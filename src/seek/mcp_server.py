"""The MCP tools, the product's primary interface: served over Streamable HTTP at /mcp, and in-process to the web
chat bound to one Group or Channel."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field, ValidationError

from seek import groups, sources
from seek.db import Database
from seek.errors import NotFound
from seek.groups import ChannelSummary, GroupSummary
from seek.ports import ModelUnavailable
from seek.scope import SCOPE_NOUN, Scope, ScopeKind
from seek.search import CANDIDATES, PreferRecent, Search, SearchResult
from seek.search_api import ChannelIds, GroupRef, ResultLimit, SearchBody, SearchQuery
from seek.sources import DEFAULT_EXPAND_SECONDS, MAX_EXPAND_SECONDS, Expansion, VideoInfo
from seek.sql import ROW_LIMIT, TEXT_LIMIT, QueryRejected, QueryResult, run_query

# User story 34 and the spec's chat system prompt. Repeated in every tool description, since a client may not pass
# the instructions to its model.
GROUNDED_ADVISOR = (
    "Act as a grounded advisor: answer only from Segments these tools return, never from general knowledge. "
    "Cite every claim with its Channel, Video title, and timestamp link. Name the Channel behind each piece of "
    "advice. When Channels disagree, say so and give each view. When the only support is old next to the Channels' "
    "newest Videos, say so. When a question is not covered by the Channels, say so and stop rather than filling the "
    "gap."
)

# The public MCP server and resource-enabled web chats may sit beside files and web tools. Its contract is to keep
# claims learned from Seek attributable without pretending those are the agent's only possible observations.
RESOURCE_ADVISOR = (
    "Answer only from Segments when stating what these Channels teach; never attribute general knowledge or another "
    "resource to them. Cite every Channel-derived claim with its Channel, Video title, and timestamp link. "
    "Name the Channel behind each piece of advice. When Channels disagree, say so and give each view. When the only "
    "support is old next to the Channels' newest Videos, say so. When a question is not covered by the Channels, say "
    "so clearly. You may use other resources the client provides, but identify observations from them separately."
)

INSTRUCTIONS = f"""\
This server searches the Transcripts of YouTube Channels the user trusts, which can be organised into Groups. Each \
Video's Transcript is cut into timestamped Segments.

{RESOURCE_ADVISOR}

Start with search (after list_groups or list_channels when one should scope it), use expand when a Segment needs \
more context, get_video for a Video's chapters and description, and sql only for counting or listing questions."""

_SCOPE_INSTRUCTIONS = """\
This server searches the Transcripts of {{consulted}} the user trusts. Each Video's Transcript is cut into \
timestamped Segments.

{advisor}

Start with search, use expand when a Segment needs more context, and get_video for a Video's chapters and \
description."""

GROUP_INSTRUCTIONS = _SCOPE_INSTRUCTIONS.format(
    consulted="one Group of YouTube Channels", advisor=GROUNDED_ADVISOR
)
CHANNEL_INSTRUCTIONS = _SCOPE_INSTRUCTIONS.format(consulted="one YouTube Channel", advisor=GROUNDED_ADVISOR)

# sql reads every Channel's data, so a chat bound to a scope goes without it; list_groups only means something for
# a Group.
GROUP_TOOL_NAMES = ("list_groups", "list_channels", "search", "expand", "get_video")
CHANNEL_TOOL_NAMES = ("list_channels", "search", "expand", "get_video")
_BOUND: dict[ScopeKind, tuple[str, tuple[str, ...]]] = {
    "group": (GROUP_INSTRUCTIONS, GROUP_TOOL_NAMES),
    "channel": (CHANNEL_INSTRUCTIONS, CHANNEL_TOOL_NAMES),
}

_SEARCH_RESULTS = (
    f"limit is 1 to {CANDIDATES} (default 10). prefer_recent is off, gentle (default), or strong. Each result has the "
    "Segment's text, Channel, Video title and ids, publish date, chapter, and url: a link to the moment that "
    "best matched, for citing."
)

type ExpandSeconds = Annotated[int, Field(ge=0, le=MAX_EXPAND_SECONDS)]


def _describe(text: str, advisor: str) -> str:
    return f"{text}\n\n{advisor}"


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


def bound_tool_names(scope: Scope) -> tuple[str, ...]:
    return _BOUND[scope.kind][1]


def create_mcp_server(database: Database, search: Search, sql_time_limit_seconds: float) -> MCPServer:
    """Every tool, over every Channel."""
    return _server(database, search, None, sql_time_limit_seconds, RESOURCE_ADVISOR)


def create_scope_server(
    database: Database, search: Search, scope: Scope, *, additional_resources: bool = False
) -> MCPServer:
    """The tools a chat with one Group or Channel may use: search covers only the scope, Segments and Videos outside
    it aren't found, and there is no sql."""
    advisor = RESOURCE_ADVISOR if additional_resources else GROUNDED_ADVISOR
    return _server(database, search, scope, None, advisor)


