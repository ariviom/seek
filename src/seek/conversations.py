"""Conversations and their messages. Functions are blocking; run them through Database.run."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Literal

from seek.db import now_iso, transaction
from seek.engines import NO_API_CONTEXT, ModelChoice, resolve_model
from seek.errors import Conflict, NotFound
from seek.ports import EngineName, PastMessage, TokenUsage
from seek.scope import CHANNEL_IN_SCOPE, SCOPE_NOUN, VIDEO_IN_SCOPE, Scope, ScopeKind, scope_params
from seek.sources import watch_url


@dataclass(frozen=True)
class ConversationScope:
    """What the Conversation consults, as stored: the scope.Scope it was created with, whose id is None once the
    Group or Channel is deleted, and the name it last had."""

    kind: ScopeKind
    id: int | None
    name: str


@dataclass(frozen=True)
class ConversationContext:
    """Read-only resources Claude may consult alongside the Conversation's Channel Transcripts."""

    workspace: str | None
    web_access: bool


@dataclass(frozen=True)
class Conversation:
    id: int
    scope: ConversationScope
    model: str | None
    context: ConversationContext
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
class MessageUsage:
    """What one turn's provider requests reported, recorded on the user message that started the turn."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    # False when the turn failed or was stopped before everything was reported: the numbers are a floor.
    complete: bool


@dataclass(frozen=True)
class ConversationUsage:
    """A Conversation's known usage. Not a bill: it counts what the provider reported, nothing more."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    # False when any turn reported nothing, or reported only part of what it used.
    complete: bool


@dataclass(frozen=True)
class Message:
    id: int
    role: Literal["user", "assistant"]
    content: str
    tool_calls: list[ToolUse]
    citations: list[Citation]
    created_at: str
    # None on messages saved before engines were selectable: unknown, not assumed.
    engine: EngineName | None = None
    model: str | None = None
    # On the user message of a turn that reported any usage; None when nothing was reported.
    usage: MessageUsage | None = None


@dataclass(frozen=True)
class ConversationSummary(Conversation):
    # The title given to the Conversation, or else its first question, shortened.
    title: str
    message_count: int
    last_message_at: str | None
    usage: ConversationUsage


@dataclass(frozen=True)
class ConversationDetail(Conversation):
    messages: list[Message]
    usage: ConversationUsage


@dataclass(frozen=True)
class Turn:
    """What a started turn needs: its scope, the engine and model chosen for it, and the messages before it.

    `user_message_id` is the saved question this turn's usage is recorded against, so the accounting
    survives a turn that never saves an answer.
    """

    conversation_id: int
    user_message_id: int
    scope: Scope
    scope_name: str
    channel_names: list[str]
    engine: EngineName
    model: str
    context: ConversationContext
    claude_session_id: str | None
    history: list[PastMessage]


TITLE_LENGTH = 80

_CONVERSATION_COLUMNS = (
    "id, group_id, channel_id, scope_kind, scope_name, model, workspace_path, web_access, created_at"
)


def _usage(row: sqlite3.Row) -> MessageUsage | None:
    """The turn's usage, or None where nothing was reported; record_usage writes all four columns at once."""
    if row["usage_complete"] is None:
        return None
    return MessageUsage(
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cache_read_tokens=row["cache_read_tokens"],
        complete=bool(row["usage_complete"]),
    )


def _message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        role=row["role"],
        content=row["content"],
        tool_calls=[ToolUse(**t) for t in json.loads(row["tool_calls"])],
        citations=[Citation(**c) for c in json.loads(row["citations"])],
        created_at=row["created_at"],
        engine=row["engine"],
        model=row["engine_model"],
        usage=_usage(row),
    )


