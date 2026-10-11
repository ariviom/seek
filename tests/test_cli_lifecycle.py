import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
import uvicorn
from harness import add_channel, add_playlist, fake_channel, fake_video, serving, wait_for_syncs

from seek import cli
from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakePlaylist, FakeReranker, FakeTranscriptSource


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key in os.environ:
        if key.startswith("SEEK_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path


def command(monkeypatch: pytest.MonkeyPatch, platform: str, *args: str) -> None:
    # Change the CLI's OS view without changing the test runner's own platform.
    monkeypatch.setattr(sys, "argv", ["seek", *args])
    monkeypatch.setattr(cli, "sys", SimpleNamespace(**(vars(sys) | {"platform": platform})))


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_service_installation_off_linux_points_to_foreground_before_reading_config_or_running_systemd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SEEK_PORT", "invalid configuration must not obscure the platform message")

    def unexpected_process(*args: Any, **kwargs: Any) -> None:
        pytest.fail("service installation attempted an external command on a non-Linux platform")

    monkeypatch.setattr(subprocess, "run", unexpected_process)
    command(monkeypatch, platform, "install-service")

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert "Linux" in str(error.value)
    assert "seek serve" in str(error.value)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("timer", [["--timer"], ["--timer", "weekly"]])
def test_service_installation_has_no_sync_timer_since_the_server_checks_channels_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], timer: list[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    def unexpected_process(*args: Any, **kwargs: Any) -> None:
        pytest.fail("a refused option still ran an external command")

    monkeypatch.setattr(subprocess, "run", unexpected_process)
    command(monkeypatch, "linux", "install-service", *timer)

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert "unrecognized arguments: --timer" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_foreground_startup_creates_directories_and_explains_url_and_terminal_lifetime(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], platform: str
) -> None:
    monkeypatch.setenv("SEEK_PORT", "7468")
    reached_server = False

    def start_server(app: Any, **kwargs: Any) -> None:
        nonlocal reached_server
        reached_server = True
        assert (isolated_home / "config" / "seek").is_dir()
        assert (isolated_home / "data" / "seek").is_dir()
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 7468
        assert kwargs["proxy_headers"] is False
        assert kwargs["timeout_graceful_shutdown"] == 5
        output = capsys.readouterr().out
        assert "http://127.0.0.1:7468/" in output
        assert "Starting" in output
        assert "Closing this terminal stops Seek" in output

    monkeypatch.setattr(uvicorn, "run", start_server)
    command(monkeypatch, platform, "serve")
    cli.main()
    assert reached_server


@pytest.mark.parametrize("platform", ["darwin", "win32"])
@pytest.mark.parametrize("subcommand", ["sync", "reindex"])
async def test_sync_commands_off_linux_queue_work_on_the_foreground_server_without_systemctl(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    transcripts: FakeTranscriptSource, platform: str, subcommand: str,
) -> None:
    # Import the optional inference runtime before forbidding external commands (its import probes the host).
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)

    def unexpected_process(*args: Any, **kwargs: Any) -> None:
        pytest.fail("ordinary Sync tried to launch a process, including systemctl")

    monkeypatch.setattr(subprocess, "run", unexpected_process)
    app = create_app(
        Config(data_dir=isolated_home / "server"), transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(),
        static_dir=isolated_home / "none",
    )
    async with serving(app) as url, httpx.AsyncClient(base_url=url) as client:
        await add_channel(client, "@woodbywright", "Wood By Wright")
        monkeypatch.setenv("SEEK_PORT", str(urlsplit(url).port))
        command(monkeypatch, platform, subcommand, "--all")
        await asyncio.to_thread(cli.main)
        finished = await wait_for_syncs(client)

    assert "Queued on the server at" in capsys.readouterr().out
    assert [(s["source_name"], s["status"]) for s in finished] == [("Wood By Wright", "done")]


@pytest.mark.parametrize("subcommand", ["sync", "reindex"])
async def test_sync_commands_queue_one_playlist_on_the_running_server(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    transcripts: FakeTranscriptSource, subcommand: str,
) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-rex", "Rex video"))
    transcripts.playlists["PL-picks"] = FakePlaylist("Picks", [("UC-rex", "v-rex")])
    app = create_app(
        Config(data_dir=isolated_home / "server"), transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(),
        static_dir=isolated_home / "none",
    )
    async with serving(app) as url, httpx.AsyncClient(base_url=url) as client:
        await add_channel(client, "@woodbywright", "Wood By Wright")
        await add_playlist(client, "PL-picks", "Sharpening picks")
        monkeypatch.setenv("SEEK_PORT", str(urlsplit(url).port))
        command(monkeypatch, "darwin", subcommand, "--playlist", "sharpening picks")
        await asyncio.to_thread(cli.main)
        finished = await wait_for_syncs(client)

    assert capsys.readouterr().out.splitlines() == [
        f"Queued on the server at {url}, where their progress shows:",
        "  Sharpening picks",
    ]
    assert [(s["source_name"], s["status"]) for s in finished] == [("Sharpening picks", "done")]


@pytest.mark.parametrize("subcommand", ["sync", "reindex", "backfill-storyboards"])
@pytest.mark.parametrize("other", [["--all"], ["--channel", "Wood By Wright"]])
def test_a_playlist_cannot_be_named_alongside_everything_or_a_channel(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], subcommand: str, other: list[str]
) -> None:
    command(monkeypatch, "linux", subcommand, "--playlist", "Sharpening picks", *other)

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert "not allowed with argument --playlist" in capsys.readouterr().err


def test_startup_preserves_existing_config_and_database(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = isolated_home / "config" / "seek" / "config.toml"
    config_file.parent.mkdir(parents=True)
    database = isolated_home / "data" / "seek" / "seek.db"
    database.parent.mkdir(parents=True)
    config_file.write_text("port = 7469\n")
    database.write_bytes(b"existing knowledge base")

    def start_server(app: Any, **kwargs: Any) -> None:
        assert kwargs["port"] == 7469
        assert config_file.read_text() == "port = 7469\n"
        assert database.read_bytes() == b"existing knowledge base"

    monkeypatch.setattr(uvicorn, "run", start_server)
    command(monkeypatch, "linux", "serve")
    cli.main()


def test_directory_creation_failure_identifies_the_path_before_starting_the_server(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    blocked = isolated_home / "blocked"
    blocked.write_text("existing file")
    monkeypatch.setenv("SEEK_DATA_DIR", str(blocked))

    def unexpected_server(*args: Any, **kwargs: Any) -> None:
        pytest.fail("server started despite an unusable data directory")

    monkeypatch.setattr(uvicorn, "run", unexpected_server)
    command(monkeypatch, "linux", "serve")
    with pytest.raises(SystemExit) as error:
        cli.main()

    assert "seek:" in str(error.value)
    assert str(blocked) in str(error.value)
    assert blocked.read_text() == "existing file"
    assert "Starting Seek" not in capsys.readouterr().out


def test_server_startup_failure_remains_visible_and_does_not_claim_readiness(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def failed_server(*args: Any, **kwargs: Any) -> None:
        print("ERROR: address already in use", file=sys.stderr)
        raise SystemExit(1)

    monkeypatch.setattr(uvicorn, "run", failed_server)
    command(monkeypatch, "linux", "serve")
    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 1
    captured = capsys.readouterr()
    assert "address already in use" in captured.err
    assert "Starting Seek" in captured.out
    assert "watch the startup log for readiness" in captured.out
    assert "is running" not in captured.out