# Given a scope, sql_time_limit_seconds is None: sql would read every Channel.
def _server(
    database: Database,
    search: Search,
    scope: Scope | None,
    sql_time_limit_seconds: float | None,
    advisor: str,
) -> MCPServer:
    if scope is None:
        instructions = INSTRUCTIONS
    elif advisor == GROUNDED_ADVISOR:
        instructions = _BOUND[scope.kind][0]
    else:
        consulted = "one Group of YouTube Channels" if scope.kind == "group" else "one YouTube Channel"
        instructions = _SCOPE_INSTRUCTIONS.format(consulted=consulted, advisor=advisor)
    # The SDK configures root logging at this level; INFO would log every library's chatter.
    server = MCPServer("seek", instructions=instructions, log_level="WARNING")

    if scope is None or scope.kind == "group":
        group_id = None if scope is None else scope.id

        @server.tool(
            name="list_groups",
            description=_describe(
                (
                    "The Groups, each with its Channels and how many searchable Videos each has. Scope search with a "
                    "Group's id or name, or with Channel ids."
                    if scope is None
                    else "The Group this Conversation consults, with its Channels and how many searchable Videos "
                    "each has."
                ),
                advisor,
            ),
        )
        async def list_groups() -> list[GroupSummary]:
            return await database.run(lambda conn: groups.group_summaries(conn, group_id))

    @server.tool(
        name="list_channels",
        description=_describe(
            (
                "Every indexed Channel, with how many searchable Videos each has. Scope search with Channel ids."
                if scope is None
                else "The Channels this Conversation consults, with how many searchable Videos each has."
            ),
            advisor,
        ),
    )
    async def list_channels() -> list[ChannelSummary]:
        return await database.run(lambda conn: groups.channel_summaries(conn, scope))

    if scope is None:

        @server.tool(
            name="search",
            description=_describe(
                "Find the Transcript Segments that best answer a question, matched by meaning and by exact words, "
                "reranked, with newer Videos preferred on near-ties. Scope it with at most one of group (a number is "
                "a Group id, a string is a Group name) or channels (Channel ids); give neither to search every "
                "Channel. " + _SEARCH_RESULTS,
                advisor,
            ),
        )
        async def search_segments(
            query: SearchQuery,
            group: GroupRef | None = None,
            channels: ChannelIds | None = None,
            limit: ResultLimit = 10,
            prefer_recent: PreferRecent = "gentle",
        ) -> list[SearchResult]:
            with _tool_errors():
                # The arguments are already valid one by one; the body adds the rule that they give one scope.
                body = SearchBody(query=query, group=group, channels=channels, limit=limit, prefer_recent=prefer_recent)
                return await search.search(
                    body.query,
                    group=body.group,
                    channel_ids=body.channels,
                    limit=body.limit,
                    prefer_recent=body.prefer_recent,
                )

    else:
        # A name of its own, so the closure below sees it as a Scope rather than Scope | None.
        bound = scope

        @server.tool(
            name="search",
            description=_describe(
                f"Find the Transcript Segments of this Conversation's {SCOPE_NOUN[bound.kind]} that best answer a "
                "question, matched by meaning and by exact words, reranked, with newer Videos preferred on "
                "near-ties. " + _SEARCH_RESULTS,
                advisor,
            ),
        )
        async def search_scope(
            query: SearchQuery, limit: ResultLimit = 10, prefer_recent: PreferRecent = "gentle"
        ) -> list[SearchResult]:
            with _tool_errors():
                return await search.search(query, scope=bound, limit=limit, prefer_recent=prefer_recent)

    @server.tool(
        name="expand",
        description=_describe(
            "The Transcript around a Segment from search, as timed lines: from before_seconds before the Segment "
            f"starts to after_seconds after it ends (each 0 to {MAX_EXPAND_SECONDS}, default "
            f"{DEFAULT_EXPAND_SECONDS}). url opens the Segment's start; to cite another line, set its t parameter to "
            "that line's start_seconds in whole seconds.",
            advisor,
        ),
    )
    async def expand(
        segment_id: int,
        before_seconds: ExpandSeconds = DEFAULT_EXPAND_SECONDS,
        after_seconds: ExpandSeconds = DEFAULT_EXPAND_SECONDS,
    ) -> Expansion:
        with _tool_errors():
            return await database.run(
                lambda conn: sources.expand(conn, segment_id, before_seconds, after_seconds, scope)
            )

    @server.tool(
        name="get_video",
        description=_describe(
            "A Video's title, Channel, publish date, duration, chapters (start and end in seconds), description, and "
            "url, by the video_id a search result or expand gives.",
            advisor,
        ),
    )
    async def get_video(video_id: int) -> VideoInfo:
        with _tool_errors():
            return await database.run(lambda conn: sources.get_video(conn, video_id, scope))

    if sql_time_limit_seconds is not None:
        time_limit = sql_time_limit_seconds

        @server.tool(
            name="sql",
            description=_describe(
                "Run one read-only SQLite SELECT over the knowledge base, for counting or listing questions search "
                "can't answer, such as how many Videos a Channel has from a given year. Tables include channels, "
                "groups, group_channels, videos (pipeline_stage 'done' means searchable), transcripts, segments, and "
                "segments_fts (FTS5 over segments.context and segments.text); read sqlite_master for the full "
                f"schema. Returns at most {ROW_LIMIT} rows within {time_limit:g} seconds; text over "
                f"{TEXT_LIMIT} characters is cut short, blobs come back as placeholders, and rows stop early for a "
                "very large result.",
                advisor,
            ),
        )
        async def sql(query: str) -> QueryResult:
            with _tool_errors():
                return await asyncio.to_thread(run_query, database.path, query, time_limit)

    return server
