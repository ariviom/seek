"""Mentors and their Channels. Functions are blocking; run them through Database.run."""

import sqlite3
from dataclasses import dataclass

from mentor.db import transaction
from mentor.errors import Conflict, NotFound
from mentor.ports import ChannelInfo


@dataclass(frozen=True)
class Channel:
    id: int
    youtube_channel_id: str
    name: str
    indexed: bool


@dataclass(frozen=True)
class Mentor:
    id: int
    name: str
    channels: list[Channel]


def _select_mentors(conn: sqlite3.Connection, mentor_id: int | None = None) -> list[Mentor]:
    rows = conn.execute(
        """
        SELECT mentors.id AS mentor_id, mentors.name AS mentor_name,
               channels.id, channels.youtube_channel_id, channels.name, channels.indexed
        FROM mentors JOIN channels ON channels.mentor_id = mentors.id
        WHERE ?1 IS NULL OR mentors.id = ?1
        ORDER BY mentors.name COLLATE NOCASE, mentors.id, channels.id
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
    row = conn.execute(
        "SELECT mentor_id, id, youtube_channel_id, name, indexed FROM channels WHERE id = ?", (channel_id,)
    ).fetchone()
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
    return Channel(id=channel_id, youtube_channel_id=info.channel_id, name=info.name, indexed=True)


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


def set_channel_indexed(conn: sqlite3.Connection, channel_id: int, indexed: bool) -> Channel:
    with transaction(conn):
        _get_channel(conn, channel_id)
        conn.execute("UPDATE channels SET indexed = ? WHERE id = ?", (indexed, channel_id))
        return _get_channel(conn, channel_id)[1]


def detach_channel(conn: sqlite3.Connection, channel_id: int) -> None:
    with transaction(conn):
        mentor_id, _ = _get_channel(conn, channel_id)
        (count,) = conn.execute("SELECT count(*) FROM channels WHERE mentor_id = ?", (mentor_id,)).fetchone()
        if count == 1:
            raise Conflict("A Mentor needs at least one Channel; delete the Mentor instead")
        conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
