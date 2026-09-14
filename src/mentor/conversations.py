"""Conversations and their messages. Functions are blocking; run them through Database.run."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Literal

from mentor.db import now_iso, transaction
from mentor.errors import Conflict, NotFound
from mentor.ports import PastMessage


@dataclass(frozen=True)
class Conversation:
    id: int
    # None once the Group is deleted; group_name keeps the name it last had.
    group_id: int | None
    group_name: str
    model: str | None
    created_at: str


@dataclass(frozen=True)
class ToolUse:
    name: str
    arguments: dict[str, object]
    is_error: bool


@dataclass(frozen=True)
class Citation:
    """A link in an answer to a moment of a Video, with the names it had when cited."""

    video_id: int
    youtube_video_id: str
    seconds: int
    video_title: str
    mentor_name: str
    channel_name: str
    url: str


@dataclass(frozen=True)
class Message:
    id: int
    role: Literal["user", "assistant"]
    content: str
    tool_calls: list[ToolUse]
    citations: list[Citation]
    created_at: str


@dataclass(frozen=True)
class ConversationSummary(Conversation):
    # The first question, shortened.
    title: str
    message_count: int
    last_message_at: str | None


@dataclass(frozen=True)
class ConversationDetail(Conversation):
    messages: list[Message]


@dataclass(frozen=True)
class Turn:
    """What a new turn needs: the Group it consults, the Claude session to resume, and the messages before it."""

    conversation_id: int
    group_id: int
    group_name: str
    mentor_names: list[str]
    model: str | None
    claude_session_id: str | None
    history: list[PastMessage]


TITLE_LENGTH = 80


def _message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        role=row["role"],
        content=row["content"],
        tool_calls=[ToolUse(**t) for t in json.loads(row["tool_calls"])],
        citations=[Citation(**c) for c in json.loads(row["citations"])],
        created_at=row["created_at"],
    )


def _title(question: str | None) -> str:
    if question is None:
        return "New Conversation"
    words = " ".join(question.split())
    return words if len(words) <= TITLE_LENGTH else words[: TITLE_LENGTH - 1].rstrip() + "…"


def list_conversations(conn: sqlite3.Connection, group_id: int | None = None) -> list[ConversationSummary]:
    """Every Conversation, or a Group's, most recently active first. Conversations of deleted Groups are included."""
    rows = conn.execute(
        """
        SELECT conversations.*,
               (SELECT content FROM messages WHERE conversation_id = conversations.id AND role = 'user'
                ORDER BY id LIMIT 1) AS first_question,
               (SELECT count(*) FROM messages WHERE conversation_id = conversations.id) AS message_count,
               (SELECT max(created_at) FROM messages WHERE conversation_id = conversations.id) AS last_message_at,
               (SELECT max(id) FROM messages WHERE conversation_id = conversations.id) AS last_message_id
        FROM conversations
        WHERE ?1 IS NULL OR group_id = ?1
        -- Message ids order activity more finely than second-resolution timestamps; unused Conversations come last.
        ORDER BY coalesce(last_message_id, 0) DESC, id DESC
        """,
        (group_id,),
    )
    return [
        ConversationSummary(
            id=row["id"],
            group_id=row["group_id"],
            group_name=row["group_name"],
            model=row["model"],
            created_at=row["created_at"],
            title=_title(row["first_question"]),
            message_count=row["message_count"],
            last_message_at=row["last_message_at"],
        )
        for row in rows
    ]


