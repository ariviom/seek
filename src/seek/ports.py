"""Interfaces to the external systems Seek depends on.

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
    # The Channel's YouTube avatar, when YouTube offered one.
    avatar_url: str | None = None


@dataclass(frozen=True)
class VideoListing:
    video_id: str
    title: str
    duration_seconds: int | None
    published_on: date | None


@dataclass(frozen=True)
class ChannelListing:
    videos: Sequence[VideoListing]
    # The same avatar ChannelInfo carries, from the same extraction, when it offered one.
    avatar_url: str | None = None


@dataclass(frozen=True)
class PlaylistEntry:
    video_id: str
    title: str
    duration_seconds: int | None
    # The creator who made the Video: their YouTube channel id and display name.
    channel_id: str
    channel_name: str


@dataclass(frozen=True)
class PlaylistListing:
    title: str
    # In the playlist's order.
    entries: Sequence[PlaylistEntry]


@dataclass(frozen=True)
class PlaylistInfo:
    playlist_id: str
    title: str
    # The entries a listing would return.
    video_count: int


@dataclass(frozen=True)
class Chapter:
    title: str
    start: float
    end: float


@dataclass(frozen=True)
class Storyboard:
    """The geometry of a Video's scrubber storyboard: tiles of one frame each, laid out in a grid on numbered sheets.

    Every sheet URL carries the same signature, so url_template, with {index} where the sheet number goes, stands
    for all fragment_count of them. The signature expires; the geometry does not.
    """

    columns: int
    rows: int
    # One tile's pixels.
    width: int
    height: int
    # Frames per second of video: one tile covers 1/fps seconds, about ten.
    fps: float
    url_template: str
    fragment_count: int


@dataclass(frozen=True)
class VideoDetails:
    video_id: str
    title: str
    published_on: date
    duration_seconds: int
    description: str
    chapters: Sequence[Chapter]
    # The scrubber storyboard the same extraction offered, when it offered a usable one.
    storyboard: Storyboard | None = None


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
    """The URL or id does not identify a YouTube playlist this machine may list."""


# YouTube answers the same for a playlist that is missing and one it won't show, so every adapter says both.
PLAYLIST_MISSING_OR_PRIVATE = (
    "This playlist doesn't exist or is private. For your own private playlist, configure youtube_cookie_file or "
    "youtube_cookies_from_browser signed in as you, or set it to unlisted."
)


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
    def resolve_channel(self, url_or_handle: str, paced: bool = False) -> ChannelInfo:
        """Accepts a channel URL, an @handle, or a bare channel id.

        Answers promptly unless `paced`, which a Sync asks for so the call waits its turn among the Sync's others.
        """
        ...

    def list_videos(self, channel_id: str, known_ids: Collection[str] = ()) -> ChannelListing:
        """A cheap flat listing of the channel's videos and streams tabs, each newest first, which excludes Shorts,
        with the channel's avatar.

        The listing may stop once a page holds only `known_ids`, so pass them only when the older ones are known to
        be complete. Raises ChannelNotFound for an unknown channel id.
        """
        ...

    def resolve_playlist(self, url_or_id: str) -> PlaylistInfo:
        """Accepts a playlist URL, a watch or share URL carrying a playlist, or a bare playlist id.

        Answers promptly, as resolve_channel does, rather than waiting its turn among a Sync's calls. Raises
        PlaylistNotFound for anything else, and for a playlist that is missing or private.
        """
        ...

    def list_playlist(self, playlist_id: str) -> PlaylistListing:
        """The playlist's title and its videos in order, whoever made them.

        Entries without a creator (private or deleted videos) are left out. Raises PlaylistNotFound for a playlist
        that is missing or private.
        """
        ...

    def fetch_video(self, video_id: str) -> tuple[VideoDetails, Transcript]:
        """Full metadata and English captions. Raises VideoUnavailable otherwise, including for an unknown id."""
        ...

    def fetch_storyboard(self, video_id: str) -> Storyboard | None:
        """The Video's scrubber storyboard geometry alone, for Videos ingested before it was kept.

        None when the source offers none this code can use. Raises VideoUnavailable for one Video that cannot be
        read, and SourceUnavailable when the source itself is refusing.
        """
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
    # The only tools the model may use: served in-process under the name "seek", already bound to one Group, Channel, or Playlist.
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
class TokenUsage:
    """The three counts a provider reports that Seek records: uncached input, output, and cache reads.

    Deliberately not everything that is billed. Writing the cache is charged separately and is not counted
    here, so a total built from these is a floor, which is why nothing presents one as a bill.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
        )


@dataclass(frozen=True)
class UsageReported:
    """One provider request's usage, emitted as soon as it is known so a later failure cannot lose it.

    An engine emits this at most once per provider request; a turn's usage is their sum.
    """

    usage: TokenUsage


@dataclass(frozen=True)
class ChatDone:
    # The session to resume next turn, for an engine that keeps one; None where the history is replayed instead.
    session_id: str | None = None


@dataclass(frozen=True)
class ChatFailed:
    message: str
    # The session to resume no longer exists; the turn can be retried without it, replaying the history.
    session_lost: bool = False


type ChatEvent = TextDelta | ToolCall | ToolResult | UsageReported | ChatDone | ChatFailed


type EngineName = Literal["api", "cli"]

# Claude CLI: api_key means logged in, but through an API key that would be billed instead of the subscription.
# Anthropic API: no_key means none is stored, invalid_key that the stored one was rejected.
type ChatEngineState = Literal[
    "ready", "missing", "logged_out", "api_key", "no_key", "invalid_key", "unknown"
]


@dataclass(frozen=True)
class ChatEngineStatus:
    # Which engine this describes, so Health can report both.
    engine: EngineName
    state: ChatEngineState
    # The Claude CLI checked, if one was found; always None for the API engine.
    cli_path: str | None = None
    # What to do about a state other than ready, for the user.
    message: str | None = None


class ChatEngine(Protocol):
    def stream(self, request: ChatRequest) -> AsyncGenerator[ChatEvent]: ...

    async def status(self) -> ChatEngineStatus:
        """Whether this engine can answer a turn right now. Never raises, and never calls the provider."""
        ...
