import argparse
import sys

import uvicorn

from mentor.app import create_app
from mentor.config import ConfigError, load_config

HOST = "127.0.0.1"


def serve() -> None:
    try:
        config = load_config()
    except ConfigError as e:
        sys.exit(f"mentor: {e}")
    uvicorn.run(create_app(config, ports=None), host=HOST, port=config.port)


def main() -> None:
    parser = argparse.ArgumentParser(prog="mentor")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the Mentor server on 127.0.0.1")
    args = parser.parse_args()
    if args.command == "serve":
        serve()
