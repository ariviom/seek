"""Mentors and their Channels. Functions are blocking; run them through Database.run."""

import sqlite3
from dataclasses import dataclass

from mentor.db import transaction
from mentor.ports import ChannelInfo


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


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


def _get(conn: sqlite3.Connection, mentor_id: int) -> Mentor:
    row = conn.execute("SELECT id, name FROM mentors WHERE id = ?", (mentor_id,)).fetchone()
    if row is None:
        raise NotFound(f"Mentor {mentor_id} not found")
    return Mentor(id=row["id"], name=row["name"], channels=_channels(conn, mentor_id))


def _channels(conn: sqlite3.Connection, mentor_id: int) -> list[Channel]:
    rows = conn.execute(
        "SELECT id, youtube_channel_id, name, indexed FROM channels WHERE mentor_id = ? ORDER BY id",
        (mentor_id,),
    )
    return [Channel(r["id"], r["youtube_channel_id"], r["name"], bool(r["indexed"])) for r in rows]


def _name_conflict(name: str) -> Conflict:
    return Conflict(f"A Mentor named {name!r} already exists")


def _insert_channel(conn: sqlite3.Connection, mentor_id: int, info: ChannelInfo) -> Channel:
    owner = conn.execute(
        "SELECT mentors.name FROM channels JOIN mentors ON mentors.id = channels.mentor_id"
        " WHERE youtube_channel_id = ?",
        (info.channel_id,),
    ).fetchone()
    if owner is not None:
        raise Conflict(f"Channel {info.name!r} already belongs to Mentor {owner['name']!r}")
    cursor = conn.execute(
        "INSERT INTO channels (mentor_id, youtube_channel_id, name) VALUES (?, ?, ?)",
        (mentor_id, info.channel_id, info.name),
    )
    assert cursor.lastrowid is not None
    return Channel(cursor.lastrowid, info.channel_id, info.name, indexed=True)


def _channel_mentor_id(conn: sqlite3.Connection, channel_id: int) -> int:
    row = conn.execute("SELECT mentor_id FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if row is None:
        raise NotFound(f"Channel {channel_id} not found")
    mentor_id: int = row["mentor_id"]
    return mentor_id


def list_mentors(conn: sqlite3.Connection) -> list[Mentor]:
    rows = conn.execute("SELECT id FROM mentors ORDER BY name COLLATE NOCASE").fetchall()
    return [_get(conn, row["id"]) for row in rows]


def create_mentor(conn: sqlite3.Connection, name: str, channel: ChannelInfo) -> Mentor:
    with transaction(conn):
        try:
            cursor = conn.execute("INSERT INTO mentors (name) VALUES (?)", (name,))
        except sqlite3.IntegrityError:
            raise _name_conflict(name) from None
        mentor_id = cursor.lastrowid
        assert mentor_id is not None
        _insert_channel(conn, mentor_id, channel)
    return _get(conn, mentor_id)


def rename_mentor(conn: sqlite3.Connection, mentor_id: int, name: str) -> Mentor:
    with transaction(conn):
        try:
            cursor = conn.execute("UPDATE mentors SET name = ? WHERE id = ?", (name, mentor_id))
        except sqlite3.IntegrityError:
            raise _name_conflict(name) from None
        if cursor.rowcount == 0:
            raise NotFound(f"Mentor {mentor_id} not found")
    return _get(conn, mentor_id)


def delete_mentor(conn: sqlite3.Connection, mentor_id: int) -> None:
    with transaction(conn):
        if conn.execute("DELETE FROM mentors WHERE id = ?", (mentor_id,)).rowcount == 0:
            raise NotFound(f"Mentor {mentor_id} not found")


def attach_channel(conn: sqlite3.Connection, mentor_id: int, info: ChannelInfo) -> Channel:
    with transaction(conn):
        _get(conn, mentor_id)
        return _insert_channel(conn, mentor_id, info)


def set_channel_indexed(conn: sqlite3.Connection, channel_id: int, indexed: bool) -> Mentor:
    with transaction(conn):
        mentor_id = _channel_mentor_id(conn, channel_id)
        conn.execute("UPDATE channels SET indexed = ? WHERE id = ?", (indexed, channel_id))
    return _get(conn, mentor_id)


def detach_channel(conn: sqlite3.Connection, channel_id: int) -> None:
    with transaction(conn):
        mentor_id = _channel_mentor_id(conn, channel_id)
        (count,) = conn.execute("SELECT count(*) FROM channels WHERE mentor_id = ?", (mentor_id,)).fetchone()
        if count == 1:
            raise Conflict("A Mentor needs at least one Channel; delete the Mentor instead")
        conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
