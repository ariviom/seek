import argparse
import sys

import uvicorn

from mentor.app import create_app
from mentor.config import ConfigError, load_config
from mentor.embeddings import SentenceTransformerEmbedder
from mentor.youtube import YouTubeTranscriptSource

HOST = "127.0.0.1"


def serve() -> None:
    try:
        config = load_config()
    except ConfigError as e:
        sys.exit(f"mentor: {e}")
    # proxy_headers=False: forwarded headers are handled deliberately by the app (ticket 17's
    # loopback check needs the real peer address, which uvicorn would otherwise rewrite).
    embedder = SentenceTransformerEmbedder(config.embedding_model, config.embedding_dimension)
    app = create_app(config, YouTubeTranscriptSource(), embedder)
    uvicorn.run(app, host=HOST, port=config.port, proxy_headers=False)


def main() -> None:
    parser = argparse.ArgumentParser(prog="mentor")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help=f"run the Mentor server on {HOST}")
    args = parser.parse_args()
    if args.command == "serve":
        serve()
