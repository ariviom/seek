"""Groups: named sets of Channels consulted together. Functions are blocking; run them through Database.run."""

import json
import sqlite3
from dataclasses import dataclass

from mentor.db import transaction
from mentor.errors import Conflict, NotFound
from mentor.scope import CHANNEL_IN_SCOPE, Scope, scope_params


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
    # Searchable Videos: done, on an indexed Channel.
    video_count: int


@dataclass(frozen=True)
class GroupSummary:
    id: int
    name: str
    video_count: int
    channels: list[ChannelSummary]


_VIDEO_COUNT = """(SELECT count(*) FROM videos
                   WHERE videos.channel_id = channels.id AND channels.indexed = 1 AND videos.pipeline_stage = 'done')"""


def group_summaries(conn: sqlite3.Connection, group_id: int | None = None) -> list[GroupSummary]:
    """Every Group, or just the given one, with its Channels and how many searchable Videos each has."""
    rows = conn.execute(
        f"""
        SELECT groups.id AS group_id, groups.name AS group_name, channels.id AS channel_id,
               channels.name AS channel_name, {_VIDEO_COUNT} AS video_count
        FROM groups
        LEFT JOIN group_channels ON group_channels.group_id = groups.id
        LEFT JOIN channels ON channels.id = group_channels.channel_id
        WHERE ?1 IS NULL OR groups.id = ?1
        ORDER BY groups.name COLLATE NOCASE, groups.id, channels.name COLLATE NOCASE, channels.id
        """,
        (group_id,),
    )
    members: dict[tuple[int, str], list[ChannelSummary]] = {}
    for row in rows:
        channels = members.setdefault((row["group_id"], row["group_name"]), [])
        if row["channel_id"] is not None:
            channels.append(
                ChannelSummary(id=row["channel_id"], name=row["channel_name"], video_count=row["video_count"])
            )
    return [
        GroupSummary(id=group_id, name=name, video_count=sum(c.video_count for c in channels), channels=channels)
        for (group_id, name), channels in members.items()
    ]


def channel_summaries(conn: sqlite3.Connection, scope: Scope | None = None) -> list[ChannelSummary]:
    """Every indexed Channel, or the scope's Channels (indexed or not, as group_summaries lists them), with how many
    searchable Videos each has."""
    rows = conn.execute(
        f"""
        SELECT channels.id, channels.name, {_VIDEO_COUNT} AS video_count
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
