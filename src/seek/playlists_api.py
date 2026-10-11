import asyncio
from typing import Annotated

from fastapi import APIRouter, status
from pydantic import BaseModel, StrictBool, StringConstraints, field_validator

from seek import playlists
from seek.channels import CheckHours
from seek.channels_api import Name
from seek.db import Database
from seek.events import Events
from seek.playlists import Playlist
from seek.ports import PlaylistInfo, TranscriptSource

# A YouTube playlist URL, a watch or share URL carrying one, or a playlist id.
type PlaylistInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class PlaylistRef(BaseModel):
    playlist: PlaylistInput


class PlaylistProposal(BaseModel):
    youtube_playlist_id: str
    title: str
    # The videos a Sync would ingest: those YouTube lists with a creator.
    video_count: int


class NewPlaylist(BaseModel):
    playlist: PlaylistInput
    # Defaults to the playlist's title on YouTube.
    name: Name | None = None


class PlaylistUpdate(BaseModel):
    """Fields left out are unchanged."""

    name: Name | None = None
    indexed: StrictBool | None = None
    # Null turns checks off, so only a field left out is unchanged.
    check_every_hours: CheckHours | None = None

    @field_validator("check_every_hours", mode="before")
    @classmethod
    def whole_hours(cls, value: object) -> object:
        # A Literal of ints would also take 24.0.
        if value is not None and type(value) is not int:
            raise ValueError("Check every 6, 24 or 168 hours, or null for off")
        return value


def playlists_router(
    database: Database, transcripts: TranscriptSource, events: Events, min_duration_seconds: int
) -> APIRouter:
    router = APIRouter()

    async def resolve(playlist: str) -> PlaylistInfo:
        return await asyncio.to_thread(transcripts.resolve_playlist, playlist)

    @router.post("/playlists/resolve")
    async def resolve_playlist(body: PlaylistRef) -> PlaylistProposal:
        info = await resolve(body.playlist)
        return PlaylistProposal(
            youtube_playlist_id=info.playlist_id, title=info.title, video_count=info.video_count
        )

    @router.get("/playlists")
    async def list_playlists() -> list[Playlist]:
        return await database.run(playlists.list_playlists)

    @router.post("/playlists", status_code=status.HTTP_201_CREATED)
    async def create_playlist(body: NewPlaylist) -> Playlist:
        # Resolved again server-side (usually from the proposal's playlist id) rather than trusting the client.
        info = await resolve(body.playlist)
        return await database.run(lambda conn: playlists.create_playlist(conn, info, body.name))

    @router.patch("/playlists/{playlist_id}")
    async def update_playlist(playlist_id: int, body: PlaylistUpdate) -> Playlist:
        check_every_hours = body.check_every_hours if "check_every_hours" in body.model_fields_set else ...
        playlist = await database.run(
            lambda conn: playlists.update_playlist(conn, playlist_id, body.name, body.indexed, check_every_hours)
        )
        # Syncs show their Playlist's name.
        if body.name is not None:
            events.syncs()
        return playlist

    @router.delete("/playlists/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_playlist(playlist_id: int) -> None:
        remaining = await database.run(
            lambda conn: playlists.delete_playlist(conn, playlist_id, min_duration_seconds)
        )
        events.syncs()
        for listed in remaining:
            events.videos(listed)

    return router
