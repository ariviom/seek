import asyncio
from datetime import date
from typing import Annotated, Self

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, StrictBool, StrictInt, StringConstraints, model_validator

from mentor import mentors
from mentor.db import Database
from mentor.mentors import Channel, ChannelFilters, Mentor
from mentor.ports import ChannelInfo, TranscriptSource

type Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# A YouTube channel URL, @handle, or channel id.
type ChannelInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ChannelRef(BaseModel):
    channel: ChannelInput


class ChannelProposal(BaseModel):
    youtube_channel_id: str
    name: str


class NewMentor(BaseModel):
    name: Name
    channel: ChannelInput


class MentorRename(BaseModel):
    name: Name


class FiltersBody(BaseModel):
    published_after: date | None
    published_before: date | None
    playlist_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")] | None
    most_recent: Annotated[StrictInt, Field(ge=1, le=100_000)] | None

    @model_validator(mode="after")
    def dates_in_order(self) -> Self:
        if self.published_after and self.published_before and self.published_after > self.published_before:
            raise ValueError("published_after must not be later than published_before")
        return self


class ChannelUpdate(BaseModel):
    """Fields left out are unchanged."""

    indexed: StrictBool | None = None
    filters: FiltersBody | None = None


def mentors_router(database: Database, transcripts: TranscriptSource) -> APIRouter:
    router = APIRouter()

    async def resolve(channel: str) -> ChannelInfo:
        return await asyncio.to_thread(transcripts.resolve_channel, channel)

    @router.post("/channels/resolve")
    async def resolve_channel(body: ChannelRef) -> ChannelProposal:
        info = await resolve(body.channel)
        return ChannelProposal(youtube_channel_id=info.channel_id, name=info.name)

    @router.get("/mentors")
    async def list_mentors() -> list[Mentor]:
        return await database.run(mentors.list_mentors)

    @router.post("/mentors", status_code=status.HTTP_201_CREATED)
    async def create_mentor(body: NewMentor) -> Mentor:
        # Resolved again server-side (usually from the proposal's channel id) rather than trusting the client.
        info = await resolve(body.channel)
        return await database.run(lambda conn: mentors.create_mentor(conn, body.name, info))

    @router.patch("/mentors/{mentor_id}")
    async def rename_mentor(mentor_id: int, body: MentorRename) -> Mentor:
        return await database.run(lambda conn: mentors.rename_mentor(conn, mentor_id, body.name))

    @router.delete("/mentors/{mentor_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_mentor(mentor_id: int) -> None:
        await database.run(lambda conn: mentors.delete_mentor(conn, mentor_id))

    @router.post("/mentors/{mentor_id}/channels", status_code=status.HTTP_201_CREATED)
    async def attach_channel(mentor_id: int, body: ChannelRef) -> Channel:
        info = await resolve(body.channel)
        return await database.run(lambda conn: mentors.attach_channel(conn, mentor_id, info))

    @router.patch("/channels/{channel_id}")
    async def update_channel(channel_id: int, body: ChannelUpdate) -> Channel:
        filters = None if body.filters is None else ChannelFilters(**body.filters.model_dump())
        return await database.run(lambda conn: mentors.update_channel(conn, channel_id, body.indexed, filters))

    @router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def detach_channel(channel_id: int) -> None:
        await database.run(lambda conn: mentors.detach_channel(conn, channel_id))

    return router
