"""Bundles in the web UI: a Channel's or a Playlist's Bundle is built on the server, then collected once as a
download, and a Bundle sent as a request's body is imported.

The Bundle itself is `bundles.export_channel`'s or `bundles.export_playlist`'s, the functions `seek export` calls;
nothing here writes one. Nor does anything here read one: an upload is stored and handed to `bundles.import_bundle`,
the function `seek import` calls, which reads it as the untrusted input it is.

What is this module's own is the keeping of both files, in the temporary directory: an upload is counted as it is
written and refused past a cap, a server takes one import at a time and none while a Sync is running or waiting to
run, a built Bundle nobody collects is deleted when its expiry comes, and what a crash left is cleared at start.
"""

import asyncio
import os
import re
import secrets
import shutil
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.requests import ClientDisconnect
from starlette.types import Receive, Scope, Send

from seek import channels, playlists, syncs, videos
from seek.bundles import (
    EXTENSION,
    ExportReport,
    ImportReport,
    Kind,
    PlaylistNameTaken,
    export_channel,
    export_playlist,
    import_bundle,
)
from seek.channels import ChannelFilters
from seek.config import Config
from seek.db import Database
from seek.errors import Conflict, NotFound
from seek.events import Events
from seek.sync_command import SyncCommandError
from seek.videos import Listed, Source


# What a refusal calls a Bundle the server is building: its path there is not for the page that asked to read.
CALLED = "the Bundle"
# And one that was sent to be imported, which the server stores under a path of its own. It begins the sentence.
UPLOADED = "The file"
# The one content type a Bundle is sent to be imported as.
UPLOAD_MEDIA_TYPE = "application/octet-stream"
# Why an import is refused for now. The first is in the words the dialog shows beside its disabled import path.
SYNC_IN_THE_WAY = "A Sync is running or waiting to run; import when it has finished."
ANOTHER_IMPORT = "Another import is running; try again when it has finished."
# The most an upload may be. It is written to the data directory's disk by anyone past Access, and the largest
# Bundle of a real Library is an eighth of this.
UPLOAD_CAP_BYTES = 2_000_000_000
# How long what is in the temporary directory has to have lain untouched for a starting server to clear it.
LEFTOVER_SECONDS = 3600


class TemporaryArea:
    """The directory where Bundles live while the server holds them, each in a directory of its own.

    It is inside the data directory, not the system's temporary one: that can be memory-backed, which a Bundle of
    hundreds of megabytes should not be, and the data directory is on the disk already sized for the knowledge base.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def prepare(self) -> None:
        """Creates the directory, readable by the user alone, and clears what a crash or a stop left in it.

        Only what was last modified over an hour ago: a second server started by mistake on the same data
        directory gets this far before it fails to take the port, and must not delete the first one's upload in
        flight.
        """
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        stale_before = time.time() - LEFTOVER_SECONDS
        for entry in self.root.iterdir():
            # One that another server removes meanwhile, or that can't be read, is left to it.
            with suppress(OSError):
                # A directory's own time is when its file was created; one still being written shows in the file's.
                if max(path.stat().st_mtime for path in (entry, *entry.rglob("*"))) >= stale_before:
                    continue
                if entry.is_dir():
                    self.remove(entry)
                else:
                    entry.unlink()

    def new_directory(self) -> Path:
        """A fresh directory under a name nobody can guess, for the caller to `remove` when it is finished with."""
        directory = self.root / secrets.token_urlsafe(16)
        directory.mkdir(mode=0o700)
        return directory

    @staticmethod
    def remove(directory: Path) -> None:
        shutil.rmtree(directory, ignore_errors=True)


class BuiltBundle(BaseModel):
    """The export's report, and the id the built Bundle is collected under."""

    id: str
    name: str
    videos: int
    segments: int
    size_bytes: int
    playlist_filter_left_out: bool


class ImportedBundle(BaseModel):
    """The import's report, and the id the Channel or Playlist has in this Library."""

    kind: Kind
    id: int
    name: str
    youtube_id: str
    created: bool
    filters: ChannelFilters | None
    added: int
    already_indexed: int
    left_out: dict[str, int]


@dataclass(frozen=True)
class _Built:
    path: Path
    file_name: str


# Path separators, the characters Windows forbids in a file name, and control characters.
_NOT_IN_A_FILE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f  ]')
_FILE_NAME_LENGTH = 100
_NOT_ASCII = re.compile(r"[^\x20-\x7e]")


def bundle_file_name(name: str) -> str:
    """The file name a Bundle of the Channel or Playlist with this name downloads under, on any system."""
    safe = _NOT_IN_A_FILE_NAME.sub("_", name).strip(". ")[:_FILE_NAME_LENGTH]
    return f"{safe or 'bundle'}{EXTENSION}"


