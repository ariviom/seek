"""Mentor Groups and their member Mentors. Functions are blocking; run them through Database.run."""

import json
import sqlite3
from dataclasses import dataclass

from mentor.db import transaction
from mentor.errors import Conflict, NotFound


@dataclass(frozen=True)
class GroupMember:
    id: int
    name: str


@dataclass(frozen=True)
class MentorGroup:
    id: int
    name: str
    mentors: list[GroupMember]


def _select_groups(conn: sqlite3.Connection, group_id: int | None = None) -> list[MentorGroup]:
    rows = conn.execute(
        """
        SELECT mentor_groups.id AS group_id, mentor_groups.name AS group_name,
               mentors.id AS mentor_id, mentors.name AS mentor_name
        FROM mentor_groups
        LEFT JOIN mentor_group_members ON mentor_group_members.group_id = mentor_groups.id
        LEFT JOIN mentors ON mentors.id = mentor_group_members.mentor_id
        WHERE ?1 IS NULL OR mentor_groups.id = ?1
        ORDER BY mentor_groups.name COLLATE NOCASE, mentor_groups.id, mentors.name COLLATE NOCASE, mentors.id
        """,
        (group_id,),
    )
    groups: dict[int, MentorGroup] = {}
    for row in rows:
        group = groups.setdefault(
            row["group_id"], MentorGroup(id=row["group_id"], name=row["group_name"], mentors=[])
        )
        if row["mentor_id"] is not None:
            group.mentors.append(GroupMember(id=row["mentor_id"], name=row["mentor_name"]))
    return list(groups.values())


@dataclass(frozen=True)
class MentorSummary:
    id: int
    name: str
    # Searchable Videos: done, on indexed Channels.
    video_count: int


@dataclass(frozen=True)
class GroupSummary:
    id: int
    name: str
    video_count: int
    mentors: list[MentorSummary]


def group_summaries(conn: sqlite3.Connection) -> list[GroupSummary]:
    """Every Group with its Mentors and how many searchable Videos each has."""
    rows = conn.execute(
        """
        SELECT mentor_groups.id AS group_id, mentor_groups.name AS group_name,
               mentors.id AS mentor_id, mentors.name AS mentor_name,
               (SELECT count(*) FROM videos JOIN channels ON channels.id = videos.channel_id
                WHERE channels.mentor_id = mentors.id AND channels.indexed = 1 AND videos.pipeline_stage = 'done'
               ) AS video_count
        FROM mentor_groups
        LEFT JOIN mentor_group_members ON mentor_group_members.group_id = mentor_groups.id
        LEFT JOIN mentors ON mentors.id = mentor_group_members.mentor_id
        ORDER BY mentor_groups.name COLLATE NOCASE, mentor_groups.id, mentors.name COLLATE NOCASE, mentors.id
        """
    )
    members: dict[tuple[int, str], list[MentorSummary]] = {}
    for row in rows:
        mentors = members.setdefault((row["group_id"], row["group_name"]), [])
        if row["mentor_id"] is not None:
            mentors.append(MentorSummary(id=row["mentor_id"], name=row["mentor_name"], video_count=row["video_count"]))
    return [
        GroupSummary(id=group_id, name=name, video_count=sum(m.video_count for m in mentors), mentors=mentors)
        for (group_id, name), mentors in members.items()
    ]


def _get_group(conn: sqlite3.Connection, group_id: int) -> MentorGroup:
    found = _select_groups(conn, group_id)
    if not found:
        raise NotFound(f"Mentor Group {group_id} not found")
    return found[0]


def _require_group(conn: sqlite3.Connection, group_id: int) -> None:
    if conn.execute("SELECT 1 FROM mentor_groups WHERE id = ?", (group_id,)).fetchone() is None:
        raise NotFound(f"Mentor Group {group_id} not found")


def _name_taken(conn: sqlite3.Connection, name: str, except_id: int | None = None) -> None:
    row = conn.execute("SELECT id, name FROM mentor_groups WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if row is not None and row["id"] != except_id:
        raise Conflict(f"A Mentor Group named {row['name']!r} already exists")


def list_groups(conn: sqlite3.Connection) -> list[MentorGroup]:
    return _select_groups(conn)


def create_group(conn: sqlite3.Connection, name: str) -> MentorGroup:
    with transaction(conn):
        _name_taken(conn, name)
        (group_id,) = conn.execute("INSERT INTO mentor_groups (name) VALUES (?) RETURNING id", (name,)).fetchone()
        return _get_group(conn, group_id)


def rename_group(conn: sqlite3.Connection, group_id: int, name: str) -> MentorGroup:
    with transaction(conn):
        _require_group(conn, group_id)
        _name_taken(conn, name, except_id=group_id)
        conn.execute("UPDATE mentor_groups SET name = ? WHERE id = ?", (name, group_id))
        return _get_group(conn, group_id)


def delete_group(conn: sqlite3.Connection, group_id: int) -> None:
    with transaction(conn):
        if conn.execute("DELETE FROM mentor_groups WHERE id = ?", (group_id,)).rowcount == 0:
            raise NotFound(f"Mentor Group {group_id} not found")


def set_members(conn: sqlite3.Connection, group_id: int, mentor_ids: list[int]) -> MentorGroup:
    unique_ids = list(dict.fromkeys(mentor_ids))
    with transaction(conn):
        _require_group(conn, group_id)
        # Bound as one JSON array: no placeholder per id, and ids beyond SQLite's integer range simply match nothing.
        found = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM mentors WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(unique_ids),)
            )
        }
        if missing := [mentor_id for mentor_id in unique_ids if mentor_id not in found]:
            raise NotFound(f"Mentor {missing[0]} not found")
        conn.execute("DELETE FROM mentor_group_members WHERE group_id = ?", (group_id,))
        conn.executemany(
            "INSERT INTO mentor_group_members (group_id, mentor_id) VALUES (?, ?)",
            [(group_id, mentor_id) for mentor_id in unique_ids],
        )
        return _get_group(conn, group_id)
