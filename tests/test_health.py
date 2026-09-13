import httpx

from mentor.config import Config


async def test_health_reports_server_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_reports_knowledge_base_ready_for_hybrid_search(
    client: httpx.AsyncClient, config: Config
) -> None:
    database = (await client.get("/api/health")).json()["database"]

    assert database["path"] == str(config.data_dir / "mentor.db")
    assert database["journal_mode"] == "wal"
    assert database["foreign_keys"] is True
    assert database["busy_timeout_ms"] > 0
    assert database["sqlite_vec"] == "v0.1.9"
    assert database["fts5"] is True
