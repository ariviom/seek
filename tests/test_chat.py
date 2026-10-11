import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from harness import (
    Json,
    done_message,
    new_group_conversation,
    query,
    running,
    said,
    send,
    sharpening_picks,
    start_channel_conversation,
    start_conversation,
    start_playlist_conversation,
    stored_messages,
    stream_events,
    woodworkers,
)
from mcp import Client

from seek.app import create_app
from seek.chat import citation_links
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from seek.mcp_server import GROUNDED_ADVISOR, RESOURCE_ADVISOR
from seek.ports import ChatDone, ChatEvent, ChatFailed, ChatRequest, TextDelta, ToolCall, ToolResult


async def test_a_turn_streams_text_and_tool_calls_then_saves_the_answer_and_resumes_the_session(
    client: httpx.AsyncClient, engine: FakeChatEngine, config: Config
) -> None:
    engine.script = [
        TextDelta("Let me look."),
        ToolCall("call-1", "search", {"query": "tear-out"}),
        ToolResult("call-1", "[]", is_error=False),
        TextDelta("Your Channels don't cover tear-out."),
        ChatDone("session-1"),
    ]
    conversation = await new_group_conversation(client, model="claude-sonnet-5")

    first = await send(client, conversation["id"], "How do I stop tear-out?")
    await send(client, conversation["id"], "And on figured maple?")

    events = stream_events(first)
    assert first.status_code == 200
    # Text after a tool call starts a new paragraph, since the model's separate steps don't end in whitespace.
    assert events[:4] == [
        {"type": "text", "text": "Let me look."},
        {"type": "tool_call", "call_id": "call-1", "name": "search", "arguments": {"query": "tear-out"}},
        {"type": "tool_result", "call_id": "call-1", "content": "[]", "is_error": False},
        {"type": "text", "text": "\n\nYour Channels don't cover tear-out."},
    ]
    assert done_message(first) | {"id": 0, "created_at": ""} == {
        "id": 0,
        "role": "assistant",
        "content": "Let me look.\n\nYour Channels don't cover tear-out.",
        "tool_calls": [{"name": "search", "arguments": {"query": "tear-out"}, "is_error": False}],
        "citations": [],
        "created_at": "",
        # The engine and the model it was actually given: the API id this Conversation is pinned to is
        # translated into the Claude CLI's own alias. This engine reports no usage, so none is recorded.
        "engine": "cli",
        "model": "sonnet",
        "usage": None,
    }
    assert stored_messages(config, conversation["id"])[:2] == [
        ("user", "How do I stop tear-out?"),
        ("assistant", "Let me look.\n\nYour Channels don't cover tear-out."),
    ]
    assert [(r.message, r.model, r.resume_session_id) for r in engine.requests] == [
        ("How do I stop tear-out?", "sonnet", None),
        ("And on figured maple?", "sonnet", "session-1"),
    ]
    assert query(config, "SELECT claude_session_id FROM conversations")[0][0] == "session-1"


