from pathlib import Path

import httpx
import pytest
from harness import running

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource


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


async def test_server_refuses_to_start_when_the_data_dir_is_unusable(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    app = create_app(
        Config(data_dir=blocker / "data"), FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle"
    )

    with pytest.raises(OSError):
        async with running(app):
            pass
