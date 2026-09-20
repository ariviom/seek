"""The ApiEngine against the ChatEngine contract: a request in, an event stream out.

The real Anthropic SDK runs against a scripted transport, and the tools are the real in-process scoped
MCP server over a real knowledge base, so a tool description change here would show up as a drift.
"""

import asyncio
import contextlib
import json
from pathlib import Path

import anthropic
import httpx2
import pytest
from api_transport import MESSAGES_URL, Provider, ToolUse, answer
from harness import running, woodworkers

from mentor.api_chat import INVALID_KEY, NO_KEY, ApiEngine, replayed
from mentor.app import create_app
from mentor.config import Config
from mentor.credentials import Credentials
from mentor.db import Database
from mentor.engines import MAX_TURNS, NO_API_CONTEXT
from mentor.events import Events
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeSecrets, FakeTranscriptSource
from mentor.mcp_server import bound_tool_names, create_scope_server
from mentor.ports import (
    ChatDone,
    ChatEvent,
    ChatFailed,
    ChatRequest,
    PastMessage,
    TextDelta,
    ToolCall,
    ToolResult,
    UsageReported,
)
from mentor.ranking import Recency
from mentor.scope import Scope
from mentor.search import PreferRecent, Search

KEY = "sk-ant-private-key"


def stored(validity: str = "valid", generation: str = "g1", key: str = KEY) -> str:
    return json.dumps({"key": key, "generation": generation, "validity": validity})


async def knowledge_base(config: Config, transcripts: FakeTranscriptSource, tmp_path: Path) -> int:
    """A real Group of one synced Channel, whose id scopes the tool server below."""
    app = create_app(
        config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine("cli"), static_dir=tmp_path / "none"
    )
    async with running(app) as client:
        group, _wright, _rex = await woodworkers(client, transcripts)
        group_id: int = group["id"]
        return group_id


def request_for(
    config: Config, group_id: int, message: str = "How do I sharpen a chisel?", **overrides: object
) -> ChatRequest:
    database = Database(config.database_path)
    recency: dict[PreferRecent, Recency | None] = {
        "off": None,
        "gentle": Recency(180, 0.25),
        "strong": Recency(60, 0.5),
    }
    embedder, reranker = FakeEmbedder(), FakeReranker()
    # The server loads them before serving; these tools must be able to answer, not report a cold model.
    embedder.load()
    reranker.load()
    search = Search(database, embedder, reranker, config.reranker_temperature, recency)
    scope = Scope("group", group_id)
    fields: dict[str, object] = {
        "message": message,
        "system_prompt": "You answer questions about woodworking.",
        "model": "claude-sonnet-5",
        "resume_session_id": None,
        "history": [],
        "workspace": None,
        "web_access": False,
        "tools": create_scope_server(database, search, scope),
        "tool_names": bound_tool_names(scope),
    }
    return ChatRequest(**(fields | overrides))  # type: ignore[arg-type]


def engine_over(secrets: FakeSecrets) -> ApiEngine:
    return ApiEngine(Credentials(secrets, Events()))


async def collect(engine: ApiEngine, request: ChatRequest) -> list[ChatEvent]:
    events: list[ChatEvent] = []
    async with contextlib.aclosing(engine.stream(request)) as stream:
        async for event in stream:
            events.append(event)
    return events


