import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from harness import add_channel, event_stream, running

from mentor import db
from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource


async def test_defaults_partial_updates_and_reset(client: httpx.AsyncClient) -> None:
    defaults = {"engine": None, "provider": "anthropic", "model": "fast"}
    assert (await client.get("/api/settings")).json() == defaults
    changed = await client.patch("/api/settings", json={"engine": "api", "model": "deep"})
    assert changed.status_code == 200
    assert changed.json() == {**defaults, "engine": "api", "model": "deep"}
    assert (await client.patch("/api/settings", json={"engine": "cli"})).json() == {
        **defaults, "engine": "cli", "model": "deep"
    }
    assert (await client.patch("/api/settings", json={"engine": None})).json() == {
        **defaults, "model": "deep"
    }
    assert (await client.patch("/api/settings", json={})).json() == {**defaults, "model": "deep"}


@pytest.mark.parametrize("invalid", [
    {"engine": "auto"}, {"engine": True}, {"provider": "openai"}, {"provider": None},
    {"model": "opus"}, {"model": None}, {"model": 1}, {"api_key": "must-not-store"},
    {"port": 8000},
])
async def test_invalid_patch_is_atomic(client: httpx.AsyncClient, invalid: dict[str, object]) -> None:
    response = await client.patch("/api/settings", json={"engine": "api", **invalid})
    assert response.status_code == 422
    assert (await client.get("/api/settings")).json() == {
        "engine": None, "provider": "anthropic", "model": "fast"
    }


@pytest.mark.parametrize("body", [
    b'{"api_key":"sk-secret-value"}',
    b'{"sk-secret-value":"unknown field"}',
    b'{"engine":"sk-secret-value"}',
    b'{"model":"sk-secret-value"',
])
async def test_invalid_settings_never_echo_credentials(client: httpx.AsyncClient, body: bytes) -> None:
    response = await client.patch("/api/settings", content=body, headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert "sk-secret-value" not in response.text


async def test_settings_survive_restart_and_publish_after_commit(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path,
) -> None:
    def app() -> FastAPI:
        return create_app(
            config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(),
            static_dir=tmp_path / "no-bundle",
        )

    first = app()
    async with running(first) as client, event_stream(first) as stream:
        await add_channel(client, "@woodbywright")
        response = await client.patch("/api/settings", json={"engine": "api", "model": "deep"})
        assert response.status_code == 200
        emitted = await stream.until(lambda event: event["type"] == "settings")
        assert emitted[-1] == {"type": "settings"}
        assert (await client.get("/api/settings")).json() == response.json()
    async with running(app()) as client:
        assert (await client.get("/api/settings")).json() == {
            "engine": "api", "provider": "anthropic", "model": "deep"
        }
        assert len((await client.get("/api/channels")).json()) == 1


def test_settings_migration_preserves_existing_database(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = db.connect(config.database_path)
    try:
        with monkeypatch.context() as previous:
            previous.setattr(db, "MIGRATIONS", db.MIGRATIONS[:11])
            db.migrate(conn)
        conn.execute("INSERT INTO channels (youtube_channel_id, name) VALUES ('UC-existing', 'Existing')")
        db.migrate(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 13
        assert conn.execute("SELECT name FROM channels").fetchone()[0] == "Existing"
        assert conn.execute("SELECT * FROM settings").fetchall() == []
        for key, value in [("engine", "other"), ("provider", "openai"), ("model", "opus"), ("api_key", "secret")]:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))
    finally:
        conn.close()