async def test_the_question_is_saved_before_the_answer_streams(
    client: httpx.AsyncClient, engine: FakeChatEngine, config: Config
) -> None:
    conversation = await new_group_conversation(client)
    saved_when_asked: list[list[tuple[str, str]]] = []

    async def respond(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        saved_when_asked.append(stored_messages(config, conversation["id"]))
        yield ChatDone("session-1")

    engine.respond = respond

    await send(client, conversation["id"], "Which saw for dovetails?")

    assert saved_when_asked == [[("user", "Which saw for dovetails?")]]


async def test_the_model_gets_only_seek_tools_bound_to_the_conversations_group_of_channels(
    client: httpx.AsyncClient, engine: FakeChatEngine, transcripts: FakeTranscriptSource
) -> None:
    group, _, rex = await woodworkers(client, transcripts)
    [rex_result] = (await client.post("/api/search", json={"query": "sharpen", "channels": [rex["id"]]})).json()
    conversation = await start_conversation(client, group["id"])
    seen: Json = {}

    async def respond(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        async with Client(request.tools) as mcp:
            tools = {tool.name: tool for tool in (await mcp.list_tools()).tools}
            found = await mcp.call_tool("search", {"query": "sharpen the blade on a stone"})
            # Scope arguments the public MCP server takes do nothing here.
            widened = await mcp.call_tool("search", {"query": "sharpen", "channels": [rex["id"]]})
            expanded = await mcp.call_tool("expand", {"segment_id": rex_result["segment_id"]})
            video = await mcp.call_tool("get_video", {"video_id": rex_result["video_id"]})
            listed = await mcp.call_tool("list_groups", {})
            channels = await mcp.call_tool("list_channels", {})
        assert found.structured_content and widened.structured_content and listed.structured_content
        assert channels.structured_content
        seen.update(
            tools=sorted(tools),
            search_arguments=sorted(tools["search"].input_schema["properties"]),
            found=[r["channel_name"] for r in found.structured_content["result"]],
            widened=[r["channel_name"] for r in widened.structured_content["result"]],
            refused=[expanded.is_error, video.is_error],
            listed=[g["name"] for g in listed.structured_content["result"]],
            channels=[c["name"] for c in channels.structured_content["result"]],
        )
        yield ChatDone("session-1")

    engine.respond = respond

    response = await send(client, conversation["id"], "How do I sharpen?")

    assert response.status_code == 200, response.text
    assert seen == {
        "tools": ["expand", "get_video", "list_channels", "list_groups", "search"],
        "search_arguments": ["limit", "prefer_recent", "query"],
        "found": ["Paul Wright"],
        "widened": ["Paul Wright"],
        "refused": [True, True],
        "listed": ["Woodworking"],
        "channels": ["Paul Wright"],
    }
    [request] = engine.requests
    assert sorted(request.tool_names) == ["expand", "get_video", "list_channels", "list_groups", "search"]
    assert GROUNDED_ADVISOR in request.system_prompt
    assert "the Group 'Woodworking'" in request.system_prompt and "Paul Wright" in request.system_prompt


async def test_a_chat_with_one_channel_sees_only_that_channel(
    client: httpx.AsyncClient, engine: FakeChatEngine, transcripts: FakeTranscriptSource, config: Config
) -> None:
    _, wright, rex = await woodworkers(client, transcripts)
    [rex_result] = (await client.post("/api/search", json={"query": "sharpen", "channels": [rex["id"]]})).json()
    [wright_result] = (await client.post("/api/search", json={"query": "sharpen", "channels": [wright["id"]]})).json()
    conversation = await start_channel_conversation(client, wright["id"])
    seen: Json = {}

    async def respond(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        async with Client(request.tools) as mcp:
            tools = {tool.name: tool for tool in (await mcp.list_tools()).tools}
            found = await mcp.call_tool("search", {"query": "sharpen the blade on a stone"})
            own = await mcp.call_tool("expand", {"segment_id": wright_result["segment_id"]})
            expanded = await mcp.call_tool("expand", {"segment_id": rex_result["segment_id"]})
            video = await mcp.call_tool("get_video", {"video_id": rex_result["video_id"]})
            channels = await mcp.call_tool("list_channels", {})
        assert found.structured_content and own.structured_content and channels.structured_content
        seen.update(
            tools=sorted(tools),
            found=[r["channel_name"] for r in found.structured_content["result"]],
            own=own.structured_content["channel_name"],
            refused=[expanded.is_error, video.is_error],
            channels=[c["name"] for c in channels.structured_content["result"]],
        )
        yield TextDelta("Fine: https://www.youtube.com/watch?v=v-wright&t=5s, coarse: youtu.be/v-rex?t=5")
        yield ChatDone("session-1")

    engine.respond = respond

    response = await send(client, conversation["id"], "How do I sharpen?")

    assert response.status_code == 200, response.text
    assert seen == {
        "tools": ["expand", "get_video", "list_channels", "search"],
        "found": ["Paul Wright"],
        "own": "Paul Wright",
        "refused": [True, True],
        "channels": ["Paul Wright"],
    }
    # Only the Channel's own Video is a Citation.
    assert [(c["youtube_video_id"], c["channel_id"]) for c in done_message(response)["citations"]] == [
        ("v-wright", wright["id"])
    ]
    [request] = engine.requests
    assert sorted(request.tool_names) == ["expand", "get_video", "list_channels", "search"]
    assert "the Channel 'Paul Wright'" in request.system_prompt and "Group" not in request.system_prompt


async def test_a_chat_with_a_playlist_sees_only_its_videos_whoever_made_them(
    client: httpx.AsyncClient, engine: FakeChatEngine, transcripts: FakeTranscriptSource
) -> None:
    _, playlist = await sharpening_picks(client, transcripts)
    results = (await client.post("/api/search", json={"query": "sharpen with something fine"})).json()
    by_video = {r["youtube_video_id"]: r for r in results}
    conversation = await start_playlist_conversation(client, playlist["id"])
    seen: Json = {}

    async def respond(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        async with Client(request.tools) as mcp:
            tools = {tool.name: tool for tool in (await mcp.list_tools()).tools}
            found = await mcp.call_tool("search", {"query": "sharpen with something fine"})
            own = await mcp.call_tool("expand", {"segment_id": by_video["v-knives"]["segment_id"]})
            own_video = await mcp.call_tool("get_video", {"video_id": by_video["v-knives"]["video_id"]})
            expanded = await mcp.call_tool("expand", {"segment_id": by_video["v-saws"]["segment_id"]})
            video = await mcp.call_tool("get_video", {"video_id": by_video["v-saws"]["video_id"]})
            channels = await mcp.call_tool("list_channels", {})
            instructions = mcp.instructions
        assert found.structured_content and own.structured_content and own_video.structured_content
        assert channels.structured_content and instructions
        seen.update(
            tools=sorted(tools),
            search_arguments=sorted(tools["search"].input_schema["properties"]),
            search_names_the_playlist="this Conversation's Playlist" in (tools["search"].description or ""),
            instructions_name_the_playlist="the Videos in one Playlist the user trusts" in instructions,
            found={r["youtube_video_id"] for r in found.structured_content["result"]},
            own=(own.structured_content["channel_name"], own_video.structured_content["channel_name"]),
            refused=[expanded.is_error, video.is_error],
            channels=[(c["name"], c["video_count"]) for c in channels.structured_content["result"]],
        )
        yield TextDelta(
            "Knives: https://www.youtube.com/watch?v=v-knives&t=5s, chisels: youtu.be/v-chisels?t=5, "
            "saws: youtu.be/v-saws?t=5"
        )
        yield ChatDone("session-1")

    engine.respond = respond

    response = await send(client, conversation["id"], "How do I sharpen?")

    assert response.status_code == 200, response.text
    assert seen == {
        "tools": ["expand", "get_video", "list_channels", "search"],
        "search_arguments": ["limit", "prefer_recent", "query"],
        "search_names_the_playlist": True,
        "instructions_name_the_playlist": True,
        "found": {"v-knives", "v-chisels"},
        "own": ("Rex Krueger", "Rex Krueger"),
        "refused": [True, True],
        # The Playlist's creators, in the Library or not, each with their Videos in it.
        "channels": [("Rex Krueger", 1), ("Wood By Wright", 1)],
    }
    # Wood By Wright's saws are in the Library but not in the Playlist, so they are no Citation here.
    assert [(c["youtube_video_id"], c["channel_name"]) for c in done_message(response)["citations"]] == [
        ("v-knives", "Rex Krueger"),
        ("v-chisels", "Wood By Wright"),
    ]
    [request] = engine.requests
    assert sorted(request.tool_names) == ["expand", "get_video", "list_channels", "search"]
    assert GROUNDED_ADVISOR in request.system_prompt
    assert "the Playlist 'Sharpening picks' (Channels: Rex Krueger, Wood By Wright)" in request.system_prompt
    assert "Group" not in request.system_prompt


async def test_a_playlist_chat_with_other_resources_is_still_told_it_consults_a_playlist(
    client: httpx.AsyncClient, engine: FakeChatEngine, transcripts: FakeTranscriptSource
) -> None:
    _, playlist = await sharpening_picks(client, transcripts)
    response = await client.post(f"/api/playlists/{playlist['id']}/conversations", json={"web_access": True})
    seen: list[str | None] = []

    async def respond(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        async with Client(request.tools) as mcp:
            seen.append(mcp.instructions)
        yield ChatDone("session-1")

    engine.respond = respond

    await send(client, response.json()["id"], "How do I sharpen?")

    [instructions] = seen
    assert instructions is not None
    assert "the Videos in one Playlist the user trusts" in instructions and RESOURCE_ADVISOR in instructions
    [request] = engine.requests
    assert (
        "consulting the Playlist 'Sharpening picks' (Channels: Rex Krueger, Wood By Wright) and public web pages"
        in request.system_prompt
    )


async def test_links_to_the_groups_videos_are_saved_as_citations_with_their_names(
    client: httpx.AsyncClient, engine: FakeChatEngine, transcripts: FakeTranscriptSource, config: Config
) -> None:
    group, wright, _ = await woodworkers(client, transcripts)
    conversation = await start_conversation(client, group["id"])
    [wright_video] = query(config, "SELECT id FROM videos WHERE youtube_video_id = 'v-wright'")
    engine.script = [
        TextDelta("Paul Wright hones on a fine stone ([Sharpening chisels at 0:05]"),
        TextDelta("(https://www.youtube.com/watch?v=v-wright&t=5s)), and again later (youtu.be/v-wright?t=1m5s). "),
        # Neither a Video outside the Group nor one that doesn't exist is a Citation.
        TextDelta("Rex disagrees: https://www.youtube.com/watch?v=v-rex&t=3s. See https://youtube.com/watch?v=v-nope."),
        ChatDone("session-1"),
    ]

    first = await send(client, conversation["id"], "How fine a stone?")
    # A later answer can cite a Video found in an earlier turn without searching again.
    engine.script = [TextDelta("As before: https://www.youtube.com/watch?t=5&v=v-wright."), ChatDone("session-1")]
    second = await send(client, conversation["id"], "Remind me?")

    def citation(seconds: int) -> Json:
        return {
            "video_id": wright_video["id"],
            "youtube_video_id": "v-wright",
            "seconds": seconds,
            "video_title": "Sharpening chisels",
            "channel_name": "Paul Wright",
            "url": f"https://www.youtube.com/watch?v=v-wright&t={seconds}s",
            "published_on": "2025-03-01",
            "channel_id": wright["id"],
        }

    assert done_message(first)["citations"] == [citation(5), citation(65)]
    assert done_message(second)["citations"] == [citation(5)]
    stored = query(config, "SELECT citations FROM messages WHERE role = 'assistant' ORDER BY id")
    assert [json.loads(row["citations"]) for row in stored] == [[citation(5), citation(65)], [citation(5)]]


def test_citation_links_are_read_from_any_common_youtube_link_form() -> None:
    answer = """
        [Paul, 1:30](https://www.youtube.com/watch?v=abc_DEF-123&t=90s) and https://m.youtube.com/watch?v=abc_DEF-123&t=90
        youtu.be/xyz?t=1h2m3s, http://youtube.com/watch?t=7&amp;v=q1; https://www.youtube.com/watch?v=noTime.
        Not a link: youtube.com/channel/UC123, and https://www.youtube.com/watch?v=bad&t=soon
    """

    assert citation_links(answer) == [("abc_DEF-123", 90), ("xyz", 3723), ("q1", 7), ("noTime", 0)]


async def test_one_turn_runs_per_conversation_at_a_time(client: httpx.AsyncClient, engine: FakeChatEngine) -> None:
    busy = await new_group_conversation(client)
    other = await start_conversation(client, busy["scope"]["id"])
    release = asyncio.Event()

    async def respond(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        if request.message == "first":
            await release.wait()
        yield ChatDone(f"session-{request.message}")

    engine.respond = respond

    first = asyncio.create_task(send(client, busy["id"], "first"))
    async with asyncio.timeout(5):
        while not engine.requests:
            await asyncio.sleep(0.01)
    overlapping = await send(client, busy["id"], "second")
    elsewhere = await send(client, other["id"], "elsewhere")
    release.set()

    assert (overlapping.status_code, overlapping.json()) == (
        409,
        {"detail": "This Conversation is still answering; wait for it to finish"},
    )
    assert elsewhere.status_code == 200
    assert (await first).status_code == 200
    assert (await send(client, busy["id"], "third")).status_code == 200


@pytest.mark.parametrize(
    ("script", "error"),
    [
        ([TextDelta("Half an ans"), ChatFailed("Claude Code is not logged in")], "Claude Code is not logged in"),
        ([TextDelta("Half an ans")], "The answer stopped before it finished"),
    ],
)
async def test_a_failed_turn_streams_the_error_saves_no_answer_and_frees_the_conversation(
    client: httpx.AsyncClient, engine: FakeChatEngine, config: Config, script: list[ChatEvent], error: str
) -> None:
    conversation = await new_group_conversation(client)
    engine.script = script

    failed = await send(client, conversation["id"], "Which glue?")
    engine.script = [TextDelta("Hide glue."), ChatDone("session-2")]
    retried = await send(client, conversation["id"], "Which glue?")

    assert stream_events(failed) == [{"type": "text", "text": "Half an ans"}, {"type": "error", "message": error}]
    assert retried.status_code == 200
    assert stored_messages(config, conversation["id"]) == [
        ("user", "Which glue?"),
        ("user", "Which glue?"),
        ("assistant", "Hide glue."),
    ]


async def test_a_quiet_answer_keeps_its_stream_alive(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    async def respond(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        await asyncio.sleep(0.3)
        yield ChatDone("session-1")

    engine = FakeChatEngine(respond=respond)
    app = create_app(
        config,
        transcripts,
        FakeEmbedder(),
        FakeReranker(),
        engine,
        static_dir=tmp_path / "no-bundle",
        events_keepalive_seconds=0.05,
    )

    async with running(app) as client:
        conversation = await new_group_conversation(client)
        response = await send(client, conversation["id"], "Anything?")

    assert response.text.startswith(": keepalive\n\n")
    assert done_message(response)["role"] == "assistant"


async def test_invalid_conversations_and_messages_are_rejected(client: httpx.AsyncClient) -> None:
    conversation = await new_group_conversation(client)
    group_id = conversation["scope"]["id"]

    assert (await client.post("/api/groups/999/conversations", json={"model": None})).status_code == 404
    for model in ("x; rm", "--settings", ""):
        assert (await client.post(f"/api/groups/{group_id}/conversations", json={"model": model})).status_code == 422
    assert (await send(client, 999, "Hello")).status_code == 404
    assert (await send(client, conversation["id"], "   ")).status_code == 422
    # The Conversation keeps the name its Group last had.
    await client.patch(f"/api/groups/{group_id}", json={"name": "Joinery"})
    await client.delete(f"/api/groups/{group_id}")
    orphaned = await send(client, conversation["id"], "Hello")
    assert (orphaned.status_code, orphaned.json()) == (
        409,
        {"detail": "The Group 'Joinery' was deleted, so this Conversation is read-only"},
    )
