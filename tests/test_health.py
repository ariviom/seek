import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import httpx2
import pytest
from harness import running

from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeSecrets, FakeTranscriptSource
from seek.ports import ChatEngineStatus


async def test_health_reports_server_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_reports_database_configuration(client: httpx.AsyncClient, config: Config) -> None:
    database = (await client.get("/api/health")).json()["database"]

    assert database["path"] == str(config.database_path)
    assert database["journal_mode"] == "wal"
    assert database["foreign_keys"] is True
    assert database["busy_timeout_ms"] > 0
    assert database["sqlite_vec"].startswith("v")
    assert database["fts5"] is True


async def test_health_reports_both_chat_engines_and_which_one_would_answer(
    client: httpx.AsyncClient, engine: FakeChatEngine, api_engine: FakeChatEngine
) -> None:
    """The settings screen has to offer a choice this machine can honour, so both engines are reported."""
    with_cli = (await client.get("/api/health")).json()["chat"]
    api_engine.engine_status = ChatEngineStatus("api", "ready")
    with_key = (await client.get("/api/health")).json()["chat"]
    engine.engine_status = ChatEngineStatus("cli", "logged_out", "/usr/bin/claude", "Run `claude auth login`")
    still_api = (await client.get("/api/health")).json()["chat"]

    # No key stored, so the Claude CLI answers; a key makes the API engine the automatic choice.
    assert with_cli["active"] == "cli"
    assert with_cli["engines"]["api"] == {
        "engine": "api",
        "state": "no_key",
        "cli_path": None,
        "message": "Add an Anthropic API key",
    }
    assert with_cli["engines"]["cli"] == {
        "engine": "cli",
        "state": "ready",
        "cli_path": "/usr/bin/claude",
        "message": None,
    }
    assert with_key["active"] == "api"
    # A Claude CLI that went away doesn't change who answers, and its own state is still reported.
    assert still_api["active"] == "api"
    assert still_api["engines"]["cli"]["message"] == "Run `claude auth login`"


async def test_health_never_asks_the_provider_whether_the_stored_key_works(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    """An offline machine reports the last known state instead of flapping, so Health costs nothing."""
    stored = json.dumps({"key": "sk-ant-stored", "generation": "g1", "validity": "valid"})
    secrets = FakeSecrets(values={"anthropic": stored})
    # The real ApiEngine, over a fake store: what it reports must come from the store alone.
    app = create_app(
        config,
        transcripts,
        FakeEmbedder(),
        FakeReranker(),
        FakeChatEngine("cli"),
        static_dir=tmp_path / "no-bundle",
        secrets=secrets,
    )

    with monkeypatch_no_network():
        async with running(app) as client:
            chat = (await client.get("/api/health")).json()["chat"]

    assert chat["active"] == "api"
    assert chat["engines"]["api"] == {"engine": "api", "state": "ready", "cli_path": None, "message": None}
    # Health read the stored envelope and nothing else: the key itself never leaves the store.
    assert secrets.values["anthropic"] == stored


@contextmanager
def monkeypatch_no_network() -> Iterator[None]:
    """Any outgoing provider request inside the block is a failure, not a slow test."""

    async def refuse(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Health must not call the Anthropic API")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(httpx2.AsyncClient, "send", refuse)
        yield


async def test_server_refuses_to_start_when_the_data_dir_is_unusable(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    app = create_app(
        Config(data_dir=blocker / "data"), FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle"
    )

    with pytest.raises(OSError):
        async with running(app):
            pass
