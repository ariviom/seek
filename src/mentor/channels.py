"""Channels: the YouTube channels the knowledge base is built from. Functions are blocking; run them through
Database.run."""

import sqlite3
from dataclasses import dataclass
from datetime import date

from mentor.db import transaction
from mentor.errors import Conflict, NotFound
from mentor.ports import ChannelInfo


@dataclass(frozen=True)
class ChannelFilters:
    """Scope a Channel's ingestion; each is off when None. Dates are inclusive."""

    published_after: date | None = None
    published_before: date | None = None
    playlist_id: str | None = None
    # Only this many of the newest otherwise-eligible Videos.
    most_recent: int | None = None


@dataclass(frozen=True)
class Channel:
    id: int
    youtube_channel_id: str
    name: str
    indexed: bool
    filters: ChannelFilters
    # Videos searchable (done), failed, and excluded, and when the Channel's last Sync finished successfully.
    indexed_videos: int = 0
    failed_videos: int = 0
    excluded_videos: int = 0
    last_synced_at: str | None = None


# The channels table with each Channel's Video counts and last completed Sync.
_CHANNEL_SQL = """
    SELECT channels.*,
           (SELECT count(*) FROM videos WHERE videos.channel_id = channels.id AND videos.pipeline_stage = 'done'
              AND videos.excluded_reason IS NULL AND videos.failure_stage IS NULL) AS indexed_videos,
           (SELECT count(*) FROM videos WHERE videos.channel_id = channels.id AND videos.excluded_reason IS NULL
              AND videos.failure_stage IS NOT NULL) AS failed_videos,
           (SELECT count(*) FROM videos WHERE videos.channel_id = channels.id
              AND videos.excluded_reason IS NOT NULL) AS excluded_videos,
           (SELECT max(finished_at) FROM syncs WHERE syncs.channel_id = channels.id AND syncs.status = 'done')
              AS last_synced_at
    FROM channels
"""


def _channel(row: sqlite3.Row) -> Channel:
    return Channel(
        id=row["id"],
        youtube_channel_id=row["youtube_channel_id"],
        name=row["name"],
        indexed=bool(row["indexed"]),
        filters=read_filters(row),
        indexed_videos=row["indexed_videos"],
        failed_videos=row["failed_videos"],
        excluded_videos=row["excluded_videos"],
        last_synced_at=row["last_synced_at"],
    )


def read_filters(row: sqlite3.Row) -> ChannelFilters:
    """The filters from a row holding the channels table's filter columns."""
    return ChannelFilters(
        published_after=date.fromisoformat(row["published_after"]) if row["published_after"] else None,
        published_before=date.fromisoformat(row["published_before"]) if row["published_before"] else None,
        playlist_id=row["playlist_id"],
        most_recent=row["most_recent"],
    )


def _get_channel(conn: sqlite3.Connection, channel_id: int) -> Channel:
    row = conn.execute(f"{_CHANNEL_SQL} WHERE channels.id = ?", (channel_id,)).fetchone()
    if row is None:
        raise NotFound(f"Channel {channel_id} not found")
    return _channel(row)


def list_channels(conn: sqlite3.Connection) -> list[Channel]:
    return [_channel(row) for row in conn.execute(f"{_CHANNEL_SQL} ORDER BY channels.name COLLATE NOCASE, channels.id")]


def create_channel(conn: sqlite3.Connection, info: ChannelInfo, name: str | None = None) -> Channel:
    """Adds the Channel under the given name, or else its display name on YouTube."""
    with transaction(conn):
        # Checked up front rather than via the UNIQUE constraint so the error can name the Channel.
        existing = conn.execute("SELECT name FROM channels WHERE youtube_channel_id = ?", (info.channel_id,)).fetchone()
        if existing is not None:
            raise Conflict(f"The Channel {info.name!r} is already added as {existing['name']!r}")
        (channel_id,) = conn.execute(
            "INSERT INTO channels (youtube_channel_id, name) VALUES (?, ?) RETURNING id",
            (info.channel_id, name or info.name),
        ).fetchone()
        return _get_channel(conn, channel_id)


def update_channel(
    conn: sqlite3.Connection,
    channel_id: int,
    name: str | None = None,
    indexed: bool | None = None,
    filters: ChannelFilters | None = None,
) -> Channel:
    """Changes whichever of the name, indexed, and the filters are given; filters are replaced as a whole."""
    with transaction(conn):
        _get_channel(conn, channel_id)
        if name is not None:
            conn.execute("UPDATE channels SET name = ? WHERE id = ?", (name, channel_id))
            # A Conversation keeps its Channel's name for when the Channel is gone.
            conn.execute("UPDATE conversations SET scope_name = ? WHERE channel_id = ?", (name, channel_id))
        if indexed is not None:
            conn.execute("UPDATE channels SET indexed = ? WHERE id = ?", (indexed, channel_id))
        if filters is not None:
            conn.execute(
                """
                UPDATE channels SET published_after = ?, published_before = ?, playlist_id = ?, most_recent = ?
                WHERE id = ?
                """,
                (
                    filters.published_after and filters.published_after.isoformat(),
                    filters.published_before and filters.published_before.isoformat(),
                    filters.playlist_id,
                    filters.most_recent,
                    channel_id,
                ),
            )
        return _get_channel(conn, channel_id)


def delete_channel(conn: sqlite3.Connection, channel_id: int) -> None:
    """Removes the Channel, everything ingested from it, and its Group memberships; its Conversations stay readable."""
    with transaction(conn):
        if conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,)).rowcount == 0:
            raise NotFound(f"Channel {channel_id} not found")
