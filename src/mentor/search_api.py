from typing import Annotated, Self

from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictInt, StringConstraints, model_validator

from mentor.mentors_api import Name
from mentor.search import CANDIDATES, PreferRecent, Search, SearchResult


class SearchBody(BaseModel):
    """At most one scope: a Group or a list of Mentors. Neither searches every Mentor."""

    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    # A JSON number is a Group id and a string is a Group name, so a Group named "12" stays reachable by name.
    group: StrictInt | Name | None = None
    mentors: Annotated[list[StrictInt], Field(min_length=1)] | None = None
    # Only as many results as go to the reranker can come back.
    limit: Annotated[StrictInt, Field(ge=1, le=CANDIDATES)] = 10
    prefer_recent: PreferRecent = "gentle"

    @model_validator(mode="after")
    def one_scope(self) -> Self:
        if self.group is not None and self.mentors is not None:
            raise ValueError("Search a Mentor Group or a list of Mentors, not both")
        return self


def search_router(search: Search) -> APIRouter:
    router = APIRouter()

    @router.post("/search")
    async def run_search(body: SearchBody) -> list[SearchResult]:
        return await search.search(
            body.query, group=body.group, mentor_ids=body.mentors, limit=body.limit, prefer_recent=body.prefer_recent
        )

    return router
