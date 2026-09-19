import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from harness import (
    Json,
    add_channel,
    add_group,
    fake_channel,
    fake_video,
    list_videos,
    mcp_client,
    query,
    running,
    said,
    sync,
)
from mcp.types import CallToolResult, TextContent

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from mentor.ports import Chapter

TOOLS = {"list_groups", "list_channels", "search", "expand", "get_video", "sql"}

type Served = tuple[httpx.AsyncClient, FastAPI]


@pytest.fixture
async def served(
    config: Config, transcripts: FakeTranscriptSource, embedder: FakeEmbedder, reranker: FakeReranker, tmp_path: Path
) -> AsyncIterator[Served]:
    """A running app and its HTTP API client.

    MCP clients are opened per call instead: the client holds an anyio cancel scope, which can't span a fixture's
    setup and teardown.
    """
    app = create_app(
        config, transcripts, embedder, reranker, FakeChatEngine(), static_dir=tmp_path / "no-bundle", sql_time_limit_seconds=0.5
    )
    async with running(app) as client:
        yield client, app


async def call_tool(app: FastAPI, tool: str, arguments: Json) -> CallToolResult:
    async with mcp_client(app) as mcp:
        return await mcp.call_tool(tool, arguments)


async def call(app: FastAPI, tool: str, **arguments: object) -> Json:
    result = await call_tool(app, tool, arguments)
    assert not result.is_error, result.content
    content: Json | None = result.structured_content
    assert content is not None
    return content


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    [content] = result.content
    assert isinstance(content, TextContent)
    return content.text


async def test_mcp_clients_see_the_tools_and_grounded_advisor_guidance(served: Served) -> None:
    _, app = served

    async with mcp_client(app) as mcp:
        tools = (await mcp.list_tools()).tools
        instructions = mcp.instructions

    assert {tool.name for tool in tools} == TOOLS
    # Story 34: answer only from Segments, cite every claim, name the Channel, surface disagreements, flag old
    # sources, and admit gaps; in the instructions and again in every tool, since clients may drop either.
    guidance = ["only from", "cite", "name the channel", "disagree", "old", "not covered"]
    assert instructions is not None
    for text in [instructions, *(tool.description or "" for tool in tools)]:
        assert [phrase for phrase in guidance if phrase not in text.lower()] == []


@pytest.mark.parametrize("reranker_unavailable", [False, True])
async def test_the_search_tool_returns_what_the_search_api_returns(
    served: Served, transcripts: FakeTranscriptSource, reranker: FakeReranker, reranker_unavailable: bool
) -> None:
    client, app = served
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-wright", "Sharpening", cues=said("Sharpen the chisel on a fine stone", "Then strop it"))
    )
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-rex", "Honing", cues=said("Sharpen the knife on a coarse stone"))
    )
    wright = await add_channel(client, "@woodbywright", "Paul Wright")
    rex = await add_channel(client, "@rexkrueger")
    await sync(client, wright, rex)
    group = await add_group(client, "Joinery", wright)
    if reranker_unavailable:
        reranker.unavailable = "Reranker CPU scoring failed"

    for scope in ({}, {"group": group["id"]}, {"group": "joinery"}, {"channels": [rex["id"]]}):
        arguments: Json = {"query": "sharpen a chisel", "limit": 5, "prefer_recent": "strong", **scope}
        api = (await client.post("/api/search", json=arguments)).json()
        assert api != []
        if reranker_unavailable:
            assert all(result["score"] == 0 for result in api)
        assert await call(app, "search", **arguments) == {"result": api}


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"query": "chisel", "group": 1, "channels": [1]}, "not both"),
        ({"query": "   "}, "query"),
        ({"query": "chisel", "channels": []}, "channels"),
        ({"query": "chisel", "limit": 51}, "limit"),
        ({"query": "chisel", "prefer_recent": "always"}, "prefer_recent"),
        ({"query": "chisel", "group": "Nobody"}, "Group 'Nobody' not found"),
        # Strict like the API: nothing is coerced into a Group id, a Channel id, or a limit.
        ({"query": "chisel", "group": True}, "group"),
        ({"query": "chisel", "channels": ["1"]}, "channels"),
        ({"query": "chisel", "limit": 5.0}, "limit"),
    ],
)
async def test_invalid_searches_are_tool_errors(served: Served, arguments: Json, message: str) -> None:
    client, app = served
    await add_group(client, "Joinery")
    await add_channel(client, "@woodbywright", "Paul Wright")

    assert message in error_text(await call_tool(app, "search", arguments))
    assert (await client.post("/api/search", json=arguments)).status_code in (404, 422)


