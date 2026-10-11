import argparse
import asyncio
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import uvicorn

from seek.api_chat import ApiEngine
from seek.app import create_app
from seek.backfill_command import backfill_storyboards
from seek.bundles import export_channel, format_export, format_import, import_bundle
from seek.claude_chat import ClaudeChatEngine
from seek.config import HOST, Config, ConfigError, config_dir, data_dir, ensure_directories, load_config
from seek.credentials import Credentials
from seek.devices import probe_device, select_device
from seek.doctor import Machine, diagnose
from seek.errors import Conflict, NotFound
from seek.events import Events
from seek.mcp_config import client_config, guidance
from seek.models import CrossEncoderReranker, GpuRunner, SentenceTransformerEmbedder
from seek.ports import ChatEngine, EngineName
from seek.secrets import KeyringSecrets
from seek.service import UNIT_NAME, install_service, unit_dir
from seek.status_command import format_list, format_status, list_all, status
from seek.sync_command import SyncCommandError, answers, sync_channels
from seek.youtube import YouTubeSettings, YouTubeTranscriptSource


def _config() -> Config:
    try:
        return load_config()
    except ConfigError as e:
        sys.exit(f"seek: {e}")


def _youtube(config: Config) -> YouTubeTranscriptSource:
    return YouTubeTranscriptSource(
        YouTubeSettings(
            delay_seconds=config.youtube_delay_seconds,
            retries=config.youtube_retries,
            backoff_seconds=config.youtube_backoff_seconds,
            cookie_file=config.youtube_cookie_file,
            cookies_from_browser=config.youtube_cookies_from_browser,
            extractor_args=config.youtube_extractor_args,
        )
    )


def _chat_engine(config: Config) -> ClaudeChatEngine:
    # The chat drives the user's own Claude CLI, the one logged in to their subscription.
    on_path = shutil.which("claude")
    claude = config.claude_cli_path or (Path(on_path) if on_path else None)
    return ClaudeChatEngine(config.data_dir / "chat", claude)


def _chat_engines(config: Config) -> dict[EngineName, ChatEngine]:
    """Both engines, for a `seek status` with no server to ask. The events go nowhere: nothing subscribes."""
    return {"api": ApiEngine(Credentials(KeyringSecrets(config.data_dir), Events())), "cli": _chat_engine(config)}


def serve() -> None:
    config = _config()
    try:
        ensure_directories(config)
    except ConfigError as e:
        sys.exit(f"seek: {e}")
    # proxy_headers=False: forwarded headers are handled deliberately by the app (ticket 17's
    # loopback check needs the real peer address, which uvicorn would otherwise rewrite).
    gpu = GpuRunner()
    selection = select_device(probe_device())
    embedder = SentenceTransformerEmbedder(config.embedding_model, config.embedding_dimension, gpu, selection)
    reranker = CrossEncoderReranker(config.reranker_model, gpu, selection)
    youtube = _youtube(config)
    app = create_app(config, youtube, embedder, reranker, _chat_engine(config), secrets=KeyringSecrets(config.data_dir))
    print(f"Starting Seek at http://{HOST}:{config.port}/ — watch the startup log for readiness.", flush=True)
    print("Closing this terminal stops Seek. Press Ctrl+C to stop it.", flush=True)
    # The event stream never ends on its own, so without a timeout shutdown waits for every open browser tab.
    uvicorn.run(app, host=config.listen_host, port=config.port, proxy_headers=False, timeout_graceful_shutdown=5)


def _service_active() -> bool:
    if sys.platform != "linux":
        return False
    try:
        return subprocess.run(["systemctl", "--user", "is-active", "--quiet", UNIT_NAME]).returncode == 0
    except OSError:
        return False


def sync(channel: str | None, playlist: str | None, reindex: bool = False) -> None:
    config = _config()
    embedder = SentenceTransformerEmbedder(
        config.embedding_model, config.embedding_dimension, GpuRunner(), select_device(probe_device())
    )
    # The service counts as active as soon as it starts, before it answers: a `seek sync` run at login can start
    # alongside it, and waiting keeps the models from loading twice.
    server_wait_seconds = 30 if _service_active() else 0
    try:
        report = asyncio.run(
            sync_channels(
                config, channel, _youtube(config), embedder, server_wait_seconds, reindex=reindex, playlist=playlist
            )
        )
    except (SyncCommandError, NotFound) as e:
        sys.exit(f"seek: {e}")
    if not report.syncs:
        print("No active Channels or Playlists to Sync.")
        return
    if report.server_url is not None:
        print(f"Queued on the server at {report.server_url}, where their progress shows:")
        for queued in report.syncs:
            print(f"  {queued.source_name}")
        return
    print("No server was running, so the Syncs ran here:")
    for finished in report.syncs:
        outcome = f"failed: {finished.error}" if finished.status == "failed" else f"{finished.new_videos} new Videos"
        print(f"  {finished.source_name}: {outcome}")
    if any(s.status == "failed" for s in report.syncs):
        sys.exit(1)


