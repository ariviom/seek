import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import uvicorn

from mentor.app import create_app
from mentor.claude_chat import ClaudeChatEngine
from mentor.config import Config, ConfigError, load_config
from mentor.models import CrossEncoderReranker, GpuRunner, SentenceTransformerEmbedder
from mentor.service import UNIT_NAME, install_service
from mentor.youtube import YouTubeSettings, YouTubeTranscriptSource

HOST = "127.0.0.1"


def _config() -> Config:
    try:
        return load_config()
    except ConfigError as e:
        sys.exit(f"mentor: {e}")


def serve() -> None:
    config = _config()
    # proxy_headers=False: forwarded headers are handled deliberately by the app (ticket 17's
    # loopback check needs the real peer address, which uvicorn would otherwise rewrite).
    gpu = GpuRunner()
    embedder = SentenceTransformerEmbedder(config.embedding_model, config.embedding_dimension, gpu)
    reranker = CrossEncoderReranker(config.reranker_model, gpu)
    youtube = YouTubeTranscriptSource(
        YouTubeSettings(
            delay_seconds=config.youtube_delay_seconds,
            retries=config.youtube_retries,
            backoff_seconds=config.youtube_backoff_seconds,
            cookie_file=config.youtube_cookie_file,
        )
    )
    # The chat drives the user's own Claude CLI, the one logged in to their subscription.
    on_path = shutil.which("claude")
    claude = config.claude_cli_path or (Path(on_path) if on_path else None)
    chat = ClaudeChatEngine(config.data_dir / "chat", claude)
    app = create_app(config, youtube, embedder, reranker, chat)
    # The event stream never ends on its own, so without a timeout shutdown waits for every open browser tab.
    uvicorn.run(app, host=HOST, port=config.port, proxy_headers=False, timeout_graceful_shutdown=5)


def _systemctl(args: list[str]) -> None:
    subprocess.run(["systemctl", "--user", *args], check=True)


def _answers(url: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5):
                return True
        except OSError:
            time.sleep(1)
    return False


def install() -> None:
    config = _config()
    # The directory systemd searches for user units unless its manager was given another XDG_CONFIG_HOME.
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    try:
        # The script as this shell found it, e.g. ~/.local/bin/mentor for a uv tool install.
        installed = install_service(config, os.environ, Path(sys.argv[0]).absolute(), unit_dir, _systemctl)
    except (OSError, subprocess.CalledProcessError) as e:
        sys.exit(f"mentor: could not install the service: {e}")
    for warning in installed.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Installed {installed.unit_path}")
    logs = f"journalctl --user -u {UNIT_NAME}"
    # A server that fails at startup (a bad config, the port taken) still counts as started for systemctl.
    url = f"http://{HOST}:{config.port}/"
    if not _answers(f"{url}api/health", 30):
        sys.exit(f"mentor: the service started but isn't answering at {url}; see `{logs}`")
    print(f"mentor is running at {url} and starts whenever you log in.")
    print(f"Status: systemctl --user status {UNIT_NAME}    Logs: {logs}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="mentor")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help=f"run the Mentor server on {HOST}")
    commands.add_parser("install-service", help="run the server as a systemd user service that starts at login")
    args = parser.parse_args()
    if args.command == "serve":
        serve()
    elif args.command == "install-service":
        install()