async def test_search_reports_a_model_still_loading_as_a_tool_error(served: Served, embedder: FakeEmbedder) -> None:
    client, app = served
    await add_channel(client, "@woodbywright", "Paul Wright")
    embedder.unavailable = "The model is still loading"

    assert "The model is still loading" in error_text(await call_tool(app, "search", {"query": "chisel"}))


async def test_list_groups_and_list_channels_show_channels_with_their_searchable_video_counts(
    served: Served, transcripts: FakeTranscriptSource
) -> None:
    client, app = served
    fake_channel(transcripts, "UC-wright").videos += [fake_video("v-1", "One"), fake_video("v-2", "Two")]
    fake_channel(transcripts, "UC-wright-vlog").videos.append(fake_video("v-vlog", "Vlog"))
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-rex", "Rex"))
    wright = await add_channel(client, "@woodbywright", "Paul Wright")
    vlog = await add_channel(client, "@wrightvlogs")
    rex = await add_channel(client, "@rexkrueger")
    await sync(client, wright, vlog)
    # Rex is never synced, and the vlog Channel stops being indexed.
    await client.patch(f"/api/channels/{vlog['id']}", json={"indexed": False})
    both = await add_group(client, "Woodworking", wright, vlog, rex)
    empty = await add_group(client, "Blacksmithing")

    assert await call(app, "list_groups") == {
        "result": [
            {"id": empty["id"], "name": "Blacksmithing", "video_count": 0, "channels": []},
            {
                "id": both["id"],
                "name": "Woodworking",
                "video_count": 2,
                "channels": [
                    {"id": wright["id"], "name": "Paul Wright", "video_count": 2},
                    {"id": rex["id"], "name": "Rex Krueger", "video_count": 0},
                    {"id": vlog["id"], "name": "Wright Vlogs", "video_count": 0},
                ],
            },
        ]
    }
    # Only indexed Channels are listed on their own: the others answer nothing.
    assert await call(app, "list_channels") == {
        "result": [
            {"id": wright["id"], "name": "Paul Wright", "video_count": 2},
            {"id": rex["id"], "name": "Rex Krueger", "video_count": 0},
        ]
    }


async def test_expand_returns_the_transcript_around_a_segment_in_the_api_and_over_mcp(
    served: Served, transcripts: FakeTranscriptSource, config: Config
) -> None:
    client, app = served
    # One cue every 10 s for five minutes, so the Video has several Segments.
    lines = [f"line {n}" for n in range(30)]
    lines[15] = "cut the tenon cheeks with a rip saw"
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-tenons", "Tenons", published_on=date(2024, 5, 17), cues=said(*lines, every=10))
    )
    wright = await add_channel(client, "@woodbywright", "Paul Wright")
    await sync(client, wright)
    results = (await client.post("/api/search", json={"query": "tenon cheeks rip saw"})).json()
    hit = next(r for r in results if "tenon cheeks" in r["text"])
    # No API gives a Segment's end.
    [segment] = query(config, "SELECT start_seconds, end_seconds FROM segments WHERE id = ?", (hit["segment_id"],))

    response = await client.get(
        f"/api/segments/{hit['segment_id']}/expand", params={"before_seconds": 20, "after_seconds": 15}
    )
    expanded = await call(app, "expand", segment_id=hit["segment_id"], before_seconds=20, after_seconds=15)

    assert response.status_code == 200, response.text
    assert expanded == response.json()
    start, end = segment["start_seconds"], segment["end_seconds"]
    # Every cue overlapping the Segment widened by 20 s before and 15 s after, in order, with its time.
    assert expanded["cues"] == [
        {"start_seconds": n * 10.0, "text": text}
        for n, text in enumerate(lines)
        if n * 10 + 10 > start - 20 and n * 10 < end + 15
    ]
    assert expanded | {"cues": []} == {
        "segment_id": hit["segment_id"],
        "start_seconds": start,
        "end_seconds": end,
        "video_id": hit["video_id"],
        "youtube_video_id": "v-tenons",
        "video_title": "Tenons",
        "published_on": "2024-05-17",
        "channel_id": wright["id"],
        "channel_name": "Paul Wright",
        "url": f"https://www.youtube.com/watch?v=v-tenons&t={int(start)}s",
        "cues": [],
    }