# A Conversation's known usage, for one Conversation or grouped across many. A question whose turn
# reported nothing has usage_complete NULL and makes the total incomplete; an answer never carries usage
# of its own, so it is exempt.
_USAGE_TOTALS = """
    SELECT conversation_id,
           coalesce(sum(input_tokens), 0) AS input_tokens,
           coalesce(sum(output_tokens), 0) AS output_tokens,
           coalesce(sum(cache_read_tokens), 0) AS cache_read_tokens,
           min(coalesce(usage_complete, role = 'assistant')) AS usage_complete
    FROM messages GROUP BY conversation_id
"""


def _totals(row: sqlite3.Row) -> ConversationUsage:
    return ConversationUsage(
        input_tokens=row["input_tokens"] or 0,
        output_tokens=row["output_tokens"] or 0,
        cache_read_tokens=row["cache_read_tokens"] or 0,
        # No messages at all: nothing is missing, so the empty total is exact.
        complete=bool(row["usage_complete"]) if row["usage_complete"] is not None else True,
    )


def conversation_usage(conn: sqlite3.Connection, conversation_id: int) -> ConversationUsage:
    row = conn.execute(
        f"SELECT * FROM ({_USAGE_TOTALS}) WHERE conversation_id = ?", (conversation_id,)
    ).fetchone()
    return _totals(row) if row is not None else ConversationUsage(0, 0, 0, True)


def _scope(row: sqlite3.Row) -> ConversationScope:
    kind: ScopeKind = row["scope_kind"]
    scope_id = row["group_id"] if kind == "group" else row["channel_id"]
    return ConversationScope(kind=kind, id=scope_id, name=row["scope_name"])


def _conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(
        id=row["id"],
        scope=_scope(row),
        model=row["model"],
        context=ConversationContext(workspace=row["workspace_path"], web_access=bool(row["web_access"])),
        created_at=row["created_at"],
    )


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
               (SELECT max(id) FROM messages WHERE conversation_id = conversations.id) AS last_message_id,
               usage.input_tokens, usage.output_tokens, usage.cache_read_tokens, usage.usage_complete
        FROM conversations
        LEFT JOIN ({_USAGE_TOTALS}) AS usage ON usage.conversation_id = conversations.id
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
            context=ConversationContext(workspace=row["workspace_path"], web_access=bool(row["web_access"])),
            created_at=row["created_at"],
            title=row["title"] or _title(row["first_question"]),
            message_count=row["message_count"],
            last_message_at=row["last_message_at"],
            usage=_totals(row),
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
    return ConversationDetail(
        **vars(_conversation(row)),
        messages=[_message(m) for m in messages],
        usage=conversation_usage(conn, conversation_id),
    )


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


def create_conversation(
    conn: sqlite3.Connection, scope: Scope, model: str | None, context: ConversationContext | None = None
) -> Conversation:
    context = context or ConversationContext(workspace=None, web_access=False)
    with transaction(conn):
        name = _answerable_scope_name(conn, scope)
        row = conn.execute(
            f"""
            INSERT INTO conversations
                (group_id, channel_id, scope_kind, scope_name, model, workspace_path, web_access, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING {_CONVERSATION_COLUMNS}
            """,
            (
                scope.id if scope.kind == "group" else None,
                scope.id if scope.kind == "channel" else None,
                scope.kind,
                name,
                model,
                context.workspace,
                context.web_access,
                now_iso(),
            ),
        ).fetchone()
        return _conversation(row)


