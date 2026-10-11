from typing import Annotated, Self

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, StrictInt, StringConstraints, model_validator

from seek import sources
from seek.db import Database
from seek.fields import Name
from seek.search import CANDIDATES, PreferRecent, Search, SearchResult
from seek.sources import DEFAULT_EXPAND_SECONDS, MAX_EXPAND_SECONDS, Expansion


# Shared with the MCP search tool, which validates its arguments with them before building a SearchBody.
type SearchQuery = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
# A JSON number is a Group id and a string is a Group name, so a Group named "12" stays reachable by name.
type GroupRef = StrictInt | Name
type ChannelIds = Annotated[list[StrictInt], Field(min_length=1)]
# An id or a name, as a Group is.
type PlaylistRef = StrictInt | Name
# Only as many results as go to the reranker can come back.
type ResultLimit = Annotated[StrictInt, Field(ge=1, le=CANDIDATES)]


class SearchBody(BaseModel):
    """At most one scope: a Group, a list of Channels, or a Playlist. None searches everything."""

    query: SearchQuery
    group: GroupRef | None = None
    channels: ChannelIds | None = None
    playlist: PlaylistRef | None = None
    limit: ResultLimit = 10
    prefer_recent: PreferRecent = "gentle"

    @model_validator(mode="after")
    def one_scope(self) -> Self:
        if sum(given is not None for given in (self.group, self.channels, self.playlist)) > 1:
            raise ValueError("Search a Group, a list of Channels, or a Playlist, not more than one")
        return self


type ExpandSeconds = Annotated[int, Query(ge=0, le=MAX_EXPAND_SECONDS)]


def search_router(search: Search, database: Database) -> APIRouter:
    router = APIRouter()

    @router.post("/search")
    async def run_search(body: SearchBody) -> list[SearchResult]:
        return await search.search(
            body.query,
            group=body.group,
            channel_ids=body.channels,
            playlist=body.playlist,
            limit=body.limit,
            prefer_recent=body.prefer_recent,
        )

    @router.get("/segments/{segment_id}/expand")
    async def expand(
        segment_id: int,
        before_seconds: ExpandSeconds = DEFAULT_EXPAND_SECONDS,
        after_seconds: ExpandSeconds = DEFAULT_EXPAND_SECONDS,
    ) -> Expansion:
        return await database.run(lambda conn: sources.expand(conn, segment_id, before_seconds, after_seconds))

    return router
