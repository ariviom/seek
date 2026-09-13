import asyncio
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

BUSY_TIMEOUT_MS = 5000

# Applied in order; PRAGMA user_version records how many have run. Never edit a shipped entry.
MIGRATIONS = [
    """
    CREATE TABLE mentors (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE channels (
        id INTEGER PRIMARY KEY,
        mentor_id INTEGER NOT NULL REFERENCES mentors(id) ON DELETE CASCADE,
        youtube_channel_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        indexed INTEGER NOT NULL DEFAULT 1 CHECK (indexed IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX channels_mentor_id ON channels(mentor_id);
    """,
]


# Blocking: call from a worker thread, never the event loop.
def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # autocommit=True: `with conn:` does not open a transaction, so writes go through transaction().
    conn = sqlite3.connect(path, autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    # IMMEDIATE takes the write lock up front; a deferred read that later writes
    # gets SQLITE_BUSY in WAL mode without waiting on busy_timeout.
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection) -> None:
    applied = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, script in enumerate(MIGRATIONS[applied:], start=applied + 1):
        # executescript handles multi-statement bodies (e.g. triggers); the explicit
        # transaction keeps each migration and its version bump atomic.
        try:
            conn.executescript(f"BEGIN IMMEDIATE; {script}; PRAGMA user_version = {number}; COMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


def initialize(path: Path) -> dict[str, object]:
    """Open and migrate the knowledge base and report its configuration.

    Raises if FTS5 or sqlite-vec is missing.
    """
    conn = connect(path)
    try:
        migrate(conn)
        conn.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(text)")
        conn.execute("DROP TABLE temp.fts5_probe")
        return {
            "path": str(path),
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            "foreign_keys": conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
            "busy_timeout_ms": conn.execute("PRAGMA busy_timeout").fetchone()[0],
            "sqlite_vec": conn.execute("SELECT vec_version()").fetchone()[0],
            "fts5": True,
        }
    finally:
        conn.close()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def run[T](self, work: Callable[[sqlite3.Connection], T]) -> T:
        """Run blocking database work on a worker thread with its own connection."""

        def call() -> T:
            conn = connect(self.path)
            try:
                return work(conn)
            finally:
                conn.close()

        return await asyncio.to_thread(call)
