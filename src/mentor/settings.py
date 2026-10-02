"""Persistent user preferences, separate from operational configuration and credentials."""

import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool

from mentor.db import transaction

# Preferences stored as the words the settings CHECK allows rather than as SQLite's 0 and 1.
_STORED_BOOLEANS = {"thumbnails": ("on", "off")}


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    engine: Literal["api", "cli"] | None = None
    provider: Literal["anthropic"] = "anthropic"
    model: Literal["fast", "deep"] = "fast"
    # Whether search results and an answer's sources show frames of the moment they cite. Strict, as the ids
    # elsewhere are: "off" is a word a caller meant as a value, not as false.
    thumbnails: StrictBool = True


def read_settings(conn: sqlite3.Connection) -> Settings:
    stored = dict(conn.execute("SELECT key, value FROM settings"))
    return Settings.model_validate(
        {key: value == _STORED_BOOLEANS[key][0] if key in _STORED_BOOLEANS else value for key, value in stored.items()}
    )


def write_settings(conn: sqlite3.Connection, patch: Settings) -> Settings:
    """Update only supplied fields atomically; null engine restores automatic selection."""
    with transaction(conn):
        for key, value in patch.model_dump(exclude_unset=True).items():
            if value is None:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                words = _STORED_BOOLEANS.get(key)
                stored = value if words is None else words[0 if value else 1]
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, stored),
                )
        return read_settings(conn)
