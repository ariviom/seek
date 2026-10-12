"""Bundles in the web UI: a Channel's Bundle is built on the server, then collected once as a download.

The Bundle itself is `bundles.export_channel`'s, the function `seek export` calls; nothing here writes one.
"""

import asyncio
import re
import secrets
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.types import Receive, Scope, Send

from seek import channels
from seek.bundles import EXTENSION, ExportReport, export_channel
from seek.config import Config
from seek.db import Database
from seek.errors import NotFound
from seek.sync_command import SyncCommandError


# What a refusal calls a Bundle the server is building: its path there is not for the page that asked to read.
CALLED = "the Bundle"


class TemporaryArea:
    """The directory where Bundles live while the server holds them, each in a directory of its own.

    It is inside the data directory, not the system's temporary one: that can be memory-backed, which a Bundle of
    hundreds of megabytes should not be, and the data directory is on the disk already sized for the knowledge base.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def prepare(self) -> None:
        """Creates the directory, readable by the user alone."""
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

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


def bundles_router(config: Config, database: Database, area: TemporaryArea) -> APIRouter:
    router = APIRouter()
    # Bundles built and not yet collected, by the id each is collected under.
    built: dict[str, _Built] = {}

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

    @router.get("/bundles/{bundle_id}")
    async def collect_bundle(bundle_id: str) -> FileResponse:
        # Taken out before it is sent, so it is served once.
        bundle = built.pop(bundle_id, None)
        if bundle is None:
            raise NotFound("That Bundle is not here to download; export it again")
        return _ServedOnce(bundle)

    return router
