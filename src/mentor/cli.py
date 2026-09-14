import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import uvicorn

from mentor.app import create_app
from mentor.claude_chat import ClaudeChatEngine
from mentor.config import HOST, Config, ConfigError, load_config
from mentor.errors import NotFound
from mentor.models import CrossEncoderReranker, GpuRunner, SentenceTransformerEmbedder
from mentor.service import TIMER_NAME, UNIT_NAME, install_service
from mentor.sync_command import SyncCommandError, answers, sync_channels
from mentor.youtube import YouTubeSettings, YouTubeTranscriptSource


def _config() -> Config:
    try:
        return load_config()
    except ConfigError as e:
        sys.exit(f"mentor: {e}")


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


def serve() -> None:
    config = _config()
    # proxy_headers=False: forwarded headers are handled deliberately by the app (ticket 17's
    # loopback check needs the real peer address, which uvicorn would otherwise rewrite).
    gpu = GpuRunner()
    embedder = SentenceTransformerEmbedder(config.embedding_model, config.embedding_dimension, gpu)
    reranker = CrossEncoderReranker(config.reranker_model, gpu)
    youtube = _youtube(config)
    # The chat drives the user's own Claude CLI, the one logged in to their subscription.
    on_path = shutil.which("claude")
    claude = config.claude_cli_path or (Path(on_path) if on_path else None)
    chat = ClaudeChatEngine(config.data_dir / "chat", claude)
    app = create_app(config, youtube, embedder, reranker, chat)
    # The event stream never ends on its own, so without a timeout shutdown waits for every open browser tab.
    uvicorn.run(app, host=HOST, port=config.port, proxy_headers=False, timeout_graceful_shutdown=5)


def _service_active() -> bool:
    try:
        return subprocess.run(["systemctl", "--user", "is-active", "--quiet", UNIT_NAME]).returncode == 0
    except OSError:
        return False


def sync(channel: str | None, reindex: bool = False) -> None:
    config = _config()
    embedder = SentenceTransformerEmbedder(config.embedding_model, config.embedding_dimension, GpuRunner())
    # The service counts as active as soon as it starts, before it answers: at login a scheduled Sync can start
    # alongside it, and waiting keeps the models from loading twice.
    server_wait_seconds = 30 if _service_active() else 0
    try:
        report = asyncio.run(
            sync_channels(config, channel, _youtube(config), embedder, server_wait_seconds, reindex=reindex)
        )
    except (SyncCommandError, NotFound) as e:
        sys.exit(f"mentor: {e}")
    if not report.syncs:
        print("No indexed Channels to Sync.")
        return
    if report.server_url is not None:
        print(f"Queued on the server at {report.server_url}, where their progress shows:")
        for queued in report.syncs:
            print(f"  {queued.mentor_name} / {queued.channel_name}")
        return
    print("No server was running, so the Syncs ran here:")
    for finished in report.syncs:
        outcome = f"failed: {finished.error}" if finished.status == "failed" else f"{finished.new_videos} new Videos"
        print(f"  {finished.mentor_name} / {finished.channel_name}: {outcome}")
    if any(s.status == "failed" for s in report.syncs):
        sys.exit(1)


def _systemctl(args: list[str]) -> None:
    subprocess.run(["systemctl", "--user", *args], check=True)


def _check_schedule(schedule: str) -> None:
    try:
        checked = subprocess.run(["systemd-analyze", "calendar", schedule], capture_output=True, text=True)
    except OSError as e:
        sys.exit(f"mentor: could not check the schedule with systemd-analyze: {e}")
    if checked.returncode != 0:
        sys.exit(f"mentor: {schedule!r} is not a systemd calendar expression, such as daily or 'Mon *-*-* 04:00'")


def install(sync_schedule: str | None) -> None:
    config = _config()
    if sync_schedule is not None:
        _check_schedule(sync_schedule)
    # The directory systemd searches for user units unless its manager was given another XDG_CONFIG_HOME.
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    try:
        # The script as this shell found it, e.g. ~/.local/bin/mentor for a uv tool install.
        installed = install_service(
            config, os.environ, Path(sys.argv[0]).absolute(), unit_dir, _systemctl, sync_schedule
        )
    except (OSError, subprocess.CalledProcessError) as e:
        sys.exit(f"mentor: could not install the service: {e}")
    for warning in installed.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Installed {installed.unit_path}")
    logs = f"journalctl --user -u {UNIT_NAME}"
    # A server that fails at startup (a bad config, the port taken) still counts as started for systemctl.
    url = f"http://{HOST}:{config.port}/"
    if not answers(f"{url}api/health", 30):
        sys.exit(f"mentor: the service started but isn't answering at {url}; see `{logs}`")
    print(f"mentor is running at {url} and starts whenever you log in.")
    print(f"Status: systemctl --user status {UNIT_NAME}    Logs: {logs}")
    if installed.timer_path is not None:
        print(f"Every indexed Channel Syncs on the schedule {sync_schedule!r}.")
        print(f"Next run: systemctl --user list-timers {TIMER_NAME}    Logs: journalctl --user -u mentor-sync")


def main() -> None:
    parser = argparse.ArgumentParser(prog="mentor")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help=f"run the Mentor server on {HOST}")
    sync_parser = commands.add_parser(
        "sync", help="Sync Channels through the running server, or in this process when none is running"
    )
    target = sync_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true", help="every indexed Channel")
    target.add_argument("--channel", metavar="NAME_OR_ID", help="the Channel with this name or YouTube channel id")
    reindex_parser = commands.add_parser(
        "reindex", help="Sync Channels as `sync` does, re-segmenting and re-embedding the Videos already indexed"
    )
    reindex_target = reindex_parser.add_mutually_exclusive_group(required=True)
    reindex_target.add_argument("--all", action="store_true", help="every indexed Channel")
    reindex_target.add_argument("--channel", metavar="NAME_OR_ID", help="the Channel with this name or YouTube channel id")
    install_parser = commands.add_parser(
        "install-service", help="run the server as a systemd user service that starts at login"
    )
    install_parser.add_argument(
        "--timer",
        nargs="?",
        const="daily",
        metavar="SCHEDULE",
        help="also Sync every indexed Channel on a schedule, a systemd calendar expression (default: daily)",
    )
    args = parser.parse_args()
    if args.command == "serve":
        serve()
    elif args.command == "sync":
        sync(args.channel)
    elif args.command == "reindex":
        sync(args.channel, reindex=True)
    elif args.command == "install-service":
        install(args.timer)
