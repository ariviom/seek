"""Choosing an engine per turn, and what that choice does to history, provenance and usage.

Both engines are fakes here: the point is which one is asked and what the store looks like afterwards,
not what either adapter does with the request. That belongs to test_api_chat.py and test_claude_chat.py.
"""

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from harness import (
    Json,
    add_channel,
    add_group,
    event_stream,
    new_group_conversation,
    query,
    running,
    send,
    start_conversation,
    stream_events,
)

from seek import conversations
from seek.app import create_app
from seek.config import Config
from seek.engines import API_MODELS, CLI_MODELS
from seek.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeSecrets, FakeTranscriptSource
from seek.ports import (
    ChatDone,
    ChatEngineState,
    ChatEngineStatus,
    ChatEvent,
    ChatFailed,
    ChatRequest,
    TextDelta,
    TokenUsage,
    UsageReported,
)


async def conversation_of(client: httpx.AsyncClient, conversation_id: int) -> Json:
    response = await client.get(f"/api/conversations/{conversation_id}")
    assert response.status_code == 200, response.text
    detail: Json = response.json()
    return detail


def with_a_key(
    api_engine: FakeChatEngine, state: ChatEngineState = "ready", message: str | None = None
) -> None:
    """The API engine's view of the stored credential, which is what selection reads."""
    api_engine.engine_status = ChatEngineStatus("api", state, None, message)


async def wait_for_request(engine: FakeChatEngine) -> None:
    async with asyncio.timeout(5):
        while not engine.requests:
            await asyncio.sleep(0.01)


async def test_with_no_preference_a_stored_key_chooses_the_api_engine_and_nothing_else_chooses_the_cli(
    client: httpx.AsyncClient, engine: FakeChatEngine, api_engine: FakeChatEngine
) -> None:
    conversation = await new_group_conversation(client)

    await send(client, conversation["id"], "Before a key?")
    with_a_key(api_engine)
    await send(client, conversation["id"], "After a key?")

    assert [r.message for r in engine.requests] == ["Before a key?"]
    assert [r.message for r in api_engine.requests] == ["After a key?"]


async def test_an_explicit_preference_that_cannot_run_says_what_to_add_instead_of_switching(
    client: httpx.AsyncClient, engine: FakeChatEngine, api_engine: FakeChatEngine, config: Config
) -> None:
    """Silently billing the other engine would be a surprise; the dead end has to be a signpost."""
    conversation = await new_group_conversation(client)
    with_a_key(api_engine, "no_key", "Add an Anthropic API key")
    assert (await client.patch("/api/settings", json={"engine": "api"})).status_code == 200

    refused = await send(client, conversation["id"], "Which stone?")

    assert refused.status_code == 409
    assert "Add an Anthropic API key" in refused.json()["detail"]
    # The Claude CLI was ready and was deliberately not used, and no question was saved.
    assert engine.requests == []
    assert query(config, "SELECT count(*) FROM messages")[0][0] == 0


async def test_an_invalid_stored_key_is_reported_rather_than_bypassed_through_the_cli(
    client: httpx.AsyncClient, engine: FakeChatEngine, api_engine: FakeChatEngine
) -> None:
    conversation = await new_group_conversation(client)
    with_a_key(api_engine, "invalid_key", "The stored Anthropic API key was rejected.")

    refused = await send(client, conversation["id"], "Which stone?")

    assert refused.status_code == 409
    assert "rejected" in refused.json()["detail"]
    assert engine.requests == []


async def test_no_ready_engine_disables_chat_and_nothing_else(
    client: httpx.AsyncClient, engine: FakeChatEngine, api_engine: FakeChatEngine
) -> None:
    """A friend without a key can still see what Seek does before paying for anything."""
    channel = await add_channel(client, "@woodbywright")
    group = await add_group(client, "Woodworking", channel)
    conversation = await start_conversation(client, group["id"])
    engine.engine_status = ChatEngineStatus("cli", "missing", None, "Install Claude Code")

    refused = await send(client, conversation["id"], "Which stone?")

    assert refused.status_code == 409
    # Both engines' own instructions, so a friend with neither learns where to get a key as well.
    detail = refused.json()["detail"]
    assert "Add an Anthropic API key" in detail and "Install Claude Code" in detail
    assert (await client.get("/api/health")).json()["chat"]["active"] is None
    # Everything that does not need a model still answers.
    assert (await client.post("/api/search", json={"query": "sharpen"})).status_code == 200
    assert (await client.get("/api/channels")).status_code == 200
    assert (await client.get("/api/syncs")).status_code == 200


