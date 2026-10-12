"""Playlists: YouTube playlists added to the Library, whose Videos may come from many Channels. Functions are
blocking; run them through Database.run."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import EllipsisType

from seek import videos
from seek.channels import CheckHours
from seek.db import transaction
from seek.errors import Conflict, NotFound
from seek.groups import ChannelSummary, channel_summaries
from seek.ports import PlaylistInfo
from seek.scope import Scope
from seek.videos import Listed, Source


@dataclass(frozen=True)
class Creator:
    """A Channel some of a Playlist's Videos are credited to, in the Library or not."""

    id: int
    name: str
    avatar_url: str | None


@dataclass(frozen=True)
class Playlist:
    id: int
    youtube_playlist_id: str
    name: str
    indexed: bool
    # None is off, as for a Channel.
    check_every_hours: CheckHours | None
    # Videos searchable (done), failed, and excluded, and when the Playlist's last Sync finished successfully.
    indexed_videos: int
    failed_videos: int
    excluded_videos: int
    last_synced_at: str | None
    # When the automatic check next queues a Sync: an interval after the latest Sync was queued. None while no
    # check is coming: Paused, checks off, or never synced.
    next_check_at: str | None
    creators: list[Creator]


# The Videos a row of the playlists table includes.
_INCLUDED = """
    FROM playlist_videos JOIN videos ON videos.id = playlist_videos.video_id
    WHERE playlist_videos.playlist_id = playlists.id
"""


def _select(conn: sqlite3.Connection, playlist_id: int | None = None) -> list[Playlist]:
    rows = conn.execute(
        f"""
        SELECT playlists.*,
               (SELECT count(*) {_INCLUDED} AND videos.pipeline_stage = 'done' AND videos.excluded_reason IS NULL
                  AND videos.failure_stage IS NULL) AS indexed_videos,
               (SELECT count(*) {_INCLUDED} AND videos.excluded_reason IS NULL
                  AND videos.failure_stage IS NOT NULL) AS failed_videos,
               (SELECT count(*) {_INCLUDED} AND videos.excluded_reason IS NOT NULL) AS excluded_videos,
               (SELECT max(finished_at) FROM syncs WHERE syncs.playlist_id = playlists.id AND syncs.status = 'done')
                 AS last_synced_at,
               (SELECT queued_at FROM syncs WHERE syncs.playlist_id = playlists.id ORDER BY syncs.id DESC LIMIT 1)
                 AS last_queued_at
        FROM playlists
        WHERE ?1 IS NULL OR playlists.id = ?1
        ORDER BY playlists.name COLLATE NOCASE, playlists.id
        """,
        (playlist_id,),
    ).fetchall()
    creators: dict[int, list[Creator]] = {row["id"]: [] for row in rows}
    credited = conn.execute(
        """
        SELECT DISTINCT playlist_videos.playlist_id, channels.id, channels.name, channels.avatar_url
        FROM playlist_videos
        JOIN videos ON videos.id = playlist_videos.video_id
        JOIN channels ON channels.id = videos.channel_id
        WHERE ?1 IS NULL OR playlist_videos.playlist_id = ?1
        ORDER BY channels.name COLLATE NOCASE, channels.id
        """,
        (playlist_id,),
    )
    for row in credited:
        creators[row["playlist_id"]].append(Creator(id=row["id"], name=row["name"], avatar_url=row["avatar_url"]))
    return [
        Playlist(
            id=row["id"],
            youtube_playlist_id=row["youtube_playlist_id"],
            name=row["name"],
            indexed=bool(row["indexed"]),
            check_every_hours=row["check_every_hours"],
            indexed_videos=row["indexed_videos"],
            failed_videos=row["failed_videos"],
            excluded_videos=row["excluded_videos"],
            last_synced_at=row["last_synced_at"],
            next_check_at=_next_check(row),
            creators=creators[row["id"]],
        )
        for row in rows
    ]


def _next_check(row: sqlite3.Row) -> str | None:
    if not row["indexed"] or row["check_every_hours"] is None or row["last_queued_at"] is None:
        return None
    due = datetime.fromisoformat(row["last_queued_at"]) + timedelta(hours=row["check_every_hours"])
    return due.isoformat(timespec="seconds")


def list_playlists(conn: sqlite3.Connection) -> list[Playlist]:
    return _select(conn)


