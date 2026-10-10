from pathlib import Path

from harness import running

from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource


async def test_server_serves_the_built_web_ui_alongside_the_api(config: Config, tmp_path: Path) -> None:
    static = tmp_path / "bundle"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<title>seek</title>")
    (static / "assets" / "app.js").write_text("console.log('seek')")

    async with running(create_app(config, FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=static)) as client:
        index = await client.get("/")
        asset = await client.get("/assets/app.js")
        health = await client.get("/api/health")

    assert index.status_code == 200
    assert "<title>seek</title>" in index.text
    assert asset.status_code == 200
    # The bundle is mounted at "/" and must not shadow the API.
    assert health.json()["status"] == "ok"
