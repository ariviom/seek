"""Channels: the YouTube channels the knowledge base is built from. Functions are blocking; run them through
Database.run."""

import sqlite3
from dataclasses import dataclass
from datetime import date
from types import EllipsisType
from typing import Literal

from seek.db import transaction
from seek.errors import Conflict, NotFound
from seek.ports import ChannelInfo

# How often the server checks a Channel for new Videos: every 6 hours, daily, or weekly.
type CheckHours = Literal[6, 24, 168]


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
    # None is off. A Paused Channel keeps its setting but isn't checked.
    check_every_hours: CheckHours | None = 24
    # Videos searchable (done), failed, and excluded, and when the Channel's last Sync finished successfully.
    indexed_videos: int = 0
    failed_videos: int = 0
    excluded_videos: int = 0
    last_synced_at: str | None = None
    avatar_url: str | None = None


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
        check_every_hours=row["check_every_hours"],
        indexed_videos=row["indexed_videos"],
        failed_videos=row["failed_videos"],
        excluded_videos=row["excluded_videos"],
        last_synced_at=row["last_synced_at"],
        avatar_url=row["avatar_url"],
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
    row = conn.execute(f"{_CHANNEL_SQL} WHERE channels.id = ? AND channels.in_library = 1", (channel_id,)).fetchone()
    if row is None:
        raise NotFound(f"Channel {channel_id} not found")
    return _channel(row)


def list_channels(conn: sqlite3.Connection) -> list[Channel]:
    """The Library's Channels."""
    rows = conn.execute(f"{_CHANNEL_SQL} WHERE channels.in_library = 1 ORDER BY channels.name COLLATE NOCASE, channels.id")
    return [_channel(row) for row in rows]


def create_channel(conn: sqlite3.Connection, info: ChannelInfo, name: str | None = None) -> Channel:
    """Adds the Channel under the given name, or else its display name on YouTube.

    A creator known outside the Library, crediting Videos that Playlists include, is brought into it as that same
    Channel, so those Videos are kept. It starts as a new Channel does: Active, unfiltered, checked daily, and
    not synced until the user starts its first Sync.
    """
    with transaction(conn):
        # Checked up front rather than via the UNIQUE constraint so the error can name the Channel.
        existing = conn.execute(
            "SELECT id, name, in_library FROM channels WHERE youtube_channel_id = ?", (info.channel_id,)
        ).fetchone()
        if existing is None:
            (channel_id,) = conn.execute(
                "INSERT INTO channels (youtube_channel_id, name, avatar_url) VALUES (?, ?, ?) RETURNING id",
                (info.channel_id, name or info.name, info.avatar_url),
            ).fetchone()
        elif existing["in_library"]:
            raise Conflict(f"The Channel {info.name!r} is already added as {existing['name']!r}")
        else:
            channel_id = existing["id"]
            # The values the columns default to for a Channel inserted above.
            conn.execute(
                """
                UPDATE channels SET in_library = 1, name = ?, avatar_url = coalesce(?, avatar_url), indexed = 1,
                                    check_every_hours = 24, published_after = NULL, published_before = NULL,
                                    playlist_id = NULL, most_recent = NULL
                WHERE id = ?
                """,
                (name or info.name, info.avatar_url, channel_id),
            )
        return _get_channel(conn, channel_id)


def youtube_channel_ids(conn: sqlite3.Connection) -> set[str]:
    """The YouTube channel id of every Channel, in the Library or not."""
    return {row["youtube_channel_id"] for row in conn.execute("SELECT youtube_channel_id FROM channels")}


def credited_channel(conn: sqlite3.Connection, creator: ChannelInfo) -> int:
    """Within a transaction: the id of the creator's Channel. One not yet known is created outside the Library,
    under its name on YouTube, with no filters and no checks of its own."""
    row = conn.execute("SELECT id FROM channels WHERE youtube_channel_id = ?", (creator.channel_id,)).fetchone()
    if row is None:
        row = conn.execute(
            """
            INSERT INTO channels (youtube_channel_id, name, avatar_url, in_library, check_every_hours)
            VALUES (?, ?, ?, 0, NULL)
            RETURNING id
            """,
            (creator.channel_id, creator.name, creator.avatar_url),
        ).fetchone()
    return int(row["id"])


def set_avatar(conn: sqlite3.Connection, channel_id: int, avatar_url: str) -> None:
    """Keeps the avatar a Sync's listing found; a Channel deleted meanwhile is left gone."""
    with transaction(conn):
        conn.execute("UPDATE channels SET avatar_url = ? WHERE id = ?", (avatar_url, channel_id))


def update_channel(
    conn: sqlite3.Connection,
    channel_id: int,
    name: str | None = None,
    indexed: bool | None = None,
    filters: ChannelFilters | None = None,
    check_every_hours: CheckHours | None | EllipsisType = ...,
) -> Channel:
    """Changes whichever of the name, indexed, the filters, and the check interval are given (None turns checks
    off, so leaving it unchanged is ...); filters are replaced as a whole."""
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
        if check_every_hours is not ...:
            conn.execute("UPDATE channels SET check_every_hours = ? WHERE id = ?", (check_every_hours, channel_id))
        return _get_channel(conn, channel_id)


def leave_library(conn: sqlite3.Connection, channel_id: int) -> None:
    """Within a transaction: takes the Channel out of the Library, where it stays only to credit the Videos that
    Playlists include. Its filters and its checks are cleared, and its Group memberships and Syncs removed. Its
    Conversations lose it as their scope, so they stay read-only even if the Channel is added again."""
    conn.execute(
        """
        UPDATE channels SET in_library = 0, check_every_hours = NULL, published_after = NULL,
                            published_before = NULL, playlist_id = NULL, most_recent = NULL
        WHERE id = ?
        """,
        (channel_id,),
    )
    conn.execute("DELETE FROM group_channels WHERE channel_id = ?", (channel_id,))
    conn.execute("DELETE FROM syncs WHERE channel_id = ?", (channel_id,))
    conn.execute("UPDATE conversations SET channel_id = NULL WHERE channel_id = ?", (channel_id,))
