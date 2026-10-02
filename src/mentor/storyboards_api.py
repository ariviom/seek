"""The one place a signed storyboard URL is served.

Deliberately not a field on a search result or a Citation: those go to models through the MCP tools, where a URL
that expires in hours would be noise at best, and the search payload stays what it was.
"""

from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictInt

from mentor.db import Database
from mentor.storyboards import MAX_FRAMES, Moment, VideoFrames, read_frames

# Enough for a page of search results or an answer's whole Sources column, asked for in one request.
MAX_MOMENTS = 60


class MomentBody(BaseModel):
    """The frames one strip wants: `count` from `seconds` on, at the Video's own storyboard interval."""

    video_id: StrictInt
    seconds: Annotated[float, Field(ge=0)]
    count: Annotated[StrictInt, Field(ge=1, le=MAX_FRAMES)]


class FramesBody(BaseModel):
    moments: Annotated[list[MomentBody], Field(min_length=1, max_length=MAX_MOMENTS)]


def storyboards_router(database: Database) -> APIRouter:
    router = APIRouter()

    @router.post("/frames")
    async def frames(body: FramesBody) -> list[VideoFrames]:
        """The frames each moment has, from geometry already stored. Never calls YouTube: a Video whose geometry
        was never fetched is simply absent, and `mentor backfill-storyboards` is what fetches it."""
        moments = [Moment(m.video_id, m.seconds, m.count) for m in body.moments]
        return await database.run(lambda conn: read_frames(conn, moments))

    return router
