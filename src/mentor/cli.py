import argparse
import sys

import uvicorn

from mentor.app import create_app
from mentor.config import ConfigError, load_config
from mentor.embeddings import SentenceTransformerEmbedder, SentenceTransformerReranker
from mentor.youtube import YouTubeSettings, YouTubeTranscriptSource

HOST = "127.0.0.1"


def serve() -> None:
    try:
        config = load_config()
    except ConfigError as e:
        sys.exit(f"mentor: {e}")
    # proxy_headers=False: forwarded headers are handled deliberately by the app (ticket 17's
    # loopback check needs the real peer address, which uvicorn would otherwise rewrite).
    embedder = SentenceTransformerEmbedder(config.embedding_model, config.embedding_dimension)
    youtube = YouTubeTranscriptSource(
        YouTubeSettings(
            delay_seconds=config.youtube_delay_seconds,
            retries=config.youtube_retries,
            backoff_seconds=config.youtube_backoff_seconds,
            cookie_file=config.youtube_cookie_file,
        )
    )
    app = create_app(config, youtube, embedder, SentenceTransformerReranker())
    # The event stream never ends on its own, so without a timeout shutdown waits for every open browser tab.
    uvicorn.run(app, host=HOST, port=config.port, proxy_headers=False, timeout_graceful_shutdown=5)


def main() -> None:
    parser = argparse.ArgumentParser(prog="mentor")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help=f"run the Mentor server on {HOST}")
    args = parser.parse_args()
    if args.command == "serve":
        serve()
