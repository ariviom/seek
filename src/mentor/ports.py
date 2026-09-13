"""Interfaces to the external systems Mentor depends on. Adapter methods are blocking."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol


@dataclass(frozen=True)
class ChannelInfo:
    channel_id: str
    name: str


@dataclass(frozen=True)
class VideoListing:
    video_id: str
    title: str
    duration_seconds: int | None


@dataclass(frozen=True)
class Chapter:
    title: str
    start: float
    end: float


@dataclass(frozen=True)
class VideoDetails:
    video_id: str
    title: str
    published_on: date
    duration_seconds: int
    description: str
    chapters: Sequence[Chapter]


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    source: Literal["youtube_auto", "youtube_manual"]
    language: str
    cues: Sequence[Cue]


class TranscriptSource(Protocol):
    def resolve_channel(self, url_or_handle: str) -> ChannelInfo: ...

    def list_videos(self, channel_id: str) -> Sequence[VideoListing]: ...

    def fetch_video(self, video_id: str) -> tuple[VideoDetails, Transcript]: ...


class Embedder(Protocol):
    model_name: str
    dimension: int

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


@dataclass(frozen=True)
class ChatRequest:
    message: str
    system_prompt: str
    model: str | None
    resume_session_id: str | None


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool


@dataclass(frozen=True)
class ChatDone:
    session_id: str


@dataclass(frozen=True)
class ChatFailed:
    message: str


type ChatEvent = TextDelta | ToolCall | ToolResult | ChatDone | ChatFailed


class ChatEngine(Protocol):
    def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]: ...


@dataclass(frozen=True)
class Ports:
    transcripts: TranscriptSource
    embedder: Embedder
    reranker: Reranker
    chat: ChatEngine
