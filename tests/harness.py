import asyncio
import sqlite3
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Literal

import httpx
from fastapi import FastAPI

from mentor import db
from mentor.config import Config
from mentor.fakes import FakeChannel, FakeTranscriptSource, FakeVideo
from mentor.ports import Chapter, Cue, Transcript, VideoDetails, VideoListing, VideoUnavailable


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """An in-process client for the app, with startup and shutdown run.

    httpx's ASGI transport does not send lifespan events on its own.
    """
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:7337") as client:
            yield client


type Json = dict[str, Any]


def fake_channel(transcripts: FakeTranscriptSource, youtube_channel_id: str) -> FakeChannel:
    [channel] = [c for c in transcripts.channels if c.info.channel_id == youtube_channel_id]
    return channel


async def add_mentor(client: httpx.AsyncClient, name: str, channel: str) -> Json:
    response = await client.post("/api/mentors", json={"name": name, "channel": channel})
    assert response.status_code == 201, response.text
    mentor: Json = response.json()
    return mentor


def fake_video(
    video_id: str,
    title: str,
    *,
    listed_duration: int | None = 600,
    duration: int = 600,
    published_on: date = date(2025, 3, 1),
    chapters: Sequence[Chapter] = (),
    source: Literal["youtube_auto", "youtube_manual"] = "youtube_manual",
    language: str = "en",
    failure: VideoUnavailable | None = None,
    before_fetch: Callable[[], None] | None = None,
    cues: Sequence[Cue] | None = None,
) -> FakeVideo:
    return FakeVideo(
        listing=VideoListing(video_id=video_id, title=title, duration_seconds=listed_duration),
        details=VideoDetails(
            video_id=video_id,
            title=title,
            published_on=published_on,
            duration_seconds=duration,
            description=f"About {title}",
            chapters=chapters,
        ),
        transcript=Transcript(
            source=source,
            language=language,
            cues=[Cue(start=0.0, end=4.0, text=f"Welcome to {title}"), Cue(start=4.0, end=9.5, text="Let's begin")]
            if cues is None
            else cues,
        ),
        failure=failure,
        before_fetch=before_fetch,
    )


async def start_sync(client: httpx.AsyncClient, channel_id: int) -> Json:
    response = await client.post(f"/api/channels/{channel_id}/syncs")
    assert response.status_code == 202, response.text
    sync: Json = response.json()
    return sync


async def wait_for_syncs(client: httpx.AsyncClient, timeout: float = 5.0) -> list[Json]:
    """Waits until no Sync is queued or running; returns every Sync, newest first."""
    async with asyncio.timeout(timeout):
        while True:
            syncs: list[Json] = (await client.get("/api/syncs")).json()
            if all(s["status"] not in ("queued", "running") for s in syncs):
                return syncs
            await asyncio.sleep(0.02)


def query(config: Config, sql: str, params: Sequence[object] = ()) -> list[sqlite3.Row]:
    """Reads the knowledge base directly, for state no API exposes yet."""
    conn = db.connect(config.database_path)
    try:
        rows: list[sqlite3.Row] = conn.execute(sql, params).fetchall()
        return rows
    finally:
        conn.close()


def row_counts(config: Config) -> dict[str, int]:
    """Rows per table, including the FTS5 index's own row table and the vector table."""
    tables = ("videos", "transcripts", "segments", "segments_fts_docsize", "segment_vectors")
    return {table: query(config, f"SELECT count(*) FROM {table}")[0][0] for table in tables}
