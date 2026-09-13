import asyncio
import json
import sqlite3
import threading
from collections.abc import AsyncIterator, Callable, MutableMapping, Sequence
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


class Gate:
    """Holds a fake (a fetch or a model load) on its worker thread until released."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.released = threading.Event()

    def __call__(self) -> None:
        self.entered.set()
        self.released.wait(timeout=5)

    async def wait_entered(self) -> None:
        assert await asyncio.to_thread(self.entered.wait, 5)


class EventStream:
    """The server-sent events of one open `GET /api/events` request."""

    def __init__(self) -> None:
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        # Comment frames (keepalives) received so far.
        self.comments = 0
        self._chunks: asyncio.Queue[bytes] = asyncio.Queue()
        self._buffer = ""

    def _receive_start(self, status: int, headers: list[tuple[bytes, bytes]]) -> None:
        self.status = status
        self.headers = {name.decode().lower(): value.decode() for name, value in headers}

    async def _frame(self) -> str:
        while "\n\n" not in self._buffer:
            self._buffer += (await self._chunks.get()).decode()
        frame, self._buffer = self._buffer.split("\n\n", 1)
        return frame

    async def next_event(self) -> Json:
        """The next data event, counting any comments before it."""
        while True:
            frame = await self._frame()
            if frame.startswith(":"):
                self.comments += 1
                continue
            assert frame.startswith("data: "), frame
            event: Json = json.loads(frame.removeprefix("data: "))
            return event

    async def until(self, predicate: Callable[[Json], bool], timeout: float = 5.0) -> list[Json]:
        """Events up to and including the first that matches."""
        events: list[Json] = []
        async with asyncio.timeout(timeout):
            while not events or not predicate(events[-1]):
                events.append(await self.next_event())
        return events

    async def wait_for_comments(self, count: int, timeout: float = 5.0) -> None:
        """Waits until `count` more comments arrive; data events meanwhile are dropped."""
        target = self.comments + count
        async with asyncio.timeout(timeout):
            while self.comments < target:
                frame = await self._frame()
                if frame.startswith(":"):
                    self.comments += 1


@asynccontextmanager
async def event_stream(app: FastAPI) -> AsyncIterator[EventStream]:
    """Opens the app's event stream, inside `running(app)`, once its first event says it is subscribed.

    Drives the ASGI app directly: httpx's ASGI transport buffers a whole response, and this one never ends.
    """
    stream = EventStream()
    disconnected = asyncio.Event()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/events",
        "raw_path": b"/api/events",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1:7337")],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 7337),
    }

    async def receive() -> dict[str, Any]:
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            stream._receive_start(message["status"], message["headers"])
        elif message["type"] == "http.response.body":
            stream._chunks.put_nowait(message.get("body", b""))

    task = asyncio.create_task(app(scope, receive, send))
    try:
        assert await asyncio.wait_for(stream.next_event(), 5) == {"type": "ready"}
        yield stream
    finally:
        disconnected.set()
        await asyncio.wait_for(task, 5)


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
    date_listed: bool = True,
) -> FakeVideo:
    return FakeVideo(
        listing=VideoListing(
            video_id=video_id,
            title=title,
            duration_seconds=listed_duration,
            published_on=published_on if date_listed else None,
        ),
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


async def list_videos(client: httpx.AsyncClient, channel_id: int) -> dict[str, Json]:
    """The Channel's Videos by title."""
    response = await client.get(f"/api/channels/{channel_id}/videos")
    assert response.status_code == 200, response.text
    return {v["title"]: v for v in response.json()}


def fetched(transcripts: FakeTranscriptSource) -> list[str]:
    """YouTube video ids fetched so far, in order."""
    return [argument for method, argument in transcripts.calls if method == "fetch_video"]


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