async def test_the_api_engine_is_given_full_model_ids_and_the_cli_its_own_aliases(
    client: httpx.AsyncClient, engine: FakeChatEngine, api_engine: FakeChatEngine
) -> None:
    """The two tables never mix: a CLI alias sent as an API model id would be a 404 from the provider."""
    conversation = await new_group_conversation(client)

    await send(client, conversation["id"], "On the CLI?")
    with_a_key(api_engine)
    await send(client, conversation["id"], "On the API?")
    assert (await client.patch("/api/settings", json={"model": "deep"})).status_code == 200
    await send(client, conversation["id"], "Deeply?")

    assert [r.model for r in engine.requests] == [CLI_MODELS["fast"]]
    assert [r.model for r in api_engine.requests] == [API_MODELS["fast"], API_MODELS["deep"]]


async def test_an_old_cli_alias_pin_is_translated_for_the_api_engine_and_an_unknown_one_is_refused(
    client: httpx.AsyncClient, api_engine: FakeChatEngine
) -> None:
    """A pin is a deliberate choice, so it is carried across rather than dropped — or it is an error."""
    group = await add_group(client, "Woodworking", await add_channel(client, "@woodbywright"))
    aliased = await start_conversation(client, group["id"], model="opus")
    unknown = await start_conversation(client, group["id"], model="gpt-4")
    with_a_key(api_engine)

    translated = await send(client, aliased["id"], "Which stone?")
    refused = await send(client, unknown["id"], "Which stone?")

    assert translated.status_code == 200
    assert [r.model for r in api_engine.requests] == [API_MODELS["deep"]]
    assert refused.status_code == 409
    assert "gpt-4" in refused.json()["detail"]