async def test_expand_defaults_to_a_minute_either_side_and_rejects_unknown_segments_and_wide_windows(
    served: Served, transcripts: FakeTranscriptSource, config: Config
) -> None:
    client, app = served
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-long", "Long", cues=said(*(f"line {n}" for n in range(100)), every=10))
    )
    await sync(client, await add_channel(client, "@woodbywright", "Paul Wright"))
    [middle] = query(config, "SELECT id, start_seconds, end_seconds FROM segments WHERE start_seconds >= 400 LIMIT 1")

    expanded = await call(app, "expand", segment_id=middle["id"])

    assert expanded["cues"][0]["start_seconds"] == middle["start_seconds"] - 60
    assert expanded["cues"][-1]["start_seconds"] < middle["end_seconds"] + 60
    assert (await client.get("/api/segments/999999/expand")).status_code == 404
    assert "Segment 999999 not found" in error_text(await call_tool(app, "expand", {"segment_id": 999999}))
    assert (await client.get(f"/api/segments/{middle['id']}/expand", params={"after_seconds": 601})).status_code == 422
    assert (await call_tool(app, "expand", {"segment_id": middle["id"], "before_seconds": -1})).is_error


async def test_get_video_returns_its_metadata_chapters_description_and_link(
    served: Served, transcripts: FakeTranscriptSource
) -> None:
    client, app = served
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video(
            "v-dovetails",
            "Hand-cut dovetails",
            duration=754,
            published_on=date(2024, 5, 17),
            chapters=[Chapter(title="Marking", start=0, end=120), Chapter(title="Sawing", start=120, end=754)],
        )
    )
    wright = await add_channel(client, "@woodbywright", "Paul Wright")
    await sync(client, wright)
    video = (await list_videos(client, wright["id"]))["Hand-cut dovetails"]

    assert await call(app, "get_video", video_id=video["id"]) == {
        "video_id": video["id"],
        "youtube_video_id": "v-dovetails",
        "title": "Hand-cut dovetails",
        "channel_id": wright["id"],
        "channel_name": "Paul Wright",
        "published_on": "2024-05-17",
        "duration_seconds": 754,
        "chapters": [{"title": "Marking", "start": 0.0, "end": 120.0}, {"title": "Sawing", "start": 120.0, "end": 754.0}],
        "description": "About Hand-cut dovetails",
        "url": "https://www.youtube.com/watch?v=v-dovetails",
    }
    assert "Video 999999 not found" in error_text(await call_tool(app, "get_video", {"video_id": 999999}))


async def test_expand_and_get_video_leave_out_not_indexed_channels(
    served: Served, transcripts: FakeTranscriptSource
) -> None:
    client, app = served
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-vlog", "Vlog", cues=said("at the cabin")))
    wright = await add_channel(client, "@woodbywright", "Paul Wright")
    await sync(client, wright)
    [hit] = (await client.post("/api/search", json={"query": "cabin"})).json()
    await client.patch(f"/api/channels/{wright['id']}", json={"indexed": False})

    assert (await client.get(f"/api/segments/{hit['segment_id']}/expand")).status_code == 404
    assert (await call_tool(app, "expand", {"segment_id": hit["segment_id"]})).is_error
    assert (await call_tool(app, "get_video", {"video_id": hit["video_id"]})).is_error


async def test_sql_answers_read_only_questions_across_the_knowledge_base_including_its_indexes(
    served: Served, transcripts: FakeTranscriptSource
) -> None:
    client, app = served
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-1", "Planes", cues=said("a jack plane flattens")),
        fake_video("v-2", "Saws", cues=said("a rip saw cuts along the grain")),
    ]
    await sync(client, await add_channel(client, "@woodbywright", "Paul Wright"))

    counted = await call(app, "sql", query="SELECT count(*) AS videos FROM videos WHERE pipeline_stage = 'done'")
    lexical = await call(app, "sql", query="SELECT count(*) FROM segments_fts WHERE segments_fts MATCH 'plane'")
    vectors = await call(app, "sql", query="SELECT segment_id, embedding FROM segment_vectors LIMIT 1")

    assert counted == {"columns": ["videos"], "rows": [[2]], "truncated": False}
    assert lexical["rows"] == [[1]]
    # Blobs such as vectors are described rather than returned.
    assert vectors["rows"][0][1] == "<blob, 256 bytes>"


