from pathlib import Path

import httpx

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import fake_ports


async def test_server_serves_the_built_web_ui(config: Config, tmp_path: Path) -> None:
    static = tmp_path / "bundle"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<title>mentor</title>")
    (static / "assets" / "app.js").write_text("console.log('mentor')")
    app = create_app(config, fake_ports(), static_dir=static)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        index = await client.get("/")
        asset = await client.get("/assets/app.js")
        health = await client.get("/api/health")

    assert index.status_code == 200
    assert "<title>mentor</title>" in index.text
    assert asset.status_code == 200
    assert health.json()["status"] == "ok"
