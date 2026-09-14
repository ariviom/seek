from pathlib import Path

from harness import running

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource


async def test_server_serves_the_built_web_ui_alongside_the_api(config: Config, tmp_path: Path) -> None:
    static = tmp_path / "bundle"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<title>mentor</title>")
    (static / "assets" / "app.js").write_text("console.log('mentor')")

    async with running(create_app(config, FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=static)) as client:
        index = await client.get("/")
        asset = await client.get("/assets/app.js")
        health = await client.get("/api/health")

    assert index.status_code == 200
    assert "<title>mentor</title>" in index.text
    assert asset.status_code == 200
    # The bundle is mounted at "/" and must not shadow the API.
    assert health.json()["status"] == "ok"
