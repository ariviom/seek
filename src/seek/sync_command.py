"""`seek sync`: hands Syncs to the running server, or runs them in this process when no server answers."""

import asyncio
import json
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

from seek import channels, db, playlists, syncs
from seek.channels import Channel
from seek.config import HOST, Config
from seek.events import Events
from seek.playlists import Playlist
from seek.ports import Embedder, TranscriptSource
from seek.sync_worker import SyncWorker
from seek.syncs import Sync
from seek.videos import Source

# Loopback only: a proxy from the environment would never reach this machine's server.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class SyncCommandError(Exception):
    """The message is for the user."""


@dataclass(frozen=True)
class SyncReport:
    # The server the Syncs were handed to, or None if they ran in this process.
    server_url: str | None
    # As queued on the server, or as they finished here.
    syncs: list[Sync]


async def sync_channels(
    config: Config,
    channel: str | None,
    transcripts: TranscriptSource,
    embedder: Embedder,
    server_wait_seconds: float = 0,
    poll_seconds: float = 5.0,
    reindex: bool = False,
    playlist: str | None = None,
) -> SyncReport:
    """Syncs the Channel with this name or YouTube channel id, or the Playlist with this name or YouTube playlist
    id, or every indexed Channel and Playlist when both are None.

    A server that answers within server_wait_seconds gets the Syncs. Otherwise they run here once the embedding
    model loads, and this returns when they have finished. With reindex, the Syncs re-segment and re-embed the
    Videos already indexed.
    """
    url = f"http://{HOST}:{config.port}/"
    # Not Health: its Claude CLI check can take seconds.
    if await asyncio.to_thread(answers, f"{url}api/syncs", server_wait_seconds):
        return SyncReport(url, await asyncio.to_thread(_hand_off, url, channel, playlist, reindex))
    return SyncReport(None, await _run_here(config, channel, playlist, transcripts, embedder, poll_seconds, reindex))


def answers(url: str, seconds: float) -> bool:
    """Whether the URL answers, trying for up to `seconds`."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            with _opener.open(url, timeout=10):
                return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(1)


def find_channel(listed: list[Channel], ref: str) -> Channel:
    matching = [c for c in listed if c.youtube_channel_id == ref or c.name.casefold() == ref.casefold()]
    if not matching:
        raise SyncCommandError(f"No Channel named {ref!r}; give a Channel's name or its YouTube channel id")
    if len(matching) > 1:
        ids = ", ".join(c.youtube_channel_id for c in matching)
        raise SyncCommandError(f"More than one Channel is named {ref!r}; give one of their YouTube channel ids: {ids}")
    return matching[0]


def find_playlist(listed: list[Playlist], ref: str) -> Playlist:
    matching = [p for p in listed if p.youtube_playlist_id == ref or p.name.casefold() == ref.casefold()]
    if not matching:
        raise SyncCommandError(f"No Playlist named {ref!r}; give a Playlist's name or its YouTube playlist id")
    if len(matching) > 1:
        ids = ", ".join(p.youtube_playlist_id for p in matching)
        raise SyncCommandError(f"More than one Playlist matches {ref!r}; give one of their YouTube playlist ids: {ids}")
    return matching[0]


def request(url: str, method: str = "GET", payload: dict[str, object] | None = None) -> bytes:
    data = None if payload is None else json.dumps(payload).encode()
    headers = {} if payload is None else {"Content-Type": "application/json"}
    try:
        with _opener.open(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=30) as response:
            body: bytes = response.read()
            return body
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e)["detail"]
        except (ValueError, KeyError, TypeError):
            detail = e.reason
        raise SyncCommandError(f"The server at {url} answered {e.code}: {detail}") from e
    except OSError as e:
        raise SyncCommandError(f"The server stopped answering at {url}: {e}") from e


def _hand_off(url: str, channel: str | None, playlist: str | None, reindex: bool) -> list[Sync]:
    options: dict[str, object] = {"reindex": reindex}
    try:
        if channel is not None:
            listed = TypeAdapter(list[Channel]).validate_json(request(f"{url}api/channels"))
            path = f"channels/{find_channel(listed, channel).id}"
        elif playlist is not None:
            added = TypeAdapter(list[Playlist]).validate_json(request(f"{url}api/playlists"))
            path = f"playlists/{find_playlist(added, playlist).id}"
        else:
            return TypeAdapter(list[Sync]).validate_json(request(f"{url}api/syncs", "POST", options))
        return [TypeAdapter(Sync).validate_json(request(f"{url}api/{path}/syncs", "POST", options))]
    except ValidationError as e:
        # e.g. this upgraded seek ran against the server from before the upgrade.
        raise SyncCommandError(
            f"The server at {url} answered in a form this Seek doesn't know; restart it after upgrading"
        ) from e


async def _run_here(
    config: Config,
    channel: str | None,
    playlist: str | None,
    transcripts: TranscriptSource,
    embedder: Embedder,
    poll_seconds: float,
    reindex: bool,
) -> list[Sync]:
    try:
        await asyncio.to_thread(db.initialize, config.database_path, embedder.model_name, embedder.dimension)
    except RuntimeError as e:
        # The knowledge base belongs to another embedding model or a newer seek.
        raise SyncCommandError(str(e)) from e
    database = db.Database(config.database_path)

    def enqueue(conn: sqlite3.Connection) -> list[Sync]:
        if channel is not None:
            source = Source("channel", find_channel(channels.list_channels(conn), channel).id)
        elif playlist is not None:
            source = Source("playlist", find_playlist(playlists.list_playlists(conn), playlist).id)
        else:
            return syncs.enqueue_all(conn, reindex)
        return [syncs.enqueue(conn, source, reindex)]

    queued = await database.run(enqueue)
    if not queued:
        return []
    await asyncio.to_thread(embedder.load)
    worker = SyncWorker(
        database,
        transcripts,
        embedder,
        config.min_duration_seconds,
        poll_seconds,
        Events(),
        cooldown_seconds=config.youtube_backoff_seconds,
    )
    return await worker.run_until_finished([s.id for s in queued])
