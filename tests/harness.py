import asyncio
import json
import socket
import sqlite3
import threading
from collections.abc import AsyncIterator, Callable, Mapping, MutableMapping, Sequence
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Literal

import httpx
import uvicorn
from fastapi import FastAPI
from mcp import Client

from seek import db
from seek.config import Config
from seek.fakes import FakeChannel, FakeTranscriptSource, FakeVideo
from seek.ports import Chapter, Cue, Storyboard, Transcript, VideoDetails, VideoListing, VideoUnavailable


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """An in-process client for the app, with startup and shutdown run.

    httpx's ASGI transport does not send lifespan events on its own.
    """
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:7337") as client:
            yield client


@asynccontextmanager
async def serving(app: FastAPI) -> AsyncIterator[str]:
    """Serves the app over HTTP on a free loopback port, for a browser; yields its base URL."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=1))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        raise RuntimeError("The server stopped while starting")
                    await asyncio.sleep(0.05)
            yield f"http://127.0.0.1:{sock.getsockname()[1]}/"
        finally:
            server.should_exit = True
            await task


def free_port() -> int:
    """A loopback port nothing is listening on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def mcp_client(app: FastAPI) -> Client:
    """An in-memory MCP client of the app's MCP server, to open inside `running(app)`."""
    return Client(app.state.mcp)


type Json = dict[str, Any]


class Gate:
    """Holds a fake (a fetch or a model load) on its worker thread until released.

    `seconds` bounds the hold so a test that never releases it still ends; a browser-driven test needs longer
    than an API one, which is the only reason to raise it.
    """

    def __init__(self, seconds: float = 5) -> None:
        self.entered = threading.Event()
        self.released = threading.Event()
        self._seconds = seconds

    def __call__(self) -> None:
        self.entered.set()
        self.released.wait(timeout=self._seconds)

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
async def event_stream(
    app: FastAPI, path: str = "/api/events", headers: Mapping[str, str] | None = None
) -> AsyncIterator[EventStream]:
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
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"127.0.0.1:7337"),
            *((name.lower().encode(), value.encode()) for name, value in (headers or {}).items()),
        ],
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


async def add_channel(client: httpx.AsyncClient, channel: str, name: str | None = None) -> Json:
    """Adds the Channel by URL, handle, or id, under the given name or else its display name."""
    response = await client.post("/api/channels", json={"channel": channel, "name": name})
    assert response.status_code == 201, response.text
    added: Json = response.json()
    return added


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
    storyboard: Storyboard | None = None,
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
            storyboard=storyboard,
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


def fake_storyboard(
    *, columns: int = 3, rows: int = 3, width: int = 320, height: int = 180, fps: float = 0.1, fragment_count: int = 2
) -> Storyboard:
    """A Video's storyboard as YouTube's geometry looks: a tile every 1/fps seconds, spread over numbered sheets."""
    return Storyboard(
        columns=columns,
        rows=rows,
        width=width,
        height=height,
        fps=fps,
        url_template="https://i.ytimg.com/sb/v/storyboard3_L3/M{index}.jpg?sqp=signed&sigh=signed",
        fragment_count=fragment_count,
    )


def said(*lines: str, every: float = 5.0) -> list[Cue]:
    """Cues for the lines, one after another, each lasting `every` seconds."""
    return [Cue(start=i * every, end=(i + 1) * every, text=line) for i, line in enumerate(lines)]


async def sync(client: httpx.AsyncClient, *channels: Json) -> None:
    """Syncs the Channels and checks each Sync finished."""
    for channel in channels:
        await start_sync(client, channel["id"])
    assert all(s["status"] == "done" for s in await wait_for_syncs(client))


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


# Web chat


def stream_events(response: httpx.Response) -> list[Json]:
    """The data events of a finished server-sent event stream."""
    assert response.headers["content-type"].startswith("text/event-stream"), response.text
    frames = response.text.split("\n\n")
    return [json.loads(frame.removeprefix("data: ")) for frame in frames if frame.startswith("data: ")]


async def add_group(client: httpx.AsyncClient, name: str, *channels: Json) -> Json:
    """A Group of the Channels; returned as listed with its members."""
    response = await client.post("/api/groups", json={"name": name})
    assert response.status_code == 201, response.text
    group: Json = response.json()
    if channels:
        members = {"channel_ids": [c["id"] for c in channels]}
        response = await client.put(f"/api/groups/{group['id']}/members", json=members)
        assert response.status_code == 200, response.text
        group = response.json()
    return group


async def woodworkers(client: httpx.AsyncClient, transcripts: FakeTranscriptSource) -> tuple[Json, Json, Json]:
    """The Channel Paul Wright in a Woodworking Group, and Rex Krueger outside it; both synced and saying something."""
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-wright", "Sharpening chisels", cues=said("Sharpen the chisel on a fine stone"))
    )
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-rex", "Sharpening knives", cues=said("Sharpen the knife on a coarse stone"))
    )
    wright = await add_channel(client, "@woodbywright", "Paul Wright")
    rex = await add_channel(client, "@rexkrueger")
    await sync(client, wright, rex)
    group = await add_group(client, "Woodworking", wright)
    return group, wright, rex


async def start_conversation(
    client: httpx.AsyncClient,
    group_id: int,
    model: str | None = None,
    workspace: str | None = None,
    web_access: bool = False,
) -> Json:
    response = await client.post(
        f"/api/groups/{group_id}/conversations",
        json={"model": model, "workspace": workspace, "web_access": web_access},
    )
    assert response.status_code == 201, response.text
    conversation: Json = response.json()
    return conversation


async def start_channel_conversation(
    client: httpx.AsyncClient,
    channel_id: int,
    model: str | None = None,
    workspace: str | None = None,
    web_access: bool = False,
) -> Json:
    response = await client.post(
        f"/api/channels/{channel_id}/conversations",
        json={"model": model, "workspace": workspace, "web_access": web_access},
    )
    assert response.status_code == 201, response.text
    conversation: Json = response.json()
    return conversation


async def new_group_conversation(client: httpx.AsyncClient, model: str | None = None) -> Json:
    """A Conversation with a new Woodworking Group of one Channel."""
    group = await add_group(client, "Woodworking", await add_channel(client, "@woodbywright"))
    return await start_conversation(client, group["id"], model)


async def send(client: httpx.AsyncClient, conversation_id: int, message: str) -> httpx.Response:
    return await client.post(f"/api/conversations/{conversation_id}/messages", json={"message": message})


def stored_messages(config: Config, conversation_id: int) -> list[tuple[str, str]]:
    rows = query(config, "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,))
    return [(row["role"], row["content"]) for row in rows]


def done_message(response: httpx.Response) -> Json:
    [done] = [event for event in stream_events(response) if event["type"] == "done"]
    message: Json = done["message"]
    return message
