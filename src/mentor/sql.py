"""A read-only SQL escape hatch over the knowledge base, for questions no tool answers."""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec

from mentor.db import BUSY_TIMEOUT_MS

ROW_LIMIT = 200
# Results go into a model's context, so long text is cut short and rows stop once the result is this large.
TEXT_LIMIT = 1000
RESULT_CHARACTER_LIMIT = 50_000
# The longest string or blob a query may build.
VALUE_BYTE_LIMIT = 1_000_000
# The progress handler runs after this many virtual machine instructions.
_PROGRESS_INSTRUCTIONS = 1000
# Read-only pragmas a SELECT may use, e.g. pragma_table_info('videos'). FTS5 reads data_version itself.
_READ_PRAGMAS = {"data_version", "table_info", "table_xinfo", "index_list", "index_info", "index_xinfo", "foreign_key_list"}

type Value = int | float | str | None


class QueryRejected(Exception):
    """The query was refused or failed; the message is for whoever wrote it."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Value]]
    # More rows matched than came back.
    truncated: bool


def _value(value: object) -> Value:
    if isinstance(value, bytes):
        return f"<blob, {len(value)} bytes>"
    if isinstance(value, str) and len(value) > TEXT_LIMIT:
        return f"{value[:TEXT_LIMIT]}… ({len(value) - TEXT_LIMIT} more characters)"
    assert value is None or isinstance(value, int | float | str)
    return value


# Blocking: call from a worker thread, never the event loop.
def run_query(path: Path, query: str, time_limit_seconds: float) -> QueryResult:
    """Runs one SELECT on a read-only connection that also refuses writes, extensions, and anything slow.

    Four guards: the file is opened read-only, query_only is on, extension loading is off once sqlite-vec is loaded,
    and an authorizer allows only reads. A progress handler interrupts the query at the time limit.
    """
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, autocommit=True)
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA query_only = ON")
        # The progress handler can't interrupt a single huge allocation, such as randomblob(900000000).
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, VALUE_BYTE_LIMIT)
        # sqlite-vec, so the vector table can be read.
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        refusal: str | None = None
        selected = False

        # An allowlist: anything unlisted, such as a write, ATTACH, or a transaction, is denied.
        def authorize(action: int, first: str | None, second: str | None, database: str | None, source: str | None) -> int:
            nonlocal refusal, selected
            if action == sqlite3.SQLITE_SELECT:
                selected = True
                return sqlite3.SQLITE_OK
            if action in (sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE):
                return sqlite3.SQLITE_OK
            # A function's name is the second argument; a pragma's is the first.
            if action == sqlite3.SQLITE_FUNCTION:
                if second != "load_extension":
                    return sqlite3.SQLITE_OK
                refusal = "load_extension is not allowed"
            elif action == sqlite3.SQLITE_PRAGMA:
                if first in _READ_PRAGMAS:
                    return sqlite3.SQLITE_OK
                refusal = f"Only reads are allowed; PRAGMA {first} is not"
            else:
                refusal = "Only reads are allowed: send a single SELECT"
            return sqlite3.SQLITE_DENY

        deadline = time.monotonic() + time_limit_seconds
        conn.set_authorizer(authorize)
        # A true result interrupts the query.
        conn.set_progress_handler(lambda: time.monotonic() > deadline, _PROGRESS_INSTRUCTIONS)
        rows: list[list[Value]] = []
        truncated = False
        characters = 0
        try:
            cursor = conn.execute(query)
            for row in cursor:
                if len(rows) == ROW_LIMIT or characters > RESULT_CHARACTER_LIMIT:
                    truncated = True
                    break
                rows.append([_value(value) for value in row])
                characters += sum(len(str(value)) for value in rows[-1])
        except sqlite3.ProgrammingError as e:
            if "one statement" in str(e):
                raise QueryRejected("Send one statement at a time") from e
            raise QueryRejected(str(e)) from e
        except sqlite3.Error as e:
            if refusal is not None:
                raise QueryRejected(refusal) from e
            if time.monotonic() > deadline:
                raise QueryRejected(f"The query ran past the {time_limit_seconds:g} second time limit") from e
            raise QueryRejected(str(e)) from e
        # Statements such as REINDEX ask the authorizer nothing; the read-only guards stop them writing.
        if not selected or cursor.description is None:
            raise QueryRejected("Only reads are allowed: send a single SELECT")
        return QueryResult(columns=[column[0] for column in cursor.description], rows=rows, truncated=truncated)
    finally:
        conn.close()
