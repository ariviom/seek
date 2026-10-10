"""Freeze a populated SQLite database without starting Seek or changing its schema.

Run with the project's Python environment. Keep the destination outside git and
inside a private directory: the snapshot contains transcripts and personal data.
Transfer only the completed .sqlite3 file, preserving its printed SHA-256.
"""

import argparse
import hashlib
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import sqlite_vec


def freeze(source: Path, destination: Path) -> str:
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Destination already exists: {destination}")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".snapshot-", suffix=".sqlite3", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        # mode=ro deliberately includes WAL. immutable=1 would silently ignore it.
        with closing(sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)) as live:
            with closing(sqlite3.connect(temporary)) as frozen:
                live.backup(frozen)
                frozen.enable_load_extension(True)
                sqlite_vec.load(frozen)
                frozen.enable_load_extension(False)
                frozen.execute("PRAGMA journal_mode=DELETE")
                if frozen.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Snapshot integrity check failed")
        with temporary.open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        temporary.chmod(0o444)
        # Publish only a complete snapshot; linking also refuses a racing overwrite.
        os.link(temporary, destination)
        return digest
    finally:
        temporary.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{temporary}{suffix}").unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    try:
        digest = freeze(args.source, args.destination)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Cannot freeze snapshot: {error}\n")
    print(f"sha256 {digest}  {args.destination.absolute()}")


if __name__ == "__main__":
    main()
