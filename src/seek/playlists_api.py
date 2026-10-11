import asyncio
from typing import Annotated

from fastapi import APIRouter, status
from pydantic import BaseModel, StringConstraints

from seek import playlists
from seek.channels_api import Name
from seek.db import Database
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


def playlists_router(database: Database, transcripts: TranscriptSource) -> APIRouter:
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

    return router
