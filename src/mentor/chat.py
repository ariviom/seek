"""Web chat turns: a Conversation's question answered by the ChatEngine, using tools bound to its Mentor Group."""

import asyncio
import contextlib
import logging
import re
from dataclasses import asdict, replace
from datetime import UTC, datetime
from urllib.parse import parse_qs

from mentor import conversations
from mentor.conversations import ToolUse, Turn
from mentor.db import Database
from mentor.errors import Conflict
from mentor.mcp_server import GROUNDED_ADVISOR, GROUP_TOOL_NAMES, create_group_server
from mentor.ports import ChatDone, ChatEngine, ChatFailed, ChatRequest, TextDelta, ToolCall, ToolResult
from mentor.search import Search

log = logging.getLogger(__name__)

# What a turn's stream carries, as JSON objects with a type: text, tool_call, tool_result, then done or error.
type TurnEvent = dict[str, object]

# A YouTube watch link in any common form: youtube.com/watch?v=ID&t=90s (www., m., or neither), or youtu.be/ID?t=90.
_YOUTUBE_LINK = re.compile(
    r"(?:https?://)?(?:(?:www\.|m\.)?youtube\.com/watch\?(?P<query>[^\s)\]>\"']+)"
    r"|youtu\.be/(?P<short_id>[\w-]+)(?:\?(?P<short_query>[^\s)\]>\"']*))?)"
)
_TIMESTAMP = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?")


def system_prompt(group_name: str, mentor_names: list[str], today: str) -> str:
    mentors = ", ".join(mentor_names) if mentor_names else "none yet"
    return f"""\
You answer questions in a web chat by consulting the Mentor Group {group_name!r} (Mentors: {mentors}) through \
tools that search the Transcripts of their YouTube Videos. Today is {today}.

{GROUNDED_ADVISOR}

Use search first and expand when a Segment needs more context. Cite each claim as a Markdown link whose text names \
the Mentor, the Video title, and the timestamp, pointing at the url a tool returned; for another line of an \
expanded Transcript, set t to that line's start_seconds in whole seconds."""


def citation_links(answer: str) -> list[tuple[str, int]]:
    """The (YouTube video id, seconds) of each watch link in the answer, in order, each once; no t is 0 seconds."""
    links: dict[tuple[str, int], None] = {}
    for match in _YOUTUBE_LINK.finditer(answer):
        # Sentence punctuation after a bare link isn't part of it.
        query = (match["query"] or match["short_query"] or "").rstrip(".,;:!?").replace("&amp;", "&")
        params = parse_qs(query)
        video_id = match["short_id"] or params.get("v", [""])[0]
        timestamp = _TIMESTAMP.fullmatch(params.get("t", [""])[0])
        if re.fullmatch(r"[\w-]+", video_id) and timestamp:
            hours, minutes, seconds = (int(part or 0) for part in timestamp.groups())
            links[video_id, hours * 3600 + minutes * 60 + seconds] = None
    return list(links)


class Chat:
    """Runs at most one turn per Conversation. A turn runs to completion even if its stream's reader goes away."""

    def __init__(self, database: Database, search: Search, engine: ChatEngine) -> None:
        self._database = database
        self._search = search
        self._engine = engine
        # Conversations with a turn under way, and the turns' tasks.
        self._busy: set[int] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    async def send(self, conversation_id: int, message: str) -> asyncio.Queue[TurnEvent | None]:
        """Saves the question and starts the turn, whose events arrive on the returned queue until None.

        Raises before returning if the turn can't start.
        """
        if conversation_id in self._busy:
            raise Conflict("This Conversation is still answering; wait for it to finish")
        # Claimed before the first await, so a second message can't slip in while the first is being saved.
        self._busy.add(conversation_id)
        try:
            turn = await self._database.run(lambda conn: conversations.begin_turn(conn, conversation_id, message))
        except BaseException:
            self._busy.discard(conversation_id)
            raise
        events: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
        task = asyncio.create_task(self._run(turn, message, events))
        self._tasks.add(task)

        def finished(task: asyncio.Task[None]) -> None:
            self._tasks.discard(task)
            self._busy.discard(conversation_id)

        task.add_done_callback(finished)
        return events

    async def close(self) -> None:
        """Stops any turns still running, without saving their answers."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _run(self, turn: Turn, message: str, events: asyncio.Queue[TurnEvent | None]) -> None:
        request = ChatRequest(
            message=message,
            system_prompt=system_prompt(turn.group_name, turn.mentor_names, datetime.now(UTC).date().isoformat()),
            model=turn.model,
            resume_session_id=turn.claude_session_id,
            history=turn.history,
            tools=create_group_server(self._database, self._search, turn.group_id),
            tool_names=GROUP_TOOL_NAMES,
        )
        try:
            if await self._answer(turn, request, events):
                # The Claude session is gone (expired or cleaned up): start a new one, replaying the Conversation.
                log.info("Conversation %s's Claude session was lost; replaying it", turn.conversation_id)
                await self._answer(turn, replace(request, resume_session_id=None), events)
        except Exception:
            log.exception("Chat turn for Conversation %s failed", turn.conversation_id)
            events.put_nowait({"type": "error", "message": "The chat failed unexpectedly; see the server log"})
        finally:
            events.put_nowait(None)

    async def _answer(self, turn: Turn, request: ChatRequest, events: asyncio.Queue[TurnEvent | None]) -> bool:
        """Streams one attempt at the turn's answer, saving it when done. True if the session to resume is gone."""
        answer: list[str] = []
        uses: dict[str, ToolUse] = {}
        # Text written after a tool call starts a new paragraph; the model's separate steps don't end in whitespace.
        after_tool = False
        # Closed on return, so the engine stops its CLI process now rather than whenever it's garbage collected.
        async with contextlib.aclosing(self._engine.stream(request)) as stream:
            async for event in stream:
                match event:
                    case TextDelta(text):
                        if after_tool and answer:
                            text = "\n\n" + text
                        after_tool = False
                        answer.append(text)
                        events.put_nowait({"type": "text", "text": text})
                    case ToolCall(call_id, name, arguments):
                        after_tool = True
                        uses[call_id] = ToolUse(name, arguments, is_error=False)
                        events.put_nowait({"type": "tool_call", **asdict(event)})
                    case ToolResult(call_id, _, is_error):
                        if call_id in uses:
                            uses[call_id] = replace(uses[call_id], is_error=is_error)
                        events.put_nowait({"type": "tool_result", **asdict(event)})
                    case ChatDone(session_id):
                        content = "".join(answer)
                        saved = await self._database.run(
                            lambda conn: conversations.record_answer(
                                conn, turn, content, list(uses.values()), citation_links(content), session_id
                            )
                        )
                        events.put_nowait({"type": "done", "message": asdict(saved)})
                        return False
                    case ChatFailed(failure, session_lost):
                        if session_lost and request.resume_session_id is not None:
                            return True
                        events.put_nowait({"type": "error", "message": failure})
                        return False
        events.put_nowait({"type": "error", "message": "The answer stopped before it finished"})
        return False
