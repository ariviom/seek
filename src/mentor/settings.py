"""Persistent user preferences, separate from operational configuration and credentials."""

import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict

from mentor.db import transaction


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    engine: Literal["api", "cli"] | None = None
    provider: Literal["anthropic"] = "anthropic"
    model: Literal["fast", "deep"] = "fast"


def read_settings(conn: sqlite3.Connection) -> Settings:
    return Settings.model_validate(dict(conn.execute("SELECT key, value FROM settings")))


def write_settings(conn: sqlite3.Connection, patch: Settings) -> Settings:
    """Update only supplied fields atomically; null engine restores automatic selection."""
    with transaction(conn):
        for key, value in patch.model_dump(exclude_unset=True).items():
            if value is None:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value),
                )
        return read_settings(conn)
