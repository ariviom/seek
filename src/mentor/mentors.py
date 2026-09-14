"""Mentors and their Channels. Functions are blocking; run them through Database.run."""

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


@dataclass(frozen=True)
class Mentor:
    id: int
    name: str
    channels: list[Channel]


def _select_mentors(conn: sqlite3.Connection, mentor_id: int | None = None) -> list[Mentor]:
    rows = conn.execute(
        f"""
        SELECT mentors.name AS mentor_name, channel.*
        FROM mentors JOIN ({_CHANNEL_SQL}) AS channel ON channel.mentor_id = mentors.id
        WHERE ?1 IS NULL OR mentors.id = ?1
        ORDER BY mentors.name COLLATE NOCASE, mentors.id, channel.id
        """,
        (mentor_id,),
    )
    mentors: dict[int, Mentor] = {}
    for row in rows:
        mentor = mentors.setdefault(
            row["mentor_id"], Mentor(id=row["mentor_id"], name=row["mentor_name"], channels=[])
        )
        mentor.channels.append(_channel(row))
    return list(mentors.values())


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


def _get_mentor(conn: sqlite3.Connection, mentor_id: int) -> Mentor:
    found = _select_mentors(conn, mentor_id)
    if not found:
        raise NotFound(f"Mentor {mentor_id} not found")
    return found[0]


def _require_mentor(conn: sqlite3.Connection, mentor_id: int) -> None:
    if conn.execute("SELECT 1 FROM mentors WHERE id = ?", (mentor_id,)).fetchone() is None:
        raise NotFound(f"Mentor {mentor_id} not found")


def _get_channel(conn: sqlite3.Connection, channel_id: int) -> tuple[int, Channel]:
    row = conn.execute(f"{_CHANNEL_SQL} WHERE channels.id = ?", (channel_id,)).fetchone()
    if row is None:
        raise NotFound(f"Channel {channel_id} not found")
    return int(row["mentor_id"]), _channel(row)


def _insert_channel(conn: sqlite3.Connection, mentor_id: int, info: ChannelInfo) -> Channel:
    # Checked up front rather than via the UNIQUE constraint so the error can name the owner.
    owner = conn.execute(
        "SELECT mentors.id, mentors.name FROM channels JOIN mentors ON mentors.id = channels.mentor_id"
        " WHERE youtube_channel_id = ?",
        (info.channel_id,),
    ).fetchone()
    if owner is not None and owner["id"] == mentor_id:
        raise Conflict(f"Channel {info.name!r} is already attached to this Mentor")
    if owner is not None:
        raise Conflict(f"Channel {info.name!r} already belongs to Mentor {owner['name']!r}")
    (channel_id,) = conn.execute(
        "INSERT INTO channels (mentor_id, youtube_channel_id, name) VALUES (?, ?, ?) RETURNING id",
        (mentor_id, info.channel_id, info.name),
    ).fetchone()
    return Channel(
        id=channel_id, youtube_channel_id=info.channel_id, name=info.name, indexed=True, filters=ChannelFilters()
    )


def _name_taken(conn: sqlite3.Connection, name: str, except_id: int | None = None) -> None:
    row = conn.execute("SELECT id FROM mentors WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if row is not None and row["id"] != except_id:
        raise Conflict(f"A Mentor named {name!r} already exists")


def list_mentors(conn: sqlite3.Connection) -> list[Mentor]:
    return _select_mentors(conn)


def create_mentor(conn: sqlite3.Connection, name: str, channel: ChannelInfo) -> Mentor:
    with transaction(conn):
        _name_taken(conn, name)
        (mentor_id,) = conn.execute("INSERT INTO mentors (name) VALUES (?) RETURNING id", (name,)).fetchone()
        _insert_channel(conn, mentor_id, channel)
        return _get_mentor(conn, mentor_id)


def rename_mentor(conn: sqlite3.Connection, mentor_id: int, name: str) -> Mentor:
    with transaction(conn):
        _require_mentor(conn, mentor_id)
        _name_taken(conn, name, except_id=mentor_id)
        conn.execute("UPDATE mentors SET name = ? WHERE id = ?", (name, mentor_id))
        return _get_mentor(conn, mentor_id)


def delete_mentor(conn: sqlite3.Connection, mentor_id: int) -> None:
    with transaction(conn):
        if conn.execute("DELETE FROM mentors WHERE id = ?", (mentor_id,)).rowcount == 0:
            raise NotFound(f"Mentor {mentor_id} not found")


def attach_channel(conn: sqlite3.Connection, mentor_id: int, info: ChannelInfo) -> Channel:
    with transaction(conn):
        _require_mentor(conn, mentor_id)
        return _insert_channel(conn, mentor_id, info)


def update_channel(
    conn: sqlite3.Connection, channel_id: int, indexed: bool | None, filters: ChannelFilters | None
) -> Channel:
    """Changes whichever of indexed and the filters are given; filters are replaced as a whole."""
    with transaction(conn):
        _get_channel(conn, channel_id)
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
        return _get_channel(conn, channel_id)[1]


def detach_channel(conn: sqlite3.Connection, channel_id: int) -> None:
    with transaction(conn):
        mentor_id, _ = _get_channel(conn, channel_id)
        (count,) = conn.execute("SELECT count(*) FROM channels WHERE mentor_id = ?", (mentor_id,)).fetchone()
        if count == 1:
            raise Conflict("A Mentor needs at least one Channel; delete the Mentor instead")
        conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
