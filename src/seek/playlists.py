"""Playlists: YouTube playlists added to the Library, whose Videos may come from many Channels. Functions are
blocking; run them through Database.run."""

import sqlite3
from dataclasses import dataclass

from seek.channels import CheckHours
from seek.db import transaction
from seek.errors import Conflict
from seek.ports import PlaylistInfo


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
                 AS last_synced_at
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
            creators=creators[row["id"]],
        )
        for row in rows
    ]


def list_playlists(conn: sqlite3.Connection) -> list[Playlist]:
    return _select(conn)


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
