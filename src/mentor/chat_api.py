import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StringConstraints

from mentor import conversations
from mentor.chat import Chat
from mentor.conversations import Conversation, ConversationDetail, ConversationSummary
from mentor.db import Database
from mentor.events_api import SSE_HEADERS


class NewConversation(BaseModel):
    # A Claude model name or alias, e.g. claude-sonnet-5 or opus. Starting with a letter or digit keeps it from
    # reading as a CLI flag.
    model: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._\[\]-]{0,99}$")] | None = None


class NewMessage(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]


def chat_router(database: Database, chat: Chat, keepalive_seconds: float) -> APIRouter:
    router = APIRouter()

    @router.post("/groups/{group_id}/conversations", status_code=status.HTTP_201_CREATED)
    async def create_conversation(group_id: int, body: NewConversation) -> Conversation:
        return await database.run(lambda conn: conversations.create_conversation(conn, group_id, body.model))

    @router.get("/conversations")
    async def list_conversations(group_id: int | None = None) -> list[ConversationSummary]:
        return await database.run(lambda conn: conversations.list_conversations(conn, group_id))

    @router.get("/conversations/{conversation_id}")
    async def get_conversation(conversation_id: int) -> ConversationDetail:
        return await database.run(lambda conn: conversations.get_conversation(conn, conversation_id))

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
