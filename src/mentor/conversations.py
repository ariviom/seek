"""Conversations and their messages. Functions are blocking; run them through Database.run."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Literal

from mentor.db import now_iso, transaction
from mentor.errors import Conflict, NotFound
from mentor.ports import PastMessage
from mentor.scope import CHANNEL_IN_SCOPE, SCOPE_NOUN, Scope, ScopeKind, scope_params
from mentor.sources import watch_url


@dataclass(frozen=True)
class ConversationScope:
    """What the Conversation consults, as stored: the scope.Scope it was created with, whose id is None once the
    Group or Channel is deleted, and the name it last had."""

    kind: ScopeKind
    id: int | None
    name: str


@dataclass(frozen=True)
class Conversation:
    id: int
    scope: ConversationScope
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
    channel_name: str
    url: str
    # None for Citations saved before publish dates were kept.
    published_on: str | None = None
    # None for a Citation saved before Channel ids were kept whose Video is gone.
    channel_id: int | None = None


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
    # The title given to the Conversation, or else its first question, shortened.
    title: str
    message_count: int
    last_message_at: str | None


@dataclass(frozen=True)
class ConversationDetail(Conversation):
    messages: list[Message]


@dataclass(frozen=True)
class Turn:
    """What a new turn needs: the scope it consults, the Claude session to resume, and the messages before it."""

    conversation_id: int
    scope: Scope
    scope_name: str
    channel_names: list[str]
    model: str | None
    claude_session_id: str | None
    history: list[PastMessage]


TITLE_LENGTH = 80

_CONVERSATION_COLUMNS = "id, group_id, channel_id, scope_kind, scope_name, model, created_at"


def _message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        role=row["role"],
        content=row["content"],
        tool_calls=[ToolUse(**t) for t in json.loads(row["tool_calls"])],
        citations=[Citation(**c) for c in json.loads(row["citations"])],
        created_at=row["created_at"],
    )


def _scope(row: sqlite3.Row) -> ConversationScope:
    kind: ScopeKind = row["scope_kind"]
    scope_id = row["group_id"] if kind == "group" else row["channel_id"]
    return ConversationScope(kind=kind, id=scope_id, name=row["scope_name"])


def _conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(id=row["id"], scope=_scope(row), model=row["model"], created_at=row["created_at"])


def _title(question: str | None) -> str:
    if question is None:
        return "New Conversation"
    words = " ".join(question.split())
    return words if len(words) <= TITLE_LENGTH else words[: TITLE_LENGTH - 1].rstrip() + "…"


def _summaries(conn: sqlite3.Connection, where: str, params: tuple[object, ...]) -> list[ConversationSummary]:
    rows = conn.execute(
        f"""
        SELECT conversations.*,
               (SELECT content FROM messages WHERE conversation_id = conversations.id AND role = 'user'
                ORDER BY id LIMIT 1) AS first_question,
               (SELECT count(*) FROM messages WHERE conversation_id = conversations.id) AS message_count,
               (SELECT max(created_at) FROM messages WHERE conversation_id = conversations.id) AS last_message_at,
               (SELECT max(id) FROM messages WHERE conversation_id = conversations.id) AS last_message_id
        FROM conversations
        WHERE {where}
        -- Message ids order activity more finely than second-resolution timestamps; unused Conversations come last.
        ORDER BY coalesce(last_message_id, 0) DESC, id DESC
        """,
        params,
    )
    return [
        ConversationSummary(
            id=row["id"],
            scope=_scope(row),
            model=row["model"],
            created_at=row["created_at"],
            title=row["title"] or _title(row["first_question"]),
            message_count=row["message_count"],
            last_message_at=row["last_message_at"],
        )
        for row in rows
    ]


def list_conversations(
    conn: sqlite3.Connection, group_id: int | None = None, channel_id: int | None = None
) -> list[ConversationSummary]:
    """Every Conversation, or a Group's or a Channel's, most recently active first. Conversations of deleted Groups
    and Channels are included in the full list."""
    return _summaries(
        conn, "(?1 IS NULL OR group_id = ?1) AND (?2 IS NULL OR channel_id = ?2)", (group_id, channel_id)
    )


def rename_conversation(conn: sqlite3.Connection, conversation_id: int, title: str) -> ConversationSummary:
    with transaction(conn):
        if conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)).rowcount == 0:
            raise NotFound(f"Conversation {conversation_id} not found")
        [summary] = _summaries(conn, "conversations.id = ?", (conversation_id,))
        return summary


def delete_conversation(conn: sqlite3.Connection, conversation_id: int) -> None:
    with transaction(conn):
        if conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,)).rowcount == 0:
            raise NotFound(f"Conversation {conversation_id} not found")


def get_conversation(conn: sqlite3.Connection, conversation_id: int) -> ConversationDetail:
    row = conn.execute(f"SELECT {_CONVERSATION_COLUMNS} FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if row is None:
        raise NotFound(f"Conversation {conversation_id} not found")
    messages = conn.execute("SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,))
    return ConversationDetail(**vars(_conversation(row)), messages=[_message(m) for m in messages])


def _answerable_scope_name(conn: sqlite3.Connection, scope: Scope) -> str:
    """The scope's name, or Conflict if it cannot answer yet: a paused Channel, or a Group with no Channels."""
    if scope.kind == "group":
        group = conn.execute("SELECT name FROM groups WHERE id = ?", (scope.id,)).fetchone()
        if group is None:
            raise NotFound(f"Group {scope.id} not found")
        if conn.execute("SELECT 1 FROM group_channels WHERE group_id = ? LIMIT 1", (scope.id,)).fetchone() is None:
            raise Conflict(f"The Group {group['name']!r} has no Channels yet, so nothing can answer")
        return str(group["name"])
    channel = conn.execute("SELECT name, indexed FROM channels WHERE id = ?", (scope.id,)).fetchone()
    if channel is None:
        raise NotFound(f"Channel {scope.id} not found")
    if not channel["indexed"]:
        raise Conflict(f"The Channel {channel['name']!r} is paused, so it can't answer")
    return str(channel["name"])