def get_playlist(conn: sqlite3.Connection, playlist_id: int) -> Playlist:
    found = _select(conn, playlist_id)
    if not found:
        raise NotFound(f"Playlist {playlist_id} not found")
    return found[0]


@dataclass(frozen=True)
class PlaylistSummary:
    id: int
    name: str
    video_count: int
    creators: list[ChannelSummary]


def playlist_summaries(conn: sqlite3.Connection) -> list[PlaylistSummary]:
    """Every indexed Playlist, with its creators and how many searchable Videos each has in it."""
    rows = conn.execute("SELECT id, name FROM playlists WHERE indexed = 1 ORDER BY name COLLATE NOCASE, id").fetchall()
    summaries = []
    for row in rows:
        creators = channel_summaries(conn, Scope("playlist", row["id"]))
        summaries.append(
            PlaylistSummary(
                id=row["id"], name=row["name"], video_count=sum(c.video_count for c in creators), creators=creators
            )
        )
    return summaries


def create_playlist(conn: sqlite3.Connection, info: PlaylistInfo, name: str | None = None) -> Playlist:
    """Adds the Playlist under the given name, or else its title on YouTube."""
    name = name or info.title
    with transaction(conn):
        # Checked up front rather than via the UNIQUE constraints so each error can name what is in the way.
        added = conn.execute(
            "SELECT name FROM playlists WHERE youtube_playlist_id = ?", (info.playlist_id,)
        ).fetchone()
        if added is not None:
            raise Conflict(f"The playlist {info.title!r} is already added as {added['name']!r}")
        taken = conn.execute("SELECT name FROM playlists WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        if taken is not None:
            raise Conflict(f"A Playlist named {taken['name']!r} already exists")
        (playlist_id,) = conn.execute(
            "INSERT INTO playlists (youtube_playlist_id, name) VALUES (?, ?) RETURNING id", (info.playlist_id, name)
        ).fetchone()
        [playlist] = _select(conn, playlist_id)
        return playlist


def update_playlist(
    conn: sqlite3.Connection,
    playlist_id: int,
    name: str | None = None,
    indexed: bool | None = None,
    check_every_hours: CheckHours | None | EllipsisType = ...,
) -> Playlist:
    """Changes whichever of the name, indexed, and the check interval are given (None turns checks off, so leaving
    it unchanged is ...)."""
    with transaction(conn):
        if conn.execute("SELECT 1 FROM playlists WHERE id = ?", (playlist_id,)).fetchone() is None:
            raise NotFound(f"Playlist {playlist_id} not found")
        if name is not None:
            taken = conn.execute(
                "SELECT name FROM playlists WHERE name = ? COLLATE NOCASE AND id != ?", (name, playlist_id)
            ).fetchone()
            if taken is not None:
                raise Conflict(f"A Playlist named {taken['name']!r} already exists")
            conn.execute("UPDATE playlists SET name = ? WHERE id = ?", (name, playlist_id))
            # A Conversation keeps its Playlist's name for when the Playlist is gone.
            conn.execute("UPDATE conversations SET scope_name = ? WHERE playlist_id = ?", (name, playlist_id))
        if indexed is not None:
            conn.execute("UPDATE playlists SET indexed = ? WHERE id = ?", (indexed, playlist_id))
        if check_every_hours is not ...:
            conn.execute("UPDATE playlists SET check_every_hours = ? WHERE id = ?", (check_every_hours, playlist_id))
        [playlist] = _select(conn, playlist_id)
        return playlist


def delete_playlist(conn: sqlite3.Connection, playlist_id: int, min_duration_seconds: int) -> list[Listed]:
    """Removes the Playlist and its Syncs; its Conversations stay readable. Each of its Videos then stays only
    while a Library Channel or another Playlist includes it (see videos.apply_keep_rule).

    Returns where its creators' remaining Videos are listed, for the pages that list them to reload.
    """
    source = Source("playlist", playlist_id)
    with transaction(conn):
        # Read before the delete: the memberships go with the Playlist, and they are what say which Videos to settle.
        video_ids = [
            row["video_id"]
            for row in conn.execute("SELECT video_id FROM playlist_videos WHERE playlist_id = ?", (playlist_id,))
        ]
        creators = videos.creators(conn, source)
        if conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,)).rowcount == 0:
            raise NotFound(f"Playlist {playlist_id} not found")
        videos.apply_keep_rule(conn, video_ids, min_duration_seconds)
        return videos.listed_by_creator(conn, source, creators)
