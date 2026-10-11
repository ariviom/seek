import asyncio
from datetime import date
from typing import Annotated, Self
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, StrictBool, StrictInt, StringConstraints, field_validator, model_validator

from seek import channels, videos
from seek.channels import Channel, ChannelFilters
from seek.db import Database
from seek.events import Events
from seek.fields import CheckEvery, Name
from seek.ports import ChannelInfo, TranscriptSource

# A YouTube channel URL, @handle, or channel id.
type ChannelInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ChannelRef(BaseModel):
    channel: ChannelInput


class ChannelProposal(BaseModel):
    youtube_channel_id: str
    name: str


class NewChannel(BaseModel):
    channel: ChannelInput
    # Defaults to the channel's display name on YouTube.
    name: Name | None = None


class FiltersBody(BaseModel):
    published_after: date | None
    published_before: date | None
    playlist_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")] | None
    most_recent: Annotated[StrictInt, Field(ge=1, le=100_000)] | None

    @field_validator("playlist_id", mode="before")
    @classmethod
    def playlist_from_url(cls, value: object) -> object:
        """A playlist URL, as copied from the address bar, gives its list parameter."""
        if isinstance(value, str) and "list=" in value:
            listed = parse_qs(urlsplit(value.strip()).query).get("list")
            if listed:
                return listed[0]
        return value

    @model_validator(mode="after")
    def dates_in_order(self) -> Self:
        if self.published_after and self.published_before and self.published_after > self.published_before:
            raise ValueError("The earliest publish date must not be later than the latest")
        return self


class ChannelUpdate(BaseModel):
    """Fields left out are unchanged."""

    name: Name | None = None
    indexed: StrictBool | None = None
    filters: FiltersBody | None = None
    # Null turns checks off, so only a field left out is unchanged.
    check_every_hours: CheckEvery = None


def channels_router(
    database: Database, transcripts: TranscriptSource, events: Events, min_duration_seconds: int
) -> APIRouter:
    router = APIRouter()

    async def resolve(channel: str) -> ChannelInfo:
        return await asyncio.to_thread(transcripts.resolve_channel, channel)

    @router.post("/channels/resolve")
    async def resolve_channel(body: ChannelRef) -> ChannelProposal:
        info = await resolve(body.channel)
        return ChannelProposal(youtube_channel_id=info.channel_id, name=info.name)

    @router.get("/channels")
    async def list_channels() -> list[Channel]:
        return await database.run(channels.list_channels)

    @router.post("/channels", status_code=status.HTTP_201_CREATED)
    async def create_channel(body: NewChannel) -> Channel:
        # Resolved again server-side (usually from the proposal's channel id) rather than trusting the client.
        info = await resolve(body.channel)
        return await database.run(lambda conn: channels.create_channel(conn, info, body.name))

    @router.patch("/channels/{channel_id}")
    async def update_channel(channel_id: int, body: ChannelUpdate) -> Channel:
        filters = None if body.filters is None else ChannelFilters(**body.filters.model_dump())
        check_every_hours = body.check_every_hours if "check_every_hours" in body.model_fields_set else ...
        channel = await database.run(
            lambda conn: channels.update_channel(conn, channel_id, body.name, body.indexed, filters, check_every_hours)
        )
        # Syncs show their Channel's name.
        if body.name is not None:
            events.syncs()
        return channel

    @router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_channel(channel_id: int) -> None:
        remaining = await database.run(lambda conn: videos.delete_channel(conn, channel_id, min_duration_seconds))
        events.syncs()
        for listed in remaining:
            events.videos(listed)

    return router