def create_conversation(conn: sqlite3.Connection, scope: Scope, model: str | None) -> Conversation:
    with transaction(conn):
        name = _answerable_scope_name(conn, scope)
        row = conn.execute(
            f"""
            INSERT INTO conversations (group_id, channel_id, scope_kind, scope_name, model, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            RETURNING {_CONVERSATION_COLUMNS}
            """,
            (
                scope.id if scope.kind == "group" else None,
                scope.id if scope.kind == "channel" else None,
                scope.kind,
                name,
                model,
                now_iso(),
            ),
        ).fetchone()
        return _conversation(row)


def begin_turn(conn: sqlite3.Connection, conversation_id: int, message: str) -> Turn:
    """Saves the user's message, before any answer, and returns what the turn needs."""
    with transaction(conn):
        row = conn.execute(
            f"SELECT {_CONVERSATION_COLUMNS}, claude_session_id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"Conversation {conversation_id} not found")
        scope = _scope(row)
        if scope.id is None:
            raise Conflict(f"The {SCOPE_NOUN[scope.kind]} {scope.name!r} was deleted, so this Conversation is read-only")
        live = Scope(scope.kind, scope.id)
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
        channels = conn.execute(
            f"SELECT name FROM channels WHERE {CHANNEL_IN_SCOPE} ORDER BY name COLLATE NOCASE, id", scope_params(live)
        )
        return Turn(
            conversation_id=conversation_id,
            scope=live,
            scope_name=scope.name,
            channel_names=[channel["name"] for channel in channels],
            model=row["model"],
            claude_session_id=row["claude_session_id"],
            history=history,
        )


def _citations(conn: sqlite3.Connection, scope: Scope, links: Sequence[tuple[str, int]]) -> list[Citation]:
    """Citations for the (YouTube video id, seconds) links that are to searchable Videos of the scope's Channels.

    Links to any other Video, including made-up ones, are not Citations.
    """
    rows = conn.execute(
        f"""
        SELECT videos.id, videos.youtube_video_id, videos.title, videos.published_on,
               channels.id AS channel_id, channels.name AS channel_name
        FROM videos
        JOIN channels ON channels.id = videos.channel_id
        WHERE {CHANNEL_IN_SCOPE} AND channels.indexed = 1 AND videos.pipeline_stage = 'done'
          AND videos.youtube_video_id IN (SELECT value FROM json_each(:links))
        """,
        {**scope_params(scope), "links": json.dumps([video_id for video_id, _ in links])},
    )
    videos = {row["youtube_video_id"]: row for row in rows}
    return [
        Citation(
            video_id=video["id"],
            youtube_video_id=youtube_video_id,
            seconds=seconds,
            video_title=video["title"],
            channel_name=video["channel_name"],
            url=watch_url(youtube_video_id, seconds),
            published_on=video["published_on"],
            channel_id=video["channel_id"],
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
        citations = _citations(conn, turn.scope, links)
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