async def test_a_conversation_with_project_or_web_context_is_refused_before_the_question_is_saved(
    client: httpx.AsyncClient,
    engine: FakeChatEngine,
    api_engine: FakeChatEngine,
    config: Config,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Those tools are Claude CLI built-ins. A Conversation started on the CLI keeps working there, so the
    refusal must leave its session and its thread exactly as they were."""
    project = tmp_path_factory.mktemp("project")
    group = await add_group(client, "Woodworking", await add_channel(client, "@woodbywright"))
    conversation = await start_conversation(client, group["id"], workspace=str(project))
    await send(client, conversation["id"], "On the CLI, with my project?")
    with_a_key(api_engine)

    refused = await send(client, conversation["id"], "And now, with a key stored?")

    assert refused.status_code == 409
    assert "only the Claude CLI engine can provide" in refused.json()["detail"]
    assert api_engine.requests == []
    # Nothing was saved and the Claude session still resumes, so the CLI thread is untouched.
    assert query(config, "SELECT count(*) FROM messages")[0][0] == 2
    assert query(config, "SELECT claude_session_id FROM conversations")[0][0] == "session-1"


@pytest.mark.parametrize(
    "api_script,replayed_after_the_api_turn",
    [
        (
            [TextDelta("An API answer."), ChatDone(None)],
            [("user", "One?"), ("assistant", "Nothing to say."), ("user", "Two?"), ("assistant", "An API answer.")],
        ),
        # A failed API turn saved no answer, but its question is still part of the thread.
        (
            [ChatFailed("The Anthropic API is overloaded")],
            [("user", "One?"), ("assistant", "Nothing to say."), ("user", "Two?")],
        ),
    ],
)
async def test_a_cli_turn_after_an_api_turn_replays_everything_instead_of_resuming_a_stale_session(
    client: httpx.AsyncClient,
    engine: FakeChatEngine,
    api_engine: FakeChatEngine,
    config: Config,
    api_script: list[ChatEvent],
    replayed_after_the_api_turn: list[tuple[str, str]],
) -> None:
    """The API keeps no session, so the stored one is cleared when its question is saved, not when it answers."""
    conversation = await new_group_conversation(client)
    api_engine.script = api_script

    await send(client, conversation["id"], "One?")
    assert query(config, "SELECT claude_session_id FROM conversations")[0][0] == "session-1"
    with_a_key(api_engine)
    await send(client, conversation["id"], "Two?")
    assert query(config, "SELECT claude_session_id FROM conversations")[0][0] is None
    with_a_key(api_engine, "no_key", "Add a key")
    await send(client, conversation["id"], "Three?")

    third = engine.requests[-1]
    assert third.resume_session_id is None
    assert [(m.role, m.content) for m in third.history] == replayed_after_the_api_turn


async def test_a_cli_turn_after_a_stopped_api_turn_still_replays_the_saved_question(
    client: httpx.AsyncClient, engine: FakeChatEngine, api_engine: FakeChatEngine, config: Config
) -> None:
    conversation = await new_group_conversation(client)
    await send(client, conversation["id"], "One?")
    with_a_key(api_engine)
    never = asyncio.Event()

    async def hang(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        yield TextDelta("Half an ans")
        await never.wait()
        yield ChatDone(None)

    api_engine.respond = hang
    answering = asyncio.create_task(send(client, conversation["id"], "Two?"))
    await wait_for_request(api_engine)
    assert (await client.delete(f"/api/conversations/{conversation['id']}/turn")).status_code == 204
    await answering
    with_a_key(api_engine, "no_key", "Add a key")

    await send(client, conversation["id"], "Three?")

    third = engine.requests[-1]
    assert third.resume_session_id is None
    # The stopped turn saved no answer, but its question is history and must be replayed.
    assert [(m.role, m.content) for m in third.history] == [
        ("user", "One?"),
        ("assistant", "Nothing to say."),
        ("user", "Two?"),
    ]


async def test_usage_reported_before_a_failure_is_kept_against_the_question_that_started_the_turn(
    client: httpx.AsyncClient, api_engine: FakeChatEngine, config: Config
) -> None:
    """A turn that fails halfway still cost something; recording nothing would understate the bill."""
    conversation = await new_group_conversation(client)
    with_a_key(api_engine)
    api_engine.script = [
        UsageReported(TokenUsage(100, 20, 0)),
        UsageReported(TokenUsage(300, 40, 90)),
        ChatFailed("The Anthropic API is overloaded"),
    ]

    await send(client, conversation["id"], "Which stone?")

    detail = await conversation_of(client, conversation["id"])
    [question] = detail["messages"]
    assert question["usage"] == {
        "input_tokens": 400,
        "output_tokens": 60,
        "cache_read_tokens": 90,
        # The turn never finished, so the numbers are a floor rather than the whole turn.
        "complete": False,
    }
    assert detail["usage"] == {
        "input_tokens": 400,
        "output_tokens": 60,
        "cache_read_tokens": 90,
        "complete": False,
    }


async def test_usage_survives_stopping_a_turn_that_had_already_reported_some(
    client: httpx.AsyncClient, api_engine: FakeChatEngine
) -> None:
    conversation = await new_group_conversation(client)
    with_a_key(api_engine)
    never = asyncio.Event()

    async def hang(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        yield UsageReported(TokenUsage(120, 15, 0))
        yield TextDelta("Half an ans")
        await never.wait()
        yield ChatDone(None)

    api_engine.respond = hang
    answering = asyncio.create_task(send(client, conversation["id"], "Which stone?"))
    await wait_for_request(api_engine)
    assert (await client.delete(f"/api/conversations/{conversation['id']}/turn")).status_code == 204
    await answering

    async with asyncio.timeout(5):
        while (await conversation_of(client, conversation["id"]))["messages"][0]["usage"] is None:
            await asyncio.sleep(0.01)
    [question] = (await conversation_of(client, conversation["id"]))["messages"]
    assert question["usage"] == {
        "input_tokens": 120,
        "output_tokens": 15,
        "cache_read_tokens": 0,
        "complete": False,
    }


async def test_a_finished_turn_counts_each_provider_request_once_and_says_the_total_is_complete(
    client: httpx.AsyncClient, api_engine: FakeChatEngine
) -> None:
    conversation = await new_group_conversation(client)
    with_a_key(api_engine)
    api_engine.script = [
        UsageReported(TokenUsage(100, 20, 0)),
        UsageReported(TokenUsage(300, 40, 90)),
        TextDelta("Sharpen it on a fine stone."),
        ChatDone(None),
    ]

    await send(client, conversation["id"], "Which stone?")

    detail = await conversation_of(client, conversation["id"])
    question, answer = detail["messages"]
    assert question["usage"] == {
        "input_tokens": 400,
        "output_tokens": 60,
        "cache_read_tokens": 90,
        "complete": True,
    }
    # Provenance is on the answer; the accounting stays on the question it answered, counted once.
    assert (answer["engine"], answer["model"]) == ("api", API_MODELS["fast"])
    assert answer["usage"] is None
    assert detail["usage"]["input_tokens"] == 400


async def test_a_turn_whose_engine_reports_no_usage_says_so_rather_than_recording_zero(
    client: httpx.AsyncClient, engine: FakeChatEngine
) -> None:
    conversation = await new_group_conversation(client)

    await send(client, conversation["id"], "Which stone?")

    detail = await conversation_of(client, conversation["id"])
    assert detail["messages"][0]["usage"] is None
    assert detail["usage"]["complete"] is False


async def test_a_settings_change_reaches_the_next_turn_not_the_one_already_answering(
    client: httpx.AsyncClient, engine: FakeChatEngine, api_engine: FakeChatEngine
) -> None:
    conversation = await new_group_conversation(client)
    never = asyncio.Event()

    async def hang(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        yield TextDelta("Half an ans")
        await never.wait()
        yield ChatDone("session-1")

    engine.respond = hang
    answering = asyncio.create_task(send(client, conversation["id"], "One?"))
    await wait_for_request(engine)
    with_a_key(api_engine)
    assert (await client.patch("/api/settings", json={"engine": "api"})).status_code == 200
    assert (await client.delete(f"/api/conversations/{conversation['id']}/turn")).status_code == 204
    await answering

    await send(client, conversation["id"], "Two?")

    # The turn in flight stayed on the engine it started with; the change landed on the next one.
    assert [r.message for r in engine.requests] == ["One?"]
    assert [r.message for r in api_engine.requests] == ["Two?"]


async def test_storing_a_key_announces_the_change_so_the_composer_comes_alive_without_a_reload(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setup should end where it started; a friend shouldn't have to reload to find chat working."""
    async def models_list(
        http: httpx2.AsyncClient, http_request: httpx2.Request, **kwargs: object
    ) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={"data": [], "has_more": False, "first_id": None, "last_id": None},
            request=http_request,
        )

    monkeypatch.setattr(httpx2.AsyncClient, "send", models_list)
    secrets = FakeSecrets()
    cli = FakeChatEngine("cli", engine_status=ChatEngineStatus("cli", "missing", None, "Install Claude Code"))
    # The real ApiEngine, so what Health reports comes from the credential the request stored.
    app = create_app(
        config, transcripts, FakeEmbedder(), FakeReranker(), cli, static_dir=tmp_path / "none", secrets=secrets
    )

    async with running(app) as client, event_stream(app) as stream:
        before = (await client.get("/api/health")).json()["chat"]
        stored = await client.put("/api/credentials/anthropic", json={"key": "sk-ant-new"})
        announced = await stream.until(lambda event: event["type"] == "credentials")
        after = (await client.get("/api/health")).json()["chat"]

    assert before["active"] is None and before["engines"]["api"]["state"] == "no_key"
    assert stored.status_code == 200
    assert announced[-1] == {"type": "credentials"}
    # Reconnecting refetches Health rather than trusting an event that may have been missed.
    assert after["active"] == "api"
    assert after["engines"]["api"]["state"] == "ready"