def _content_disposition(file_name: str) -> str:
    """The header that makes a response a download under this name, which `bundle_file_name` made.

    The name goes twice, so one in another script or with an emoji survives: in the UTF-8 form, and as an ASCII
    fallback for whatever reads only that. Built by hand because the framework's file response writes one of them.
    """
    fallback = _NOT_ASCII.sub("_", file_name)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(file_name, safe='')}"


class _ServedOnce(FileResponse):
    """Sends a built Bundle, then removes its directory whether or not it was sent whole.

    Not a background task, which a response that broke partway never reaches.
    """

    def __init__(self, built: _Built) -> None:
        super().__init__(
            built.path,
            media_type="application/octet-stream",
            headers={"Content-Disposition": _content_disposition(built.file_name)},
        )
        self._directory = built.path.parent

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            TemporaryArea.remove(self._directory)


# The units the cap is named in, largest first, each a thousand of the next as the page writes a size.
_UNITS = (("GB", 10**9), ("MB", 10**6), ("KB", 10**3), ("bytes", 1))


def _too_large(cap_bytes: int) -> HTTPException:
    """The refusal of an upload over the cap, which names the cap in the largest unit it fills."""
    unit, scale = next(named for named in _UNITS if cap_bytes >= named[1])
    return HTTPException(
        status.HTTP_413_CONTENT_TOO_LARGE,
        f"{UPLOADED} is larger than {cap_bytes / scale:g} {unit}, the most the web UI imports; "
        "import it with `seek import`.",
    )


def _create(path: Path) -> BinaryIO:
    """A new file at the path, readable by the user alone as a built Bundle is."""
    return open(path, "xb", opener=lambda name, flags: os.open(name, flags, 0o600))


async def _body(request: Request, cap_bytes: int) -> AsyncIterator[bytes]:
    """The request's body a chunk at a time, refused once more of it has arrived than the cap allows: a body
    may declare no length, or a false one."""
    arrived = 0
    try:
        async for chunk in request.stream():
            arrived += len(chunk)
            if arrived > cap_bytes:
                raise _too_large(cap_bytes)
            yield chunk
    except ClientDisconnect as e:
        # An upload the browser abandoned. Nobody is left to read this, but as a refusal it ends the request
        # like any other, where the disconnect itself would be logged as a failure of the server's.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{UPLOADED} stopped arriving") from e


async def _store(request: Request, path: Path, cap_bytes: int) -> None:
    """Writes the request's body to the path a chunk at a time, so none of it is held in memory. The writes, the
    last one on closing included, run in a worker thread: the event loop is shared with every other request and
    the event stream's keepalives."""
    file = await asyncio.to_thread(_create, path)
    try:
        async for chunk in _body(request, cap_bytes):
            await asyncio.to_thread(file.write, chunk)
    finally:
        await asyncio.to_thread(file.close)


async def _discard(request: Request, cap_bytes: int) -> None:
    """Reads the request's body to its end and keeps none of it, so that the browser of an upload refused before
    it was stored receives the sentence and not a dropped connection. No further than the cap, though: a body
    that passes it is refused for that, as one being stored is."""
    async for _ in _body(request, cap_bytes):
        pass


def _imported(conn: sqlite3.Connection, report: ImportReport) -> tuple[int, list[Listed]]:
    """The id here of the Channel or Playlist an import reported, which it names by its id on YouTube, and where
    its Videos are listed, a creator at a time, as a Sync of it would tell open pages."""
    if report.kind == "channel":
        [found] = [c.id for c in channels.list_channels(conn) if c.youtube_channel_id == report.youtube_id]
    else:
        [found] = [p.id for p in playlists.list_playlists(conn) if p.youtube_playlist_id == report.youtube_id]
    return found, videos.listed_by_creator(conn, Source(report.kind, found))