@contextlib.contextmanager
def _own_cookies(config: Config) -> Iterator[Config]:
    """A config whose cookie jar is this process's alone, for a command that runs beside the server.

    yt-dlp rewrites the cookie file as each session closes, and the server holds the same one: a write from here
    could replace cookies YouTube had just rotated for a running Sync. A copy is read, rotated within this run, and
    thrown away; the real jar is never written.
    """
    if config.youtube_cookie_file is None:
        yield config
        return
    with tempfile.TemporaryDirectory(prefix="seek-cookies-") as directory:
        jar = Path(directory) / "cookies.txt"
        try:
            shutil.copy2(config.youtube_cookie_file, jar)
        except OSError as e:
            sys.exit(f"seek: could not read {config.youtube_cookie_file}: {e}")
        yield replace(config, youtube_cookie_file=jar)


def backfill(channel: str | None, playlist: str | None) -> None:
    config = _config()
    try:
        with _own_cookies(config) as own:
            report = backfill_storyboards(
                config, channel, _youtube(own), lambda line: print(line, flush=True), playlist
            )
    except (SyncCommandError, NotFound) as e:
        sys.exit(f"seek: {e}")
    print(f"Stored {report.stored} storyboards; {report.absent} Videos offered none; {report.failed} could not be read.")
    if report.stopped is not None:
        print(f"Stopped with {report.remaining} Videos left: {report.stopped}")
        print("Run the command again to carry on where it stopped.")
        sys.exit(1)


def export(channel: str, file: Path) -> None:
    try:
        print(format_export(export_channel(_config(), channel, file)))
    except SyncCommandError as e:
        sys.exit(f"seek: {e}")


def import_(file: Path, name: str | None) -> None:
    try:
        print(format_import(import_bundle(_config(), file, name)))
    except (SyncCommandError, Conflict) as e:
        sys.exit(f"seek: {e}")


def show_status() -> None:
    config = _config()
    try:
        print(format_status(asyncio.run(status(config, _chat_engines(config)))))
    except SyncCommandError as e:
        sys.exit(f"seek: {e}")


def show_list() -> None:
    try:
        print(format_list(asyncio.run(list_all(_config()))))
    except SyncCommandError as e:
        sys.exit(f"seek: {e}")


