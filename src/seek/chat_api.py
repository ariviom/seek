import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StringConstraints

from seek import conversations
from seek.chat import Chat
from seek.conversations import Conversation, ConversationContext, ConversationDetail, ConversationSummary
from seek.db import Database
from seek.errors import Conflict
from seek.events_api import SSE_HEADERS
from seek.scope import Scope


class NewConversation(BaseModel):
    # A Claude model name or alias, e.g. claude-sonnet-5 or opus. Starting with a letter or digit keeps it from
    # reading as a CLI flag.
    model: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._\[\]-]{0,99}$")] | None = None
    workspace: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)] | None = None
    web_access: bool = False


def _context(body: NewConversation) -> ConversationContext:
    if body.workspace is None:
        return ConversationContext(workspace=None, web_access=body.web_access)
    given = Path(body.workspace).expanduser()
    if not given.is_absolute():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The project directory must be an absolute path")
    try:
        workspace = given.resolve(strict=True)
    except (OSError, RuntimeError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"The project directory cannot be opened: {e}") from e
    if not workspace.is_dir():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The project directory must name a directory")
    return ConversationContext(workspace=str(workspace), web_access=body.web_access)


class NewMessage(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]


class ConversationRename(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def chat_router(database: Database, chat: Chat, keepalive_seconds: float) -> APIRouter:
    router = APIRouter()

    @router.post("/groups/{group_id}/conversations", status_code=status.HTTP_201_CREATED)
    async def create_group_conversation(group_id: int, body: NewConversation) -> Conversation:
        scope = Scope("group", group_id)
        context = _context(body)
        return await database.run(lambda conn: conversations.create_conversation(conn, scope, body.model, context))

    @router.post("/channels/{channel_id}/conversations", status_code=status.HTTP_201_CREATED)
    async def create_channel_conversation(channel_id: int, body: NewConversation) -> Conversation:
        scope = Scope("channel", channel_id)
        context = _context(body)
        return await database.run(lambda conn: conversations.create_conversation(conn, scope, body.model, context))

    @router.get("/conversations")
    async def list_conversations(
        group_id: int | None = None, channel_id: int | None = None
    ) -> list[ConversationSummary]:
        """Every Conversation, or a Group's, or a Channel's."""
        if group_id is not None and channel_id is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Filter by group_id or channel_id, not both")
        return await database.run(lambda conn: conversations.list_conversations(conn, group_id, channel_id))

    @router.get("/conversations/{conversation_id}")
    async def get_conversation(conversation_id: int) -> ConversationDetail:
        return await database.run(lambda conn: conversations.get_conversation(conn, conversation_id))

    @router.patch("/conversations/{conversation_id}")
    async def rename_conversation(conversation_id: int, body: ConversationRename) -> ConversationSummary:
        return await database.run(lambda conn: conversations.rename_conversation(conn, conversation_id, body.title))

    @router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_conversation(conversation_id: int) -> None:
        if chat.answering(conversation_id):
            raise Conflict("This Conversation is still answering; stop it first")
        await database.run(lambda conn: conversations.delete_conversation(conn, conversation_id))

    @router.delete("/conversations/{conversation_id}/turn", status_code=status.HTTP_204_NO_CONTENT)
    async def stop_turn(conversation_id: int) -> None:
        """Stops the answer under way; the question stays, without an answer."""
        chat.stop(conversation_id)

    @router.post("/conversations/{conversation_id}/messages")
    async def send_message(conversation_id: int, body: NewMessage) -> StreamingResponse:
        # Errors before the turn starts (no such Conversation, one already answering) are plain JSON responses.
        events = await chat.send(conversation_id, body.message)

        async def stream() -> AsyncIterator[str]:
            while True:
                try:
                    event = await asyncio.wait_for(events.get(), keepalive_seconds)
                except TimeoutError:
                    # A long tool call or model step would otherwise leave the stream idle long enough for a proxy
                    # to close it.
                    yield ": keepalive\n\n"
                    continue
                if event is None:
                    return
                yield f"data: {json.dumps(jsonable_encoder(event))}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)

    return router
