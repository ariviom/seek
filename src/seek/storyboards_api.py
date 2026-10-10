"""The one place a signed storyboard URL is served.

Deliberately not a field on a search result or a Citation: those go to models through the MCP tools, where a URL
that expires in hours would be noise at best, and the search payload stays what it was.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, StrictInt, ValidationError

from seek.db import Database
from seek.storyboards import MAX_FRAMES, Moment, VideoFrames, read_frames

# Enough for a page of search results or an answer's whole Sources column, asked for in one request.
MAX_MOMENTS = 60


class MomentBody(BaseModel):
    """The frames one strip wants: `count` from `seconds` on, at the Video's own storyboard interval."""

    video_id: StrictInt
    # allow_inf_nan=False: infinity passes `ge=0` and then has no tile.
    seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    count: Annotated[StrictInt, Field(ge=1, le=MAX_FRAMES)]


class FramesBody(BaseModel):
    moments: Annotated[list[MomentBody], Field(min_length=1, max_length=MAX_MOMENTS)]


def storyboards_router(database: Database) -> APIRouter:
    router = APIRouter()

    @router.post("/frames")
    async def frames(request: Request) -> list[VideoFrames]:
        """The frames each moment has, from geometry already stored. Never calls YouTube: a Video whose geometry
        was never fetched is simply absent, and `seek backfill-storyboards` is what fetches it.

        Validated here rather than by a body parameter, so a refusal says what the shape is instead of echoing
        what was sent -- which for an infinite number isn't JSON a response can carry.
        """
        try:
            body = FramesBody.model_validate_json(await request.body())
        except ValidationError:
            raise HTTPException(
                422,
                f"Ask for 1 to {MAX_MOMENTS} moments, each with a video_id, seconds (0 or more, finite) and count "
                f"(1 to {MAX_FRAMES}).",
            ) from None
        moments = [Moment(m.video_id, m.seconds, m.count) for m in body.moments]
        return await database.run(lambda conn: read_frames(conn, moments))

    return router