def get_conversation(conn: sqlite3.Connection, conversation_id: int) -> ConversationDetail:
    row = conn.execute(
        "SELECT id, group_id, group_name, model, created_at FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"Conversation {conversation_id} not found")
    messages = conn.execute("SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,))
    return ConversationDetail(**dict(row), messages=[_message(m) for m in messages])


def create_conversation(conn: sqlite3.Connection, group_id: int, model: str | None) -> Conversation:
    with transaction(conn):
        group = conn.execute("SELECT name FROM mentor_groups WHERE id = ?", (group_id,)).fetchone()
        if group is None:
            raise NotFound(f"Mentor Group {group_id} not found")
        row = conn.execute(
            """
            INSERT INTO conversations (group_id, group_name, model, created_at) VALUES (?, ?, ?, ?)
            RETURNING id, group_id, group_name, model, created_at
            """,
            (group_id, group["name"], model, now_iso()),
        ).fetchone()
        return Conversation(**dict(row))


def begin_turn(conn: sqlite3.Connection, conversation_id: int, message: str) -> Turn:
    """Saves the user's message, before any answer, and returns what the turn needs."""
    with transaction(conn):
        row = conn.execute(
            "SELECT group_id, group_name, model, claude_session_id FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise NotFound(f"Conversation {conversation_id} not found")
        if row["group_id"] is None:
            raise Conflict(f"The Mentor Group {row['group_name']!r} was deleted, so this Conversation is read-only")
        history = [
            PastMessage(role=m["role"], content=m["content"])
            for m in conn.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)
            )
        ]
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
            (conversation_id, message, now_iso()),
        )
        mentors = conn.execute(
            """
            SELECT mentors.name FROM mentors
            JOIN mentor_group_members ON mentor_group_members.mentor_id = mentors.id
            WHERE mentor_group_members.group_id = ?
            ORDER BY mentors.name COLLATE NOCASE
            """,
            (row["group_id"],),
        )
        return Turn(
            conversation_id=conversation_id,
            group_id=row["group_id"],
            group_name=row["group_name"],
            mentor_names=[mentor["name"] for mentor in mentors],
            model=row["model"],
            claude_session_id=row["claude_session_id"],
            history=history,
        )


def _citations(conn: sqlite3.Connection, group_id: int, links: Sequence[tuple[str, int]]) -> list[Citation]:
    """Citations for the (YouTube video id, seconds) links that are to searchable Videos of the Group's Mentors.

    Links to any other Video, including made-up ones, are not Citations.
    """
    rows = conn.execute(
        """
        SELECT videos.id, videos.youtube_video_id, videos.title, channels.name AS channel_name,
               mentors.name AS mentor_name
        FROM videos
        JOIN channels ON channels.id = videos.channel_id
        JOIN mentors ON mentors.id = channels.mentor_id
        JOIN mentor_group_members ON mentor_group_members.mentor_id = mentors.id
        WHERE mentor_group_members.group_id = ? AND channels.indexed = 1 AND videos.pipeline_stage = 'done'
          AND videos.youtube_video_id IN (SELECT value FROM json_each(?))
        """,
        (group_id, json.dumps([video_id for video_id, _ in links])),
    )
    videos = {row["youtube_video_id"]: row for row in rows}
    return [
        Citation(
            video_id=video["id"],
            youtube_video_id=youtube_video_id,
            seconds=seconds,
            video_title=video["title"],
            mentor_name=video["mentor_name"],
            channel_name=video["channel_name"],
            url=f"https://www.youtube.com/watch?v={youtube_video_id}&t={seconds}s",
        )
        for youtube_video_id, seconds in links
        if (video := videos.get(youtube_video_id)) is not None
    ]


def record_answer(
    conn: sqlite3.Connection,
    turn: Turn,
    content: str,
    tool_calls: list[ToolUse],
    links: Sequence[tuple[str, int]],
    claude_session_id: str,
) -> Message:
    """Saves the answer with the Citations among its links, and the session to resume next turn."""
    with transaction(conn):
        citations = _citations(conn, turn.group_id, links)
        conn.execute(
            "UPDATE conversations SET claude_session_id = ? WHERE id = ?", (claude_session_id, turn.conversation_id)
        )
        row = conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, tool_calls, citations, created_at)
            VALUES (?, 'assistant', ?, ?, ?, ?)
            RETURNING id, created_at
            """,
            (
                turn.conversation_id,
                content,
                json.dumps([asdict(t) for t in tool_calls]),
                json.dumps([asdict(c) for c in citations]),
                now_iso(),
            ),
        ).fetchone()
        return Message(
            id=row["id"],
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            citations=citations,
            created_at=row["created_at"],
        )
