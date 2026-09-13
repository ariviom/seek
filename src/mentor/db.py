import asyncio
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

BUSY_TIMEOUT_MS = 5000

# Applied in order; PRAGMA user_version records how many have run. Never edit a shipped entry.
# Migrations run with foreign keys ON inside a transaction, where they cannot be switched off:
# keep them additive, because DROP TABLE on a parent would cascade-delete its children.
MIGRATIONS = [
    """
    CREATE TABLE mentors (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE
    );
    CREATE TABLE channels (
        id INTEGER PRIMARY KEY,
        mentor_id INTEGER NOT NULL REFERENCES mentors(id) ON DELETE CASCADE,
        youtube_channel_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        indexed INTEGER NOT NULL DEFAULT 1 CHECK (indexed IN (0, 1))
    );
    CREATE INDEX channels_mentor_id ON channels(mentor_id);
    """,
    """
    -- AUTOINCREMENT: a deleted Group's id is never reused, so records that outlive it can't
    -- attach to a new Group.
    CREATE TABLE mentor_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE
    );
    CREATE TABLE mentor_group_members (
        group_id INTEGER NOT NULL REFERENCES mentor_groups(id) ON DELETE CASCADE,
        mentor_id INTEGER NOT NULL REFERENCES mentors(id) ON DELETE CASCADE,
        PRIMARY KEY (group_id, mentor_id)
    ) WITHOUT ROWID;
    CREATE INDEX mentor_group_members_mentor_id ON mentor_group_members(mentor_id);
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
        # SQLite may already have rolled back (e.g. disk full); don't mask the original error.
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection) -> None:
    # The version is read under the write lock so two processes starting together don't both apply.
    with transaction(conn):
        applied = conn.execute("PRAGMA user_version").fetchone()[0]
        if applied > len(MIGRATIONS):
            raise RuntimeError(
                f"The knowledge base was created by a newer mentor (schema {applied}, this build knows "
                f"{len(MIGRATIONS)}); upgrade mentor"
            )
        for number, script in enumerate(MIGRATIONS[applied:], start=applied + 1):
            # executescript handles multi-statement bodies such as triggers; in autocommit mode
            # it does not commit the surrounding transaction.
            conn.executescript(f"{script}; PRAGMA user_version = {number};")


def initialize(path: Path) -> dict[str, object]:
    """Open and migrate the knowledge base; raises if FTS5 or sqlite-vec is missing."""
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
        """Run blocking database work on a worker thread with its own connection.

        A fresh connection per call is cheap enough for one user and avoids sharing across threads.
        """

        def call() -> T:
            conn = connect(self.path)
            try:
                return work(conn)
            finally:
                conn.close()

        return await asyncio.to_thread(call)
