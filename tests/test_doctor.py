import asyncio
import json
import sqlite3
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import httpx
import pytest
from harness import add_channel, fake_channel, fake_video, free_port, running, serving, wait_for_syncs

from mentor import cli, db, doctor
from mentor.api_chat import ApiEngine
from mentor.app import create_app
from mentor.config import Config
from mentor.credentials import Credentials
from mentor.devices import DeviceProbe
from mentor.doctor import Machine, diagnose
from mentor.events import Events
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeSecrets, FakeTranscriptSource
from mentor.ports import ChatEngine, EngineName, ModelStatus, SecretStoreStatus, SecretsUnavailable, VideoUnavailable

# Distinctive values, so finding any of them anywhere in the output is a leak.
KEY = "SEEDED-anthropic-key-5b1e0c"
PO_TOKEN = "SEEDED-po-token-81c2d9"
BROWSER = "firefox:SEEDEDprofile"
# Never stored, but shaped like a key: redacted by its shape.
SHAPED_KEY = "sk-ant-api03-SEEDEDshapedkey"


def stored_key(key: str = KEY) -> FakeSecrets:
    return FakeSecrets({"anthropic": json.dumps({"key": key, "generation": "g-1", "validity": "valid"})})


def machine(
    probe_device: Callable[[], DeviceProbe] = lambda: DeviceProbe(cuda=False, mps=True, cuda_bfloat16=False),
    ytdlp_version: Callable[[], str] = lambda: "2026.08.19",
    which: Callable[[str], str | None] = lambda name: f"/usr/bin/{name}" if name == "deno" else None,
) -> Machine:
    """No torch, no real yt-dlp lookup and no PATH search: every answer is the test's."""
    return Machine(probe_device, ytdlp_version, which)


def engines() -> dict[EngineName, ChatEngine]:
    return {"api": FakeChatEngine("api"), "cli": FakeChatEngine("cli")}


def leaked(output: str, cookie_file: Path) -> list[str]:
    return [s for s in (KEY, PO_TOKEN, BROWSER, "SEEDEDprofile", str(cookie_file), SHAPED_KEY) if s in output]


@dataclass
class LeakyReranker(FakeReranker):
    """A reranker whose failure and CPU fallback both quote a credential, as a library error might."""

    def load(self) -> None:
        pass

    def status(self) -> ModelStatus:
        return ModelStatus(
            self.model_name, "failed", error=f"scoring failed with token {PO_TOKEN}", device="cpu",
            precision="float32", fallback_reason=f"MPS refused; key {KEY}",
        )


def seeded(config: Config, cookie_file: Path) -> Config:
    return replace(
        config,
        youtube_cookie_file=cookie_file,
        youtube_cookies_from_browser=BROWSER,
        youtube_extractor_args={"po_token": (f"web+{PO_TOKEN}",), "player_client": ("mweb",)},
    )


async def seed_failures(
    client: httpx.AsyncClient, config: Config, transcripts: FakeTranscriptSource, cookie_file: Path
) -> None:
    """A failed Video and two failed Syncs whose stored messages quote every secret."""
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-ok", "Sharpening chisels"),
        fake_video("v-members", "Members stream", failure=VideoUnavailable(
            f"yt-dlp refused cookies from {cookie_file} ({BROWSER}) with po_token {PO_TOKEN}", permanent=True
        )),
    ]
    wright = await add_channel(client, "@woodbywright", "Paul Wright")
    await client.post(f"/api/channels/{wright['id']}/syncs")
    await wait_for_syncs(client)

    def failed_syncs(conn: sqlite3.Connection) -> None:
        # Written directly: a queued Sync would be claimed by the running worker.
        for error in (f"Anthropic said key {KEY} is wrong", f"Provider echoed {SHAPED_KEY}"):
            conn.execute(
                "INSERT INTO syncs (channel_id, status, error, queued_at, finished_at, stage_counts) "
                "VALUES (?, 'failed', ?, ?, ?, '{}')",
                (wright["id"], error, db.now_iso(), db.now_iso()),
            )

    await db.Database(config.database_path).run(failed_syncs)


