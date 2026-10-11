"""Groups: named sets of Channels consulted together. Functions are blocking; run them through Database.run."""

import json
import sqlite3
from dataclasses import dataclass

from seek.db import transaction
from seek.errors import Conflict, NotFound
from seek.scope import CHANNEL_IN_SCOPE, VIDEO_IN_SCOPE, Scope, scope_params


@dataclass(frozen=True)
class GroupMember:
    id: int
    name: str


@dataclass(frozen=True)
class Group:
    id: int
    name: str
    channels: list[GroupMember]


def _select_groups(conn: sqlite3.Connection, group_id: int | None = None) -> list[Group]:
    rows = conn.execute(
        """
        SELECT groups.id AS group_id, groups.name AS group_name,
               channels.id AS channel_id, channels.name AS channel_name
        FROM groups
        LEFT JOIN group_channels ON group_channels.group_id = groups.id
        LEFT JOIN channels ON channels.id = group_channels.channel_id
        WHERE ?1 IS NULL OR groups.id = ?1
        ORDER BY groups.name COLLATE NOCASE, groups.id, channels.name COLLATE NOCASE, channels.id
        """,
        (group_id,),
    )
    groups: dict[int, Group] = {}
    for row in rows:
        group = groups.setdefault(row["group_id"], Group(id=row["group_id"], name=row["group_name"], channels=[]))
        if row["channel_id"] is not None:
            group.channels.append(GroupMember(id=row["channel_id"], name=row["channel_name"]))
    return list(groups.values())


@dataclass(frozen=True)
class ChannelSummary:
    id: int
    name: str
    # Its searchable Videos that the scope it is listed in covers.
    video_count: int


@dataclass(frozen=True)
class GroupSummary:
    id: int
    name: str
    video_count: int
    channels: list[ChannelSummary]


def group_summaries(conn: sqlite3.Connection, group_id: int | None = None) -> list[GroupSummary]:
    """Every Group, or just the given one, with its Channels and how many searchable Videos each has."""
    rows = conn.execute(
        "SELECT id, name FROM groups WHERE ?1 IS NULL OR id = ?1 ORDER BY name COLLATE NOCASE, id", (group_id,)
    ).fetchall()
    summaries = []
    for row in rows:
        channels = channel_summaries(conn, Scope("group", row["id"]))
        summaries.append(
            GroupSummary(
                id=row["id"], name=row["name"], video_count=sum(c.video_count for c in channels), channels=channels
            )
        )
    return summaries


def channel_summaries(conn: sqlite3.Connection, scope: Scope | None = None) -> list[ChannelSummary]:
    """Every indexed Channel, or the scope's Channels (indexed or not), with how many of its Videos the scope
    covers."""
    rows = conn.execute(
        f"""
        SELECT channels.id, channels.name,
               (SELECT count(*) FROM videos WHERE videos.channel_id = channels.id AND {VIDEO_IN_SCOPE}) AS video_count
        FROM channels
        WHERE (:scope_kind IS NOT NULL OR channels.indexed = 1) AND {CHANNEL_IN_SCOPE}
        ORDER BY channels.name COLLATE NOCASE, channels.id
        """,
        scope_params(scope),
    )
    return [ChannelSummary(id=row["id"], name=row["name"], video_count=row["video_count"]) for row in rows]


def _get_group(conn: sqlite3.Connection, group_id: int) -> Group:
    found = _select_groups(conn, group_id)
    if not found:
        raise NotFound(f"Group {group_id} not found")
    return found[0]


def _require_group(conn: sqlite3.Connection, group_id: int) -> None:
    if conn.execute("SELECT 1 FROM groups WHERE id = ?", (group_id,)).fetchone() is None:
        raise NotFound(f"Group {group_id} not found")


def _name_taken(conn: sqlite3.Connection, name: str, except_id: int | None = None) -> None:
    row = conn.execute("SELECT id, name FROM groups WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if row is not None and row["id"] != except_id:
        raise Conflict(f"A Group named {row['name']!r} already exists")


def list_groups(conn: sqlite3.Connection) -> list[Group]:
    return _select_groups(conn)


def create_group(conn: sqlite3.Connection, name: str) -> Group:
    with transaction(conn):
        _name_taken(conn, name)
        (group_id,) = conn.execute("INSERT INTO groups (name) VALUES (?) RETURNING id", (name,)).fetchone()
        return _get_group(conn, group_id)


def rename_group(conn: sqlite3.Connection, group_id: int, name: str) -> Group:
    with transaction(conn):
        _require_group(conn, group_id)
        _name_taken(conn, name, except_id=group_id)
        conn.execute("UPDATE groups SET name = ? WHERE id = ?", (name, group_id))
        # A Conversation keeps its Group's name for when the Group is gone.
        conn.execute("UPDATE conversations SET scope_name = ? WHERE group_id = ?", (name, group_id))
        return _get_group(conn, group_id)


def delete_group(conn: sqlite3.Connection, group_id: int) -> None:
    with transaction(conn):
        if conn.execute("DELETE FROM groups WHERE id = ?", (group_id,)).rowcount == 0:
            raise NotFound(f"Group {group_id} not found")


def set_members(conn: sqlite3.Connection, group_id: int, channel_ids: list[int]) -> Group:
    unique_ids = list(dict.fromkeys(channel_ids))
    with transaction(conn):
        _require_group(conn, group_id)
        # Bound as one JSON array: no placeholder per id, and ids beyond SQLite's integer range simply match nothing.
        found = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM channels WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(unique_ids),)
            )
        }
        if missing := [channel_id for channel_id in unique_ids if channel_id not in found]:
            raise NotFound(f"Channel {missing[0]} not found")
        conn.execute("DELETE FROM group_channels WHERE group_id = ?", (group_id,))
        conn.executemany(
            "INSERT INTO group_channels (group_id, channel_id) VALUES (?, ?)",
            [(group_id, channel_id) for channel_id in unique_ids],
        )
        return _get_group(conn, group_id)
