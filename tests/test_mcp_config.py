import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from harness import add_channel, fake_channel, fake_video, free_port, said, serving, sync
from mcp import Client

from mentor import cli
from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeSecrets, FakeTranscriptSource

TOOLS = {"list_groups", "list_channels", "search", "expand", "get_video", "sql"}


def command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, port: int) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("MENTOR_PORT", str(port))
    monkeypatch.setattr(sys, "argv", ["mentor", "mcp-config"])


def endpoint(stdout: str) -> str:
    """The URL from the configuration a client would read, which is everything on stdout."""
    url: str = json.loads(stdout)["mcpServers"]["mentor"]["url"]
    return url


async def test_the_emitted_endpoint_lists_the_tools_and_answers_a_scoped_search_without_an_api_key(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-wright", "Sharpening", cues=said("Sharpen the chisel on a fine stone"))
    )
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-rex", "Honing", cues=said("Sharpen the knife on a coarse stone"))
    )
    # No key stored: the tools need none.
    app = create_app(
        config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "none",
        secrets=FakeSecrets(),
    )
    async with serving(app) as url, httpx.AsyncClient(base_url=url) as client:
        wright = await add_channel(client, "@woodbywright", "Paul Wright")
        rex = await add_channel(client, "@rexkrueger")
        await sync(client, wright, rex)
        command(monkeypatch, tmp_path, int(url.rsplit(":", 1)[1].rstrip("/")))
        await asyncio.to_thread(cli.main)
        captured = capsys.readouterr()
        async with Client(endpoint(captured.out)) as mcp:
            tools = {tool.name for tool in (await mcp.list_tools()).tools}
            result = await mcp.call_tool("search", {"query": "sharpen", "channels": [rex["id"]]})

    assert endpoint(captured.out) == f"{url}mcp"
    assert tools == TOOLS
    assert not result.is_error, result.content
    assert result.structured_content is not None
    found = result.structured_content["result"]
    assert found and {hit["channel_name"] for hit in found} == {"Rex Krueger"}
    assert f"claude mcp add --transport http --scope user mentor {url}mcp" in captured.err
    assert "does not register a Claude Desktop custom connector" in captured.err
    assert f"Mentor is answering at {url} now." in captured.err


def test_with_no_server_the_configuration_still_prints_and_says_to_run_mentor_serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    port = free_port()
    command(monkeypatch, tmp_path, port)

    cli.main()
    captured = capsys.readouterr()

    url = f"http://127.0.0.1:{port}/mcp"
    assert json.loads(captured.out) == {"mcpServers": {"mentor": {"type": "http", "url": url}}}
    assert "run `mentor serve`" in captured.err
    assert "Mentor is answering" not in captured.err
    assert "does not register a Claude Desktop custom connector" in captured.err
    assert not (tmp_path / "config").exists()