def bundles_router(
    config: Config,
    database: Database,
    area: TemporaryArea,
    events: Events,
    wake_worker: Callable[[], None],
    upload_cap_bytes: int,
    built_expiry_seconds: float,
) -> APIRouter:
    router = APIRouter()
    # Bundles built and not yet collected, by the id each is collected under.
    built: dict[str, _Built] = {}
    # Whether an import is under way, uploading or importing: a server runs one at a time.
    importing = False

    def expire(bundle_id: str) -> None:
        """Deletes a built Bundle nobody collected. One that was collected is no longer in the map, which is what
        a download and this both take it out of: whichever comes first, the other finds nothing."""
        bundle = built.pop(bundle_id, None)
        if bundle is not None:
            area.remove(bundle.path.parent)

    async def build(export: Callable[[Path], ExportReport]) -> BuiltBundle:
        """Runs the export in a worker thread, since it opens a connection of its own, into a fresh directory."""
        try:
            directory = area.new_directory()
        except OSError as e:
            # In export's own words for a Bundle it can't write, and like them without the path.
            raise SyncCommandError(f"Could not write {CALLED}: {e.strerror}") from e
        try:
            report = await asyncio.to_thread(export, directory / f"bundle{EXTENSION}")
        except BaseException:
            area.remove(directory)
            raise
        bundle_id = secrets.token_urlsafe(32)
        built[bundle_id] = _Built(report.path, bundle_file_name(report.name))
        asyncio.get_running_loop().call_later(built_expiry_seconds, expire, bundle_id)
        return BuiltBundle(
            id=bundle_id,
            name=report.name,
            videos=report.videos,
            segments=report.segments,
            size_bytes=report.size_bytes,
            playlist_filter_left_out=report.playlist_filter_left_out,
        )

    @router.post("/channels/{channel_id}/bundles", status_code=status.HTTP_201_CREATED)
    async def build_channel_bundle(channel_id: int) -> BuiltBundle:
        channel = await database.run(lambda conn: channels.get_channel(conn, channel_id))
        # By its YouTube id: Channel names are not unique, and export refuses a name two Channels share.
        return await build(lambda path: export_channel(config, channel.youtube_channel_id, path, called=CALLED))

    @router.post("/playlists/{playlist_id}/bundles", status_code=status.HTTP_201_CREATED)
    async def build_playlist_bundle(playlist_id: int) -> BuiltBundle:
        playlist = await database.run(lambda conn: playlists.get_playlist(conn, playlist_id))
        # By its YouTube playlist id, as a Channel is by its own.
        return await build(lambda path: export_playlist(config, playlist.youtube_playlist_id, path, called=CALLED))

    @router.get("/bundles/{bundle_id}")
    async def collect_bundle(bundle_id: str) -> FileResponse:
        # Taken out before it is sent, so it is served once.
        bundle = built.pop(bundle_id, None)
        if bundle is None:
            raise NotFound("That Bundle is not here to download; export it again")
        return _ServedOnce(bundle)

    @router.post("/bundles")
    async def import_uploaded_bundle(request: Request) -> ImportedBundle:
        # First, and before any of the body is read: this is what closes the route to a form on another site. A
        # page there can send a form's three content types without asking, and this one only after a preflight
        # that Seek never grants. A parameter after the type is ignored.
        media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if media_type != UPLOAD_MEDIA_TYPE:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"A Bundle is imported as the body of the request, sent as {UPLOAD_MEDIA_TYPE}",
            )
        # A length declared over the cap is refused on its word, with none of the body read, and ahead of the
        # checks below, so it neither takes the place of the one import nor waits for a Sync.
        if int(request.headers.get("content-length", 0)) > upload_cap_bytes:
            raise _too_large(upload_cap_bytes)
        nonlocal importing
        if importing:
            await _discard(request, upload_cap_bytes)
            raise Conflict(ANOTHER_IMPORT)
        # Taken with no await since it was found free, so two requests can't both find it so.
        importing = True
        try:
            # The condition the dialog disables its import path on. The import function would refuse a running
            # Sync itself, once the whole file had been stored; a queued one only this refuses.
            if await database.run(syncs.has_work):
                await _discard(request, upload_cap_bytes)
                raise Conflict(SYNC_IN_THE_WAY)
            directory = area.new_directory()
            try:
                path = directory / f"upload{EXTENSION}"
                await _store(request, path, upload_cap_bytes)
                # In a worker thread, as a build is: it opens connections of its own, and takes the Sync lease,
                # which a Sync that started since the check above holds. From here the import runs to its end
                # whether or not the browser is still there: the server cancels no request for its connection
                # having gone, so the hold and the wake below wait for it too.
                report = await asyncio.to_thread(import_bundle, config, path, called=UPLOADED)
            except PlaylistNameTaken as e:
                # The command's sentence points at a flag; here the way out is the other Playlist's Rename.
                raise PlaylistNameTaken(e.name, "rename it, then import the file again.") from e
            finally:
                area.remove(directory)
        finally:
            # However it ended, an upload the browser abandoned included: that raises out of the body's stream.
            importing = False
            # A Sync queued while the import held the lease found the worker unable to take it, and the worker
            # would otherwise look again only at its next poll.
            wake_worker()
        entry_id, listed = await database.run(lambda conn: _imported(conn, report))
        # Published here, on the event loop, never from the import's thread; and only for an import that completed,
        # since a refusal names no entry. Every open page reloads its Channels, Playlists, and Videos table on it.
        for creator in listed:
            events.videos(creator)
        return ImportedBundle(
            kind=report.kind,
            id=entry_id,
            name=report.name,
            youtube_id=report.youtube_id,
            created=report.created,
            filters=report.filters,
            added=report.added,
            already_indexed=report.already_indexed,
            left_out=report.left_out,
        )

    return router