def begin_turn(
    conn: sqlite3.Connection, conversation_id: int, message: str, engine: EngineName, choice: ModelChoice
) -> Turn:
    """Saves the user's message with the engine and model chosen for it, and returns what the turn needs.

    An API turn also clears the stored Claude CLI session here, in the same transaction: the API keeps no
    provider-side session, so a later CLI turn must replay the whole Conversation even if this turn fails
    or is stopped. A pin this engine cannot express, or context it cannot serve, raises before anything is
    saved, so a refused turn leaves neither a stranded question nor a dropped session behind.
    """
    with transaction(conn):
        row = conn.execute(
            f"SELECT {_CONVERSATION_COLUMNS}, claude_session_id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"Conversation {conversation_id} not found")
        scope = _scope(row)
        if scope.id is None:
            raise Conflict(f"The {SCOPE_NOUN[scope.kind]} {scope.name!r} was deleted, so this Conversation is read-only")
        model = resolve_model(engine, row["model"], choice)
        context = ConversationContext(workspace=row["workspace_path"], web_access=bool(row["web_access"]))
        if engine == "api" and (context.workspace is not None or context.web_access):
            raise Conflict(NO_API_CONTEXT)
        live = Scope(scope.kind, scope.id)
        history = [
            PastMessage(role=m["role"], content=m["content"])
            for m in conn.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)
            )
        ]
        saved = conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, created_at, engine, engine_model)
            VALUES (?, 'user', ?, ?, ?, ?) RETURNING id
            """,
            (conversation_id, message, now_iso(), engine, model),
        ).fetchone()
        if engine == "api":
            conn.execute("UPDATE conversations SET claude_session_id = NULL WHERE id = ?", (conversation_id,))
        channels = conn.execute(
            f"SELECT name FROM channels WHERE {CHANNEL_IN_SCOPE} ORDER BY name COLLATE NOCASE, id", scope_params(live)
        )
        return Turn(
            conversation_id=conversation_id,
            user_message_id=saved["id"],
            scope=live,
            scope_name=scope.name,
            channel_names=[channel["name"] for channel in channels],
            engine=engine,
            model=model,
            context=context,
            claude_session_id=None if engine == "api" else row["claude_session_id"],
            history=history,
        )


def record_usage(conn: sqlite3.Connection, turn: Turn, usage: TokenUsage, complete: bool) -> None:
    """Records the turn's reported usage against the question that started it, however the turn ended.

    Only called when something was reported: a turn that reported nothing leaves the columns NULL, because
    unknown usage is not a measured zero.
    """
    with transaction(conn):
        conn.execute(
            """
            UPDATE messages
            SET input_tokens = ?, output_tokens = ?, cache_read_tokens = ?, usage_complete = ?
            WHERE id = ?
            """,
            (
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_read_tokens,
                int(complete),
                turn.user_message_id,
            ),
        )


def _citations(conn: sqlite3.Connection, scope: Scope, links: Sequence[tuple[str, int]]) -> list[Citation]:
    """Citations for the (YouTube video id, seconds) links that are to Videos the scope covers.

    Links to any other Video, including made-up ones, are not Citations.
    """
    rows = conn.execute(
        f"""
        SELECT videos.id, videos.youtube_video_id, videos.title, videos.published_on,
               channels.id AS channel_id, channels.name AS channel_name
        FROM videos
        JOIN channels ON channels.id = videos.channel_id
        WHERE {VIDEO_IN_SCOPE} AND videos.youtube_video_id IN (SELECT value FROM json_each(:links))
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
    claude_session_id: str | None,
) -> Message:
    """Saves the answer with the Citations among its links, and the session to resume next turn.

    An engine that keeps no session reports None, which leaves the stored session as this turn left it.
    """
    with transaction(conn):
        citations = _citations(conn, turn.scope, links)
        if claude_session_id is not None:
            conn.execute(
                "UPDATE conversations SET claude_session_id = ? WHERE id = ?",
                (claude_session_id, turn.conversation_id),
            )
        row = conn.execute(
            """
            INSERT INTO messages
                (conversation_id, role, content, tool_calls, citations, created_at, engine, engine_model)
            VALUES (?, 'assistant', ?, ?, ?, ?, ?, ?)
            RETURNING id, created_at
            """,
            (
                turn.conversation_id,
                content,
                json.dumps([asdict(t) for t in tool_calls]),
                json.dumps([asdict(c) for c in citations]),
                now_iso(),
                turn.engine,
                turn.model,
            ),
        ).fetchone()
        return Message(
            id=row["id"],
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            citations=citations,
            created_at=row["created_at"],
            engine=turn.engine,
            model=turn.model,
        )
