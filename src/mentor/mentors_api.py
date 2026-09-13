import asyncio
from typing import Annotated

from fastapi import APIRouter, status
from pydantic import BaseModel, StringConstraints

from mentor import mentors
from mentor.db import Database
from mentor.mentors import Channel, Mentor
from mentor.ports import ChannelInfo, TranscriptSource

type Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ChannelRef(BaseModel):
    channel: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChannelProposal(BaseModel):
    youtube_channel_id: str
    name: str


class NewMentor(BaseModel):
    name: Name
    channel: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MentorRename(BaseModel):
    name: Name


class ChannelUpdate(BaseModel):
    indexed: bool


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
    async def update_channel(channel_id: int, body: ChannelUpdate) -> Mentor:
        return await database.run(lambda conn: mentors.set_channel_indexed(conn, channel_id, body.indexed))

    @router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def detach_channel(channel_id: int) -> None:
        await database.run(lambda conn: mentors.detach_channel(conn, channel_id))

    return router