async def test_sql_caps_rows_text_and_result_size(served: Served) -> None:
    _, app = served
    numbers = "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 1000)"

    many = await call(app, "sql", query=f"{numbers} SELECT i FROM n")
    long = await call(app, "sql", query="SELECT printf('%.*c', 5000, 'x')")
    large = await call(app, "sql", query=f"{numbers} SELECT printf('%.*c', 5000, 'x') FROM n")
    huge = await call_tool(app, "sql", {"query": "SELECT length(randomblob(900000000))"})

    assert (len(many["rows"]), many["rows"][-1], many["truncated"]) == (200, [200], True)
    assert long["rows"] == [["x" * 1000 + "… (4000 more characters)"]]
    # Rows stop once the result passes 50,000 characters, 1,024 of them a row here, well before the row cap.
    assert (len(large["rows"]), large["truncated"]) == (49, True)
    assert "too big" in error_text(huge)


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("DELETE FROM channels", "only read"),
        ("INSERT INTO groups (name) VALUES ('x')", "only read"),
        ("UPDATE channels SET name = 'x'", "only read"),
        ("DROP TABLE channels", "only read"),
        ("CREATE TABLE scratch (a)", "only read"),
        ("CREATE TEMP TABLE scratch (a)", "only read"),
        ("ATTACH DATABASE '{scratch}/attached.db' AS other", "only read"),
        ("PRAGMA journal_mode = DELETE", "only read"),
        ("PRAGMA query_only = OFF", "only read"),
        ("BEGIN", "only read"),
        ("VACUUM INTO '{scratch}/copy.db'", "only read"),
        ("SELECT load_extension('{scratch}/evil.so')", "load_extension"),
        ("SELECT 1; DELETE FROM channels", "one statement"),
        ("SELECT * FROM no_such_table", "no such table"),
        (
            "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT count(*) FROM n",
            "time limit",
        ),
    ],
)
async def test_sql_rejects_anything_but_one_read(
    served: Served, config: Config, tmp_path: Path, statement: str, message: str
) -> None:
    client, app = served
    await add_channel(client, "@woodbywright", "Paul Wright")
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    rejected = await call_tool(app, "sql", {"query": statement.format(scratch=scratch)})

    assert message in error_text(rejected).lower()
    assert [row["name"] for row in query(config, "SELECT name FROM channels")] == ["Paul Wright"]
    assert list(scratch.iterdir()) == []


async def test_the_mcp_endpoint_serves_tools_over_http_to_loopback_and_configured_hosts_only(
    config: Config, transcripts: FakeTranscriptSource, embedder: FakeEmbedder, reranker: FakeReranker, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-one", "One", cues=said("flatten the board")))
    app = create_app(
        replace(config, allowed_hosts=("mentor.example.com",)),
        transcripts,
        embedder,
        reranker,
        FakeChatEngine(),
        static_dir=tmp_path / "no-bundle",
    )
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    }
    search = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"query": "flatten the board"}},
    }
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}

    async with running(app) as client:

        async def post(body: Json, **extra: str) -> httpx.Response:
            return await client.post("/mcp", json=body, headers=headers | extra)

        await sync(client, await add_channel(client, "@woodbywright", "Paul Wright"))
        api = (await client.post("/api/search", json={"query": "flatten the board"})).json()
        called = await post(search)

        assert (await post(initialize, Host="127.0.0.1:7337")).status_code == 200
        assert (await post(initialize, Host="localhost:7337")).status_code == 200
        assert (await post(initialize, Host="mentor.example.com")).status_code == 200
        assert (await post(initialize, Host="mentor.example.com", Origin="https://mentor.example.com")).status_code == 200
        # DNS rebinding: a page on another site that resolves its name to this machine.
        assert (await post(initialize, Host="attacker.example:7337")).status_code == 421
        assert (await post(initialize, Origin="https://attacker.example")).status_code == 403
        assert called.status_code == 200, called.text
        assert called.json()["result"]["structuredContent"] == {"result": api}


async def test_startup_fails_rather_than_hangs_when_the_mcp_server_cannot_start(
    config: Config, transcripts: FakeTranscriptSource, embedder: FakeEmbedder, reranker: FakeReranker, tmp_path: Path
) -> None:
    app = create_app(config, transcripts, embedder, reranker, FakeChatEngine(), static_dir=tmp_path / "no-bundle")
    async with running(app):
        pass

    # The MCP session manager runs once per app, so starting the same app again fails.
    with pytest.raises(RuntimeError, match="once per instance"):
        async with asyncio.timeout(5), running(app):
            pass