def command(monkeypatch: pytest.MonkeyPatch, config: Config, secrets: FakeSecrets, probes: Machine) -> None:
    """`mentor doctor` as a friend runs it, configured through the environment, with fakes for the machine."""
    monkeypatch.setenv("HOME", str(config.data_dir.parent))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.data_dir.parent / "config"))
    monkeypatch.setenv("MENTOR_DATA_DIR", str(config.data_dir))
    monkeypatch.setenv("MENTOR_PORT", str(config.port))
    if config.youtube_cookie_file is not None:
        monkeypatch.setenv("MENTOR_YOUTUBE_COOKIE_FILE", str(config.youtube_cookie_file))
    if config.youtube_cookies_from_browser is not None:
        monkeypatch.setenv("MENTOR_YOUTUBE_COOKIES_FROM_BROWSER", config.youtube_cookies_from_browser)
    args = "\n".join(f"{name} = {json.dumps(list(values))}" for name, values in config.youtube_extractor_args.items())
    monkeypatch.setenv("MENTOR_YOUTUBE_EXTRACTOR_ARGS", args)
    monkeypatch.setattr(cli, "KeyringSecrets", lambda data_dir: secrets)
    monkeypatch.setattr(cli, "_chat_engine", lambda config: FakeChatEngine("cli"))
    monkeypatch.setattr(cli, "Machine", lambda: probes)
    monkeypatch.setattr(sys, "argv", ["mentor", "doctor"])


