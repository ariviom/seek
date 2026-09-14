"""The MCP tools, the product's primary interface, served over Streamable HTTP at /mcp."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field, ValidationError

from mentor import groups, sources
from mentor.db import Database
from mentor.errors import NotFound
from mentor.groups import GroupSummary
from mentor.ports import ModelUnavailable
from mentor.search import CANDIDATES, PreferRecent, Search, SearchResult
from mentor.search_api import GroupRef, MentorIds, ResultLimit, SearchBody, SearchQuery
from mentor.sources import DEFAULT_EXPAND_SECONDS, MAX_EXPAND_SECONDS, Expansion, VideoInfo
from mentor.sql import ROW_LIMIT, TEXT_LIMIT, QueryRejected, QueryResult, run_query

# User story 34 and the spec's chat system prompt. Repeated in every tool description, since a client may not pass
# the instructions to its model.
GROUNDED_ADVISOR = (
    "Act as a grounded advisor: answer only from Segments these tools return, never from general knowledge. "
    "Cite every claim with its Mentor, Video title, and timestamp link. Name the Mentor behind each piece of advice. "
    "When Mentors disagree, say so and give each view. When the only support is old next to the Mentors' newest "
    "Videos, say so. When a question is not covered by the Mentors, say so and stop rather than filling the gap."
)

INSTRUCTIONS = f"""\
This server searches the Transcripts of YouTube creators the user trusts, called Mentors, organised into Mentor \
Groups. Each Mentor owns Channels, and each Video's Transcript is cut into timestamped Segments.

{GROUNDED_ADVISOR}

Start with search (after list_groups when a Group should scope it), use expand when a Segment needs more context, \
get_video for a Video's chapters and description, and sql only for counting or listing questions."""

type ExpandSeconds = Annotated[int, Field(ge=0, le=MAX_EXPAND_SECONDS)]


def _describe(text: str) -> str:
    return f"{text}\n\n{GROUNDED_ADVISOR}"


def _validation_message(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(map(str, detail['loc']))}: {detail['msg']}" if detail["loc"] else detail["msg"]
        for detail in error.errors()
    )


@contextmanager
def _tool_errors() -> Iterator[None]:
    """Turns errors written for the user into tool errors, whose text the model sees; anything else is a crash."""
    try:
        yield
    except ValidationError as e:
        raise ToolError(_validation_message(e)) from e
    except (NotFound, ModelUnavailable, QueryRejected) as e:
        raise ToolError(str(e)) from e


def create_mcp_server(database: Database, search: Search, sql_time_limit_seconds: float) -> MCPServer:
    # The SDK configures root logging at this level; INFO would log every library's chatter.
    server = MCPServer("mentor", instructions=INSTRUCTIONS, log_level="WARNING")

    @server.tool(
        name="list_groups",
        description=_describe(
            "The Mentor Groups, each with its Mentors and how many searchable Videos each has. Scope search with a "
            "Group's id or name, or with Mentor ids."
        ),
    )
    async def list_groups() -> list[GroupSummary]:
        return await database.run(groups.group_summaries)

    @server.tool(
        name="search",
        description=_describe(
            "Find the Transcript Segments that best answer a question, matched by meaning and by exact words, "
            "reranked, with newer Videos preferred on near-ties. Scope it with at most one of group (a number is a "
            "Group id, a string is a Group name) or mentors (Mentor ids); give neither to search every Mentor. "
            f"limit is 1 to {CANDIDATES} (default 10). prefer_recent is off, gentle (default), or strong. Each result "
            "has the Segment's text, Mentor, Channel, Video title and ids, publish date, chapter, and url: a link to "
            "the moment that best matched, for citing."
        ),
    )
    async def search_segments(
        query: SearchQuery,
        group: GroupRef | None = None,
        mentors: MentorIds | None = None,
        limit: ResultLimit = 10,
        prefer_recent: PreferRecent = "gentle",
    ) -> list[SearchResult]:
        with _tool_errors():
            # The arguments are already valid one by one; the body adds the rule that they give one scope.
            body = SearchBody(query=query, group=group, mentors=mentors, limit=limit, prefer_recent=prefer_recent)
            return await search.search(
                body.query, group=body.group, mentor_ids=body.mentors, limit=body.limit, prefer_recent=body.prefer_recent
            )

    @server.tool(
        name="expand",
        description=_describe(
            "The Transcript around a Segment from search, as timed lines: from before_seconds before the Segment "
            f"starts to after_seconds after it ends (each 0 to {MAX_EXPAND_SECONDS}, default "
            f"{DEFAULT_EXPAND_SECONDS}). url opens the Segment's start; to cite another line, set its t parameter to "
            "that line's start_seconds in whole seconds."
        ),
    )
    async def expand(
        segment_id: int,
        before_seconds: ExpandSeconds = DEFAULT_EXPAND_SECONDS,
        after_seconds: ExpandSeconds = DEFAULT_EXPAND_SECONDS,
    ) -> Expansion:
        with _tool_errors():
            return await database.run(lambda conn: sources.expand(conn, segment_id, before_seconds, after_seconds))

    @server.tool(
        name="get_video",
        description=_describe(
            "A Video's title, Mentor, Channel, publish date, duration, chapters (start and end in seconds), "
            "description, and url, by the video_id a search result or expand gives."
        ),
    )
    async def get_video(video_id: int) -> VideoInfo:
        with _tool_errors():
            return await database.run(lambda conn: sources.get_video(conn, video_id))

    @server.tool(
        name="sql",
        description=_describe(
            "Run one read-only SQLite SELECT over the knowledge base, for counting or listing questions search can't "
            "answer, such as how many Videos a Mentor has from a given year. Tables include mentors, channels, "
            "mentor_groups, mentor_group_members, videos (pipeline_stage 'done' means searchable), transcripts, "
            "segments, and segments_fts (FTS5 over segments.text); read sqlite_master for the full schema. Returns "
            f"at most {ROW_LIMIT} rows within {sql_time_limit_seconds:g} seconds; text over {TEXT_LIMIT} characters "
            "is cut short, blobs come back as placeholders, and rows stop early for a very large result."
        ),
    )
    async def sql(query: str) -> QueryResult:
        with _tool_errors():
            return await asyncio.to_thread(run_query, database.path, query, sql_time_limit_seconds)

    return server