async def test_a_turn_runs_the_tool_loop_through_the_scoped_server_and_streams_every_step(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    group_id = await knowledge_base(config, transcripts, tmp_path)
    provider = Provider(
        script=[
            answer("Let me look.", tools=[ToolUse("call-1", "search", {"query": "sharpen chisel"})],
                   stop_reason="tool_use", input_tokens=100, output_tokens=20),
            answer("Sharpen it on a fine stone.", input_tokens=300, output_tokens=40, cache_read_tokens=90),
        ]
    )
    monkeypatch.setattr(httpx2.AsyncClient, "send", provider.hook())

    events = await collect(engine_over(FakeSecrets(values={"anthropic": stored()})), request_for(config, group_id))

    # Usage lands as soon as each request reports it, before the tool work that could still fail.
    assert [type(e).__name__ for e in events] == [
        "TextDelta", "UsageReported", "ToolCall", "ToolResult", "TextDelta", "UsageReported", "ChatDone"
    ]
    assert events[0] == TextDelta("Let me look.")
    assert events[2] == ToolCall("call-1", "search", {"query": "sharpen chisel"})
    assert isinstance(events[3], ToolResult) and not events[3].is_error
    # The real Channel's Segment came back through the real scoped server, not a stub.
    assert "Sharpen the chisel on a fine stone" in events[3].content
    reported = [e.usage for e in events if isinstance(e, UsageReported)]
    assert [(u.input_tokens, u.output_tokens, u.cache_read_tokens) for u in reported] == [
        (100, 20, 0),
        (300, 40, 90),
    ]
    assert TextDelta("Sharpen it on a fine stone.") in events
    # No provider-side session, so completion carries no session id to resume.
    assert events[-1] == ChatDone(None)


async def test_the_request_carries_the_scoped_tool_listing_adaptive_thinking_and_cache_control(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    group_id = await knowledge_base(config, transcripts, tmp_path)
    provider = Provider(script=[answer("Done.")])
    monkeypatch.setattr(httpx2.AsyncClient, "send", provider.hook())

    await collect(engine_over(FakeSecrets(values={"anthropic": stored()})), request_for(config, group_id))

    [body] = provider.bodies
    tools = body["tools"]
    assert [t["name"] for t in tools] == list(bound_tool_names(Scope("group", group_id)))
    # Translated from the server's own listing: its descriptions travel with it.
    assert "grounded advisor" in tools[0]["description"]
    assert tools[-1]["cache_control"] == {"type": "ephemeral"}
    assert body["system"] == [
        {"type": "text", "text": "You answer questions about woodworking.", "cache_control": {"type": "ephemeral"}}
    ]
    assert body["thinking"] == {"type": "adaptive"}
    assert body["model"] == "claude-sonnet-5"
    assert body["stream"] is True


async def test_a_conversation_with_project_or_web_context_is_refused_before_any_provider_request(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Those tools are Claude CLI built-ins; refusing costs nothing rather than promising them."""
    group_id = await knowledge_base(config, transcripts, tmp_path)
    provider = Provider(script=[answer("Should never run.")])
    monkeypatch.setattr(httpx2.AsyncClient, "send", provider.hook())
    engine = engine_over(FakeSecrets(values={"anthropic": stored()}))

    with_project = await collect(engine, request_for(config, group_id, workspace=tmp_path))
    with_web = await collect(engine, request_for(config, group_id, web_access=True))

    assert with_project == [ChatFailed(NO_API_CONTEXT)]
    assert with_web == [ChatFailed(NO_API_CONTEXT)]
    assert provider.bodies == []


async def test_a_missing_key_fails_the_turn_without_reaching_the_provider(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    group_id = await knowledge_base(config, transcripts, tmp_path)
    provider = Provider(script=[answer("Should never run.")])
    monkeypatch.setattr(httpx2.AsyncClient, "send", provider.hook())

    events = await collect(engine_over(FakeSecrets()), request_for(config, group_id))

    assert events == [ChatFailed(NO_KEY)]
    assert provider.bodies == []


async def test_a_tool_the_conversation_does_not_have_is_refused_rather_than_executed(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sql reads every Channel, so a scoped chat must not reach it even if the model asks by name."""
    group_id = await knowledge_base(config, transcripts, tmp_path)
    provider = Provider(
        script=[
            answer(tools=[ToolUse("call-1", "sql", {"query": "SELECT 1"})], stop_reason="tool_use"),
            answer("I can't run that here."),
        ]
    )
    monkeypatch.setattr(httpx2.AsyncClient, "send", provider.hook())

    events = await collect(engine_over(FakeSecrets(values={"anthropic": stored()})), request_for(config, group_id))

    refused = next(e for e in events if isinstance(e, ToolResult))
    assert refused.is_error
    assert refused.content == "This chat has no tool named sql."


async def test_the_turn_stops_at_the_shared_turn_limit_instead_of_looping(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    group_id = await knowledge_base(config, transcripts, tmp_path)
    provider = Provider(
        script=[answer(tools=[ToolUse("call-1", "list_channels", {})], stop_reason="tool_use")]
    )
    monkeypatch.setattr(httpx2.AsyncClient, "send", provider.hook())

    events = await collect(engine_over(FakeSecrets(values={"anthropic": stored()})), request_for(config, group_id))

    assert len(provider.bodies) == MAX_TURNS
    assert events[-1] == ChatFailed(f"The answer needed more than {MAX_TURNS} steps, so Mentor stopped it.")


@pytest.mark.parametrize(
    "code,expected,marks_invalid",
    [
        (401, INVALID_KEY, True),
        (429, "The Anthropic API is rate limiting this key right now; wait a moment and ask again.", False),
        (529, "The Anthropic API is overloaded or unavailable right now; ask again in a moment.", False),
        (400, "The Anthropic API refused this request: scripted failure", False),
    ],
)
async def test_provider_failures_become_sentences_and_only_authentication_invalidates_the_key(
    config: Config,
    transcripts: FakeTranscriptSource,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    code: int,
    expected: str,
    marks_invalid: bool,
) -> None:
    caplog.set_level("DEBUG")
    group_id = await knowledge_base(config, transcripts, tmp_path)
    monkeypatch.setattr(httpx2.AsyncClient, "send", Provider(script=[code]).hook())
    secrets = FakeSecrets(values={"anthropic": stored()})

    events = await collect(engine_over(secrets), request_for(config, group_id))

    assert events == [ChatFailed(expected)]
    assert json.loads(secrets.values["anthropic"])["validity"] == ("invalid" if marks_invalid else "valid")
    assert KEY not in caplog.text


async def test_a_delayed_rejection_of_the_old_key_leaves_a_newly_stored_one_alone(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The turn was started on key A; by the time it is rejected the user has already stored key B."""
    group_id = await knowledge_base(config, transcripts, tmp_path)
    secrets = FakeSecrets(values={"anthropic": stored(generation="old", key="sk-ant-key-a")})

    async def replace_the_key(client: httpx2.AsyncClient, request: httpx2.Request, **kwargs: object) -> httpx2.Response:
        secrets.values["anthropic"] = stored(generation="new", key="sk-ant-key-b")
        return httpx2.Response(
            401, json={"type": "error", "error": {"type": "authentication_error", "message": "no"}}, request=request
        )

    monkeypatch.setattr(httpx2.AsyncClient, "send", replace_the_key)

    events = await collect(engine_over(secrets), request_for(config, group_id))

    assert events == [ChatFailed(INVALID_KEY)]
    envelope = json.loads(secrets.values["anthropic"])
    assert (envelope["generation"], envelope["key"], envelope["validity"]) == ("new", "sk-ant-key-b", "valid")


async def test_usage_already_reported_survives_a_later_request_failing(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    group_id = await knowledge_base(config, transcripts, tmp_path)
    provider = Provider(
        script=[
            answer(tools=[ToolUse("call-1", "list_channels", {})], stop_reason="tool_use",
                   input_tokens=120, output_tokens=15),
            429,
        ]
    )
    monkeypatch.setattr(httpx2.AsyncClient, "send", provider.hook())

    events = await collect(engine_over(FakeSecrets(values={"anthropic": stored()})), request_for(config, group_id))

    reported = [e.usage for e in events if isinstance(e, UsageReported)]
    assert [(u.input_tokens, u.output_tokens) for u in reported] == [(120, 15)]
    assert isinstance(events[-1], ChatFailed)


async def test_stopping_the_turn_closes_the_sdk_client_without_making_another_request(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing the stream mid-answer has to unwind the turn, not leave its connection open until a
    collection: `Chat` closes the generator on every stop and on shutdown."""
    group_id = await knowledge_base(config, transcripts, tmp_path)
    provider = Provider(
        script=[
            answer("Thinking", tools=[ToolUse("call-1", "list_channels", {})], stop_reason="tool_use"),
            answer("Second step."),
        ]
    )
    monkeypatch.setattr(httpx2.AsyncClient, "send", provider.hook())
    closed: list[bool] = []
    released = anthropic.AsyncAnthropic.close

    async def record(client: anthropic.AsyncAnthropic) -> None:
        closed.append(True)
        await released(client)

    monkeypatch.setattr(anthropic.AsyncAnthropic, "close", record)
    engine = engine_over(FakeSecrets(values={"anthropic": stored()}))

    stream = engine.stream(request_for(config, group_id))
    first = await anext(stream)
    assert closed == []
    await stream.aclose()

    assert first == TextDelta("Thinking")
    assert len(provider.bodies) == 1
    assert closed == [True]


async def test_the_key_is_sent_per_request_and_never_taken_from_the_environment(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    group_id = await knowledge_base(config, transcripts, tmp_path)
    provider = Provider(script=[answer("Done.")])
    monkeypatch.setattr(httpx2.AsyncClient, "send", provider.hook())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "environment-must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "environment-token-must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://wrong.example")
    monkeypatch.setenv(
        "ANTHROPIC_CUSTOM_HEADERS", "x-api-key: environment-key\nAuthorization: Bearer environment-token"
    )

    await collect(engine_over(FakeSecrets(values={"anthropic": stored()})), request_for(config, group_id))

    [sent] = provider.requests
    assert str(sent.url) == MESSAGES_URL
    assert sent.headers["x-api-key"] == KEY
    assert "authorization" not in sent.headers


async def test_history_is_replayed_bounded_and_always_starts_with_a_question() -> None:
    """The provider rejects a first message that isn't a question, which truncation could otherwise cause."""
    short = replayed([PastMessage("user", "Earlier?"), PastMessage("assistant", "Earlier answer.")], "Now?")
    long_history = [PastMessage("user", "a" * 60_000), PastMessage("assistant", "b" * 60_000)]
    truncated = replayed(long_history, "Now?")

    assert short == [
        {"role": "user", "content": "Earlier?"},
        {"role": "assistant", "content": "Earlier answer."},
        {"role": "user", "content": "Now?"},
    ]
    assert [m["role"] for m in truncated] == ["user", "assistant", "user"]
    assert truncated[0]["content"] == "(Earlier messages in this Conversation were left out.)"
    assert truncated[-1] == {"role": "user", "content": "Now?"}


async def test_an_unanswered_question_is_replayed_where_it_happened(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    group_id = await knowledge_base(config, transcripts, tmp_path)
    provider = Provider(script=[answer("Now I can answer.")])
    monkeypatch.setattr(httpx2.AsyncClient, "send", provider.hook())
    history = [PastMessage("user", "First?"), PastMessage("user", "Second, unanswered?")]

    await collect(
        engine_over(FakeSecrets(values={"anthropic": stored()})),
        request_for(config, group_id, message="Third?", history=history),
    )

    [body] = provider.bodies
    assert body["messages"] == [
        {"role": "user", "content": "First?"},
        {"role": "user", "content": "Second, unanswered?"},
        {"role": "user", "content": "Third?"},
    ]


async def test_the_next_request_carries_the_assistant_blocks_and_the_tool_result(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A multi-step thinking/tool continuation is only valid if the earlier blocks go back unchanged."""
    group_id = await knowledge_base(config, transcripts, tmp_path)
    provider = Provider(
        script=[
            answer("Looking.", tools=[ToolUse("call-1", "list_channels", {})], stop_reason="tool_use"),
            answer("Paul Wright."),
        ]
    )
    monkeypatch.setattr(httpx2.AsyncClient, "send", provider.hook())

    await collect(engine_over(FakeSecrets(values={"anthropic": stored()})), request_for(config, group_id))

    continuation = provider.bodies[1]["messages"]
    assert continuation[-2]["role"] == "assistant"
    assert [b["type"] for b in continuation[-2]["content"]] == ["text", "tool_use"]
    [result] = continuation[-1]["content"]
    assert (result["type"], result["tool_use_id"], result["is_error"]) == ("tool_result", "call-1", False)
    assert "Paul Wright" in result["content"]