async def test_a_conversation_continues_after_a_restart_because_history_comes_from_the_store(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    """The API engine keeps no session anywhere, so a restart must cost nothing."""
    api = FakeChatEngine("api", engine_status=ChatEngineStatus("api", "ready"))
    api.script = [TextDelta("Use a fine stone."), ChatDone(None)]

    def build() -> FastAPI:
        return create_app(
            config,
            transcripts,
            FakeEmbedder(),
            FakeReranker(),
            FakeChatEngine("cli"),
            static_dir=tmp_path / "none",
            secrets=FakeSecrets(),
            api_engine=api,
        )

    async with running(build()) as client:
        group = await add_group(client, "Woodworking", await add_channel(client, "@woodbywright"))
        conversation = await start_conversation(client, group["id"])
        await send(client, conversation["id"], "Which stone?")

    async with running(build()) as client:
        await send(client, conversation["id"], "And for a plane iron?")
        reopened = await conversation_of(client, conversation["id"])

    assert [(m.role, m.content) for m in api.requests[-1].history] == [
        ("user", "Which stone?"),
        ("assistant", "Use a fine stone."),
    ]
    assert [(m["role"], m["engine"]) for m in reopened["messages"]] == [
        ("user", "api"),
        ("assistant", "api"),
        ("user", "api"),
        ("assistant", "api"),
    ]


async def test_stopping_the_server_mid_turn_still_records_what_that_turn_cost(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    """Shutdown cancels the turn, and the accounting it already had must still reach the store."""
    api = FakeChatEngine("api", engine_status=ChatEngineStatus("api", "ready"))
    never = asyncio.Event()

    async def hang(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        yield UsageReported(TokenUsage(120, 15, 0))
        yield TextDelta("Half an ans")
        await never.wait()
        yield ChatDone(None)

    api.respond = hang

    def build() -> FastAPI:
        return create_app(
            config,
            transcripts,
            FakeEmbedder(),
            FakeReranker(),
            FakeChatEngine("cli"),
            static_dir=tmp_path / "none",
            secrets=FakeSecrets(),
            api_engine=api,
        )

    async with running(build()) as client:
        group = await add_group(client, "Woodworking", await add_channel(client, "@woodbywright"))
        conversation = await start_conversation(client, group["id"])
        answering = asyncio.create_task(send(client, conversation["id"], "Which stone?"))
        await wait_for_request(api)
    await asyncio.gather(answering, return_exceptions=True)

    async with running(build()) as client:
        [question] = (await conversation_of(client, conversation["id"]))["messages"]
    assert question["usage"] == {
        "input_tokens": 120,
        "output_tokens": 15,
        "cache_read_tokens": 0,
        "complete": False,
    }


async def test_a_turn_whose_usage_cannot_be_recorded_still_ends_its_stream(
    client: httpx.AsyncClient, api_engine: FakeChatEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The answer is already saved and streamed. Losing the accounting must not strand the reader, which
    waits for the stream's terminator and would otherwise never stop."""
    conversation = await new_group_conversation(client)
    with_a_key(api_engine)
    api_engine.script = [UsageReported(TokenUsage(120, 15, 0)), TextDelta("Use a fine stone."), ChatDone(None)]

    def unwritable(conn: object, *args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(conversations, "record_usage", unwritable)

    async with asyncio.timeout(5):
        response = await send(client, conversation["id"], "Which stone?")

    assert stream_events(response)[-1]["type"] == "done"
    # The answer is intact; only the usage is missing, and the total says so rather than reading as zero.
    detail = await conversation_of(client, conversation["id"])
    assert [m["content"] for m in detail["messages"]] == ["Which stone?", "Use a fine stone."]
    assert detail["messages"][0]["usage"] is None
    assert detail["usage"]["complete"] is False
