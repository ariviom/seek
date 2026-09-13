import sqlite3
from pathlib import Path

import sqlite_vec

BUSY_TIMEOUT_MS = 5000


def connect(path: Path) -> sqlite3.Connection:
    """Open the knowledge base with the settings every connection needs.

    Blocking: call from a worker thread, never the event loop.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, autocommit=True, check_same_thread=False)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def describe(path: Path) -> dict[str, object]:
    conn = connect(path)
    try:
        try:
            conn.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(text)")
            conn.execute("DROP TABLE temp.fts5_probe")
            fts5 = True
        except sqlite3.OperationalError:
            fts5 = False
        return {
            "path": str(path),
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            "foreign_keys": conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
            "busy_timeout_ms": conn.execute("PRAGMA busy_timeout").fetchone()[0],
            "sqlite_vec": conn.execute("SELECT vec_version()").fetchone()[0],
            "fts5": fts5,
        }
    finally:
        conn.close()