def doctor() -> None:
    config_file = config_dir(os.environ, sys.platform, Path.home()) / "config.toml"
    try:
        config, problem = load_config(), None
    except ConfigError as e:
        # The rest of the report is still worth having, read from the default locations.
        config, problem = Config(data_dir=data_dir(os.environ, sys.platform, Path.home())), str(e)
    secrets = KeyringSecrets(config.data_dir)
    engines: dict[EngineName, ChatEngine] = {
        "api": ApiEngine(Credentials(secrets, Events())), "cli": _chat_engine(config)
    }
    # Whatever Python code prints to stderr while being asked (prints, warnings, log records) could carry what the
    # block redacts, so it is discarded; output a native library writes straight to the file descriptor is not.
    # An unexpected failure is named without its message.
    try:
        with contextlib.redirect_stderr(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            service_unit = unit_dir(Path.home()) / UNIT_NAME
            block = asyncio.run(diagnose(config, config_file, problem, secrets, engines, Machine(), service_unit))
    except Exception as e:
        sys.exit(f"seek: doctor could not finish ({type(e).__name__})")
    print(block)


def mcp_config() -> None:
    config = _config()
    print(json.dumps(client_config(config), indent=2), flush=True)
    running = answers(f"http://{HOST}:{config.port}/api/syncs", 0)
    print(guidance(config, running), file=sys.stderr)


def _systemctl(args: list[str]) -> None:
    subprocess.run(["systemctl", "--user", *args], check=True)


def install() -> None:
    if sys.platform != "linux":
        sys.exit("seek: install-service is supported only on Linux with systemd; run `seek serve` in a terminal")
    config = _config()
    try:
        # The script as this shell found it, e.g. ~/.local/bin/seek for a uv tool install.
        installed = install_service(
            config, os.environ, Path(sys.argv[0]).absolute(), unit_dir(Path.home()), _systemctl
        )
    except (OSError, subprocess.CalledProcessError) as e:
        sys.exit(f"seek: could not install the service: {e}")
    for warning in installed.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Installed {installed.unit_path}")
    logs = f"journalctl --user -u {UNIT_NAME}"
    # A server that fails at startup (a bad config, the port taken) still counts as started for systemctl.
    url = f"http://{HOST}:{config.port}/"
    if not answers(f"{url}api/health", 30):
        sys.exit(f"seek: the service started but isn't answering at {url}; see `{logs}`")
    print(f"Seek is running at {url} and starts whenever you log in.")
    print(f"Status: systemctl --user status {UNIT_NAME}    Logs: {logs}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="seek")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the Seek server")
    sync_parser = commands.add_parser(
        "sync", help="Sync Channels and Playlists through the running server, or in this process when none is running"
    )
    target = sync_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true", help="every active Channel and Playlist")
    target.add_argument("--channel", metavar="NAME_OR_ID", help="the Channel with this name or YouTube channel id")
    target.add_argument("--playlist", metavar="NAME_OR_ID", help="the Playlist with this name or YouTube playlist id")
    reindex_parser = commands.add_parser(
        "reindex", help="Sync as `sync` does, re-segmenting and re-embedding the Videos already indexed"
    )
    reindex_target = reindex_parser.add_mutually_exclusive_group(required=True)
    reindex_target.add_argument("--all", action="store_true", help="every active Channel and Playlist")
    reindex_target.add_argument("--channel", metavar="NAME_OR_ID", help="the Channel with this name or YouTube channel id")
    reindex_target.add_argument(
        "--playlist", metavar="NAME_OR_ID", help="the Playlist with this name or YouTube playlist id"
    )
    backfill_parser = commands.add_parser(
        "backfill-storyboards",
        help="store the frames of already-ingested Videos, paced as a Sync is; safe to stop and run again",
    )
    backfill_target = backfill_parser.add_mutually_exclusive_group(required=True)
    backfill_target.add_argument("--all", action="store_true", help="every Channel and Playlist")
    backfill_target.add_argument("--channel", metavar="NAME_OR_ID", help="the Channel with this name or YouTube channel id")
    backfill_target.add_argument(
        "--playlist", metavar="NAME_OR_ID", help="the Playlist with this name or YouTube playlist id"
    )
    export_parser = commands.add_parser(
        "export", help="write a Channel's indexed Videos to a Bundle, a .seek file another Seek can import"
    )
    export_parser.add_argument(
        "--channel", metavar="NAME_OR_ID", required=True, help="the Channel with this name or YouTube channel id"
    )
    export_parser.add_argument("file", metavar="FILE", type=Path, help="where to write it; .seek is added if missing")
    import_parser = commands.add_parser(
        "import",
        help="add a Bundle's Channel to the Library, or its Videos to the Channel already there; searchable at once "
        "with nothing fetched or embedded",
    )
    import_parser.add_argument("file", metavar="FILE", type=Path, help="the .seek file to import")
    import_parser.add_argument(
        "--name", metavar="NAME", help="the name to add the Channel under; one already in the Library keeps its own"
    )
    commands.add_parser("status", help="the server, models, chat engines, and running and queued Syncs")
    commands.add_parser("list", help="Channels, with Video counts and when each last synced, then Groups and Playlists")
    commands.add_parser("doctor", help="one pasteable block for support, with every secret redacted")
    commands.add_parser(
        "mcp-config", help="the configuration that registers Seek's tools with Claude Code and similar agents"
    )
    commands.add_parser("install-service", help="run the server as a systemd user service that starts at login")
    args = parser.parse_args()
    if args.command == "serve":
        serve()
    elif args.command == "sync":
        sync(args.channel, args.playlist)
    elif args.command == "reindex":
        sync(args.channel, args.playlist, reindex=True)
    elif args.command == "backfill-storyboards":
        backfill(args.channel, args.playlist)
    elif args.command == "export":
        export(args.channel, args.file)
    elif args.command == "import":
        import_(args.file, args.name)
    elif args.command == "status":
        show_status()
    elif args.command == "list":
        show_list()
    elif args.command == "doctor":
        doctor()
    elif args.command == "mcp-config":
        mcp_config()
    elif args.command == "install-service":
        install()
