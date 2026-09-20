"""Interfaces to the external systems Mentor depends on.

TranscriptSource, Embedder, and Reranker methods are blocking; ChatEngine streams asynchronously.
"""

from collections.abc import AsyncGenerator, Collection, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Protocol

from mcp.server.mcpserver import MCPServer


@dataclass(frozen=True)
class ChannelInfo:
    channel_id: str
    name: str


@dataclass(frozen=True)
class VideoListing:
    video_id: str
    title: str
    duration_seconds: int | None
    published_on: date | None


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


# Adapters raise only these for expected failures; messages are shown to the user as-is.
class ChannelNotFound(Exception):
    """The URL, handle, or id does not identify a YouTube channel."""


class PlaylistNotFound(Exception):
    """The id does not identify a YouTube playlist."""


class SourceUnavailable(Exception):
    """The transcript source cannot be reached or is not usable right now."""


class SecretsUnavailable(Exception):
    """The credential store cannot be used. Messages never contain credential or backend exception details."""


@dataclass(frozen=True)
class SecretStoreStatus:
    store: Literal["keychain", "file"]
    fallback_reason: str | None = None


class Secrets(Protocol):
    """Blocking credential access. Raises SecretsUnavailable if persistence or retrieval is impossible."""

    @property
    def status(self) -> SecretStoreStatus: ...

    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class ModelUnavailable(Exception):
    """The embedding or reranking model cannot be used right now."""


class GpuOutOfMemory(ModelUnavailable):
    """One call didn't fit beside whatever else holds the GPU. The model itself is fine, so a Sync fails just the
    Video it was embedding and carries on; a later retry embeds it once memory is free."""


class VideoUnavailable(Exception):
    """One Video cannot be ingested: members-only, age-restricted, live or upcoming, no captions, not in English.

    Transient failures (e.g. upcoming) may succeed on a later Sync. `language` names the Video's caption
    language when that is the reason; `details` carries whatever metadata was fetched before failing. `throttled`
    marks a refusal by the source rather than anything about the Video: one is retried later like any transient
    failure, but a run of them means the source is blocking this machine and the Sync should stop.
    """

    def __init__(
        self,
        reason: str,
        *,
        permanent: bool,
        language: str | None = None,
        details: VideoDetails | None = None,
        throttled: bool = False,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.permanent = permanent
        self.language = language
        self.details = details
        self.throttled = throttled


class TranscriptSource(Protocol):
    def resolve_channel(self, url_or_handle: str) -> ChannelInfo:
        """Accepts a channel URL, an @handle, or a bare channel id."""
        ...

    def list_videos(self, channel_id: str, known_ids: Collection[str] = ()) -> Sequence[VideoListing]:
        """A cheap flat listing of the channel's videos and streams tabs, each newest first, which excludes Shorts.

        The listing may stop once a page holds only `known_ids`, so pass them only when the older ones are known to
        be complete. Raises ChannelNotFound for an unknown channel id.
        """
        ...

    def list_playlist(self, playlist_id: str) -> Sequence[str]:
        """The video ids in a playlist, which may include other channels' videos.

        Raises PlaylistNotFound for an unknown playlist id.
        """
        ...

    def fetch_video(self, video_id: str) -> tuple[VideoDetails, Transcript]:
        """Full metadata and English captions. Raises VideoUnavailable otherwise, including for an unknown id."""
        ...


type ModelState = Literal["waiting", "downloading", "loading", "ready", "failed"]


@dataclass(frozen=True)
class ModelStatus:
    name: str
    state: ModelState
    # Progress while downloading; the total is None until known.
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    # Why loading failed, for the user.
    error: str | None = None
    device: Literal["cuda", "mps", "cpu"] | None = None
    precision: Literal["bfloat16", "float32"] | None = None
    fallback_reason: str | None = None


class Model(Protocol):
    def load(self) -> None:
        """Downloads the model if needed and loads it. Never raises: the outcome shows in status()."""
        ...

    def status(self) -> ModelStatus: ...


class Embedder(Model, Protocol):
    """Raises ModelUnavailable when the model can't be used, including until it has loaded.

    model_name and dimension are known before loading.
    """

    model_name: str
    dimension: int

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class Reranker(Model, Protocol):
    """Raises ModelUnavailable when the model can't be used, including until it has loaded."""

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Raw relevance logits, one per passage; search squashes them with a sigmoid, so don't return probabilities."""
        ...


@dataclass(frozen=True)
class PastMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class ChatRequest:
    message: str
    system_prompt: str
    # None uses the Claude CLI's default model.
    model: str | None
    resume_session_id: str | None
    # The Conversation's earlier messages, oldest first. The engine replays them when there is no session to resume.
    history: Sequence[PastMessage]
    # Optional read-only resources selected when the Conversation was created.
    workspace: Path | None
    web_access: bool
    # The only tools the model may use: served in-process under the name "mentor", already bound to one Group or Channel.
    tools: MCPServer
    tool_names: Sequence[str]


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
    # The session to resume no longer exists; the turn can be retried without it, replaying the history.
    session_lost: bool = False


type ChatEvent = TextDelta | ToolCall | ToolResult | ChatDone | ChatFailed


# api_key: logged in, but through an API key that would be billed instead of the subscription.
type ChatEngineState = Literal["ready", "missing", "logged_out", "api_key", "unknown"]


@dataclass(frozen=True)
class ChatEngineStatus:
    state: ChatEngineState
    # The Claude CLI checked, if one was found.
    cli_path: str | None
    # What to do about a state other than ready, for the user.
    message: str | None = None


class ChatEngine(Protocol):
    def stream(self, request: ChatRequest) -> AsyncGenerator[ChatEvent]: ...

    async def status(self) -> ChatEngineStatus:
        """Whether chat can run: the Claude CLI is present and logged in. Never raises."""
        ...
