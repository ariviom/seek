"""Frozen-corpus runner inputs. This module never starts the application or Sync."""

import hashlib
import shutil
import sqlite3
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from seek.ranking import Recency

from collections.abc import Mapping
from pathlib import Path

# Search still reads the frozen schema directly. Additive application migrations (such as preferences)
# do not require changing the corpus; accept only a schema explicitly supported by this runner.
RETRIEVAL_SCHEMA_VERSION = 11


def configured_snapshot(env: Mapping[str, str]) -> Path | None:
    value = env.get("SEEK_RETRIEVAL_SNAPSHOT")
    if value is None:
        return None
    if not value or not (path := Path(value).expanduser()).is_file():
        raise ValueError("SEEK_RETRIEVAL_SNAPSHOT must name the frozen SQLite snapshot file")
    return path.resolve()




class Snapshot(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: int


class Model(BaseModel):
    model: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")


class Embedding(Model):
    dimension: int = Field(gt=0)


class Manifest(BaseModel):
    snapshot: Snapshot
    embedding: Embedding
    reranker: Model


class Retrieval(BaseModel):
    temperature: float = Field(gt=0)
    recency: dict[Literal["off", "gentle", "strong"], Recency | None]


class Question(BaseModel):
    id: str
    query: str = Field(min_length=1)
    group: str = Field(min_length=1)
    limit: int = Field(gt=0)
    prefer_recent: Literal["off", "gentle", "strong"]
    required_video_ids: list[str] = Field(min_length=1)
    pass_condition: str = Field(min_length=1)


class Questions(BaseModel):
    reference_date: date
    retrieval: Retrieval
    questions: list[Question] = Field(min_length=1)


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_snapshot(source: Path, destination: Path, manifest: Manifest) -> Path:
    """Validate without opening for writes, then derive a disposable working copy."""
    if source.resolve() == destination.resolve():
        raise ValueError("The working copy must be separate from the frozen snapshot")
    if checksum(source) != manifest.snapshot.sha256:
        raise ValueError("Snapshot checksum differs from the manifest; transfer the exact frozen snapshot")
    if any(Path(str(source) + suffix).exists() for suffix in ("-wal", "-shm")):
        raise ValueError("Snapshot has SQLite sidecars; use the standalone consistent backup, not a live database")
    try:
        conn = sqlite3.connect(source.as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version != manifest.snapshot.schema_version or version != RETRIEVAL_SCHEMA_VERSION:
                raise ValueError("Snapshot schema differs from the manifest or supported retrieval schema; do not migrate the baseline")
            model = conn.execute("SELECT name, dimension FROM embedding_model").fetchall()
            if model != [(manifest.embedding.model, manifest.embedding.dimension)]:
                raise ValueError("Snapshot embedding model/dimension differs from the manifest")
        finally:
            conn.close()
    except sqlite3.Error as error:
        raise ValueError(f"Invalid SQLite snapshot: {error}") from error
    shutil.copyfile(source, destination)
    if checksum(destination) != manifest.snapshot.sha256:
        destination.unlink()
        raise ValueError("Snapshot changed while copying; restore the immutable frozen snapshot")
    return destination