async def test_doctor_against_a_served_app_reports_its_state_and_leaks_no_seeded_secret(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    cookie_file = tmp_path / "SEEDED-cookie-jar" / "cookies.txt"
    config = seeded(config, cookie_file)
    secrets = stored_key()
    secrets.status = SecretStoreStatus("file", "The operating system keychain could not write credentials.")
    app = create_app(
        config, transcripts, FakeEmbedder(), LeakyReranker(), FakeChatEngine("cli"), static_dir=tmp_path / "none",
        secrets=secrets, api_engine=FakeChatEngine("api"),
    )
    async with serving(app) as url, httpx.AsyncClient(base_url=url) as client:
        await seed_failures(client, config, transcripts, cookie_file)
        await client.patch("/api/settings", json={"engine": "cli", "model": "deep"})
        served = replace(config, port=int(url.rsplit(":", 1)[1].rstrip("/")))
        # A server that answers leaves the device probe unused.
        command(monkeypatch, served, secrets, machine(probe_device=lambda: pytest.fail("probed with a server")))
        await asyncio.to_thread(cli.main)
    captured = capsys.readouterr()

    assert leaked(captured.out + captured.err, cookie_file) == []
    assert captured.err == ""
    lines = captured.out.splitlines()
    for expected in [
        f"Server: running at {url}",
        f"  data directory: {config.data_dir}",
        "Preferences: engine cli, provider anthropic, model deep",
        "  embedding: ready (fake-embedder)",
        "  reranker: failed (fake-reranker), cpu / float32; CPU fallback: MPS refused; key [redacted]",
        "Secret store: private fallback file",
        "  The operating system keychain could not write credentials.",
        "Chat: cli",
        "  YouTube cookie file: set (path redacted)",
        "  YouTube browser cookies: set (redacted)",
        "  YouTube extractor arguments: player_client=[redacted], po_token=[redacted]",
        "YouTube: yt-dlp 2026.08.19; JavaScript runtimes: deno /usr/bin/deno, node not found, bun not found",
        f"Database: schema {len(db.MIGRATIONS)} (current)",
        "  reranker model: scoring failed with token [redacted]",
        "  failed Videos: 1, latest first:",
        "    Video v-members (Members stream): yt-dlp refused cookies from [redacted] ([redacted]) with po_token "
        "[redacted]",
        "  failed Syncs: 2, latest first:",
    ]:
        assert expected in lines
    assert any(line.startswith("Mentor 0.1.0, Python ") for line in lines)
    assert "  rows: 1 channels, 0 groups, 2 videos" in captured.out
    [sync_errors] = [lines[i + 1 : i + 3] for i, line in enumerate(lines) if line.startswith("  failed Syncs")]
    assert [line.split(": ", 1)[1] for line in sync_errors] == [
        "Provider echoed [redacted]", "Anthropic said key [redacted] is wrong"
    ]


async def test_doctor_without_a_server_reads_the_store_without_changing_it(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    cookie_file = tmp_path / "SEEDED-cookie-jar" / "cookies.txt"
    config = seeded(replace(config, port=free_port()), cookie_file)
    app = create_app(
        config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "none"
    )
    async with running(app) as client:
        await seed_failures(client, config, transcripts, cookie_file)
        await client.patch("/api/settings", json={"engine": "api"})
    before = config.database_path.read_bytes()

    report = await diagnose(
        config, tmp_path / "config.toml", None, stored_key(), engines(), machine()
    )

    assert leaked(report, cookie_file) == []
    lines = report.splitlines()
    for expected in [
        f"Server: not running at http://127.0.0.1:{config.port}/; start it with `mentor serve`",
        "Preferences: engine api, provider anthropic, model fast",
        "Models: state unavailable, since only a running server loads them",
        "  expected device: mps / float32",
        "Secret store: OS keychain",
        "Chat: api",
        f"Database: schema {len(db.MIGRATIONS)} (current)",
        "  failed Videos: 1, latest first:",
        "  failed Syncs: 2, latest first:",
    ]:
        assert expected in lines
    assert config.database_path.read_bytes() == before


async def test_doctor_on_a_first_install_creates_nothing_and_labels_what_it_cannot_know(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path / "data", port=free_port())

    def no_torch() -> DeviceProbe:
        raise ImportError("No module named 'torch'")

    def no_ytdlp() -> str:
        raise FileNotFoundError("yt-dlp")

    report = await diagnose(
        config, tmp_path / "config.toml", None, FakeSecrets(), engines(),
        machine(probe_device=no_torch, ytdlp_version=no_ytdlp, which=lambda name: None),
    )

    lines = report.splitlines()
    for expected in [
        f"  config file: {tmp_path / 'config.toml'} (absent, so defaults apply)",
        "Preferences: engine automatic, provider anthropic, model fast",
        "  expected device: unavailable (ImportError: No module named 'torch')",
        "YouTube: yt-dlp unavailable (FileNotFoundError); JavaScript runtimes: deno not found, node not found, "
        "bun not found",
        "Database: none yet; `mentor serve` creates it on first start",
        "Recent errors: none stored",
    ]:
        assert expected in lines
    assert list(tmp_path.iterdir()) == []


async def test_doctor_reports_an_unreadable_or_older_database_without_migrating_it(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path, port=free_port())
    config.database_path.write_bytes(b"not a database" * 100)
    report = await diagnose(config, tmp_path / "config.toml", None, FakeSecrets(), engines(), machine())
    assert "Database: could not be read (file is not a database)" in report.splitlines()
    assert "Chat: api" in report

    config.database_path.unlink()
    with sqlite3.connect(config.database_path) as conn:
        conn.execute("PRAGMA user_version = 2")
    report = await diagnose(config, tmp_path / "config.toml", None, FakeSecrets(), engines(), machine())
    lines = report.splitlines()
    assert f"Database: schema 2 of {len(db.MIGRATIONS)}; `mentor serve` migrates it on start" in lines
    assert "  rows: none readable" in lines
    assert "Preferences: unavailable (the stored preferences could not be read)" in lines
    with sqlite3.connect(config.database_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


LOCKED = "The keychain credential is unavailable and no fallback copy exists. Unlock the keychain or replace the key."


class LockedKeychain(FakeSecrets):
    def get(self, name: str) -> str | None:
        self.status = SecretStoreStatus("keychain", LOCKED)
        raise SecretsUnavailable(LOCKED)


async def test_an_unavailable_keychain_is_explained_and_the_rest_still_prints(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path / "data", port=free_port())
    secrets = LockedKeychain()
    api = ApiEngine(Credentials(secrets, Events()))

    report = await diagnose(
        config, tmp_path / "config.toml", None, secrets, {"api": api, "cli": FakeChatEngine("cli")}, machine()
    )

    lines = report.splitlines()
    assert "Secret store: OS keychain" in lines
    assert f"  {LOCKED}" in lines
    # An unreadable key is worth reporting rather than quietly switching to the Claude CLI.
    assert "Chat: api" in lines
    assert "  api: unknown" in lines
    assert lines[-1] == "Recent errors: none stored"


def test_nothing_printed_while_diagnosing_escapes_redaction_on_stderr(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cookie_file = tmp_path / "SEEDED-cookie-jar" / "cookies.txt"
    config = seeded(replace(config, port=free_port()), cookie_file)

    def noisy_ytdlp() -> str:
        print(f"yt-dlp: reading {cookie_file}", file=sys.stderr)
        warnings.warn(f"po_token {PO_TOKEN} looks stale", stacklevel=1)
        raise RuntimeError(f"extractor args {PO_TOKEN} and key {KEY}")

    command(monkeypatch, config, stored_key(), machine(ytdlp_version=noisy_ytdlp))
    cli.main()
    captured = capsys.readouterr()

    assert leaked(captured.out + captured.err, cookie_file) == []
    assert captured.err == ""
    assert "YouTube: yt-dlp unavailable (RuntimeError)" in captured.out


def test_an_unexpected_failure_is_named_without_its_message(
    config: Config, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def broken(*args: object) -> str:
        raise RuntimeError(f"crashed holding {KEY}")

    command(monkeypatch, replace(config, port=free_port()), stored_key(), machine())
    monkeypatch.setattr(cli, "diagnose", broken)

    with pytest.raises(SystemExit) as exited:
        cli.main()

    assert str(exited.value) == "mentor: doctor could not finish (RuntimeError)"
    assert KEY not in capsys.readouterr().err


def test_an_unreadable_config_still_prints_the_report_and_withholds_stored_error_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = Config(data_dir=tmp_path / "data" / "mentor", port=free_port())
    command(monkeypatch, config, stored_key(), machine())
    for name in ("MENTOR_DATA_DIR", "MENTOR_PORT", "MENTOR_YOUTUBE_EXTRACTOR_ARGS"):
        monkeypatch.delenv(name)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    config_file = tmp_path / "data" / "config" / "mentor" / "config.toml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(f'youtube_extractor_args = {{ po_token = "{PO_TOKEN}" ')
    config.data_dir.mkdir(parents=True)

    def failed_video(conn: sqlite3.Connection) -> None:
        db.migrate(conn)
        conn.execute("INSERT INTO channels (youtube_channel_id, name) VALUES ('UC-x', 'X')")
        conn.execute(
            "INSERT INTO videos (channel_id, youtube_video_id, title, failure_stage, failure_reason, discovered_at) "
            f"VALUES (1, 'v', 'V', 'transcript_fetched', 'token {PO_TOKEN} refused', 'now')"
        )

    asyncio.run(db.Database(config.database_path).run(failed_video))
    # The fallback is the default port, where a real Mentor may be running on this machine.
    monkeypatch.setattr(doctor, "answers", lambda url, seconds: False)
    cli.main()
    out = capsys.readouterr().out

    assert PO_TOKEN not in out
    assert "(could not be read, so defaults are shown:" in out
    assert "  1 failed Videos and 0 failed Syncs; their messages are withheld until the config file can be read" in out
