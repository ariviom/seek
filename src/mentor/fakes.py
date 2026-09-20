"""Deterministic stand-ins for the ports, for tests."""

import hashlib
import math
import re
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Collection, Sequence
from dataclasses import dataclass, field

from mentor.ports import (
    ChannelInfo,
    ChannelNotFound,
    ChatDone,
    ChatEngineStatus,
    ChatEvent,
    ChatRequest,
    EngineName,
    ModelStatus,
    ModelUnavailable,
    PlaylistNotFound,
    SecretStoreStatus,
    SourceUnavailable,
    TextDelta,
    Transcript,
    VideoDetails,
    VideoListing,
    VideoUnavailable,
)


@dataclass
class FakeSecrets:
    values: dict[str, str] = field(default_factory=dict, repr=False)
    status: SecretStoreStatus = field(default_factory=lambda: SecretStoreStatus("keychain"))

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class FakeVideo:
    listing: VideoListing
    details: VideoDetails
    transcript: Transcript
    # Raised by fetch_video instead of returning the transcript.
    failure: VideoUnavailable | None = None
    # Called on the fetching thread before anything else, e.g. to hold a Sync mid-run.
    before_fetch: Callable[[], None] | None = None


@dataclass
class FakeChannel:
    info: ChannelInfo
    handles: Sequence[str]
    videos: list[FakeVideo] = field(default_factory=list)
    # The streams tab: past livestreams, listed after the videos tab.
    streams: list[FakeVideo] = field(default_factory=list)

    @property
    def all_videos(self) -> list[FakeVideo]:
        return [*self.videos, *self.streams]


@dataclass
class FakeTranscriptSource:
    channels: list[FakeChannel] = field(default_factory=list)
    # Video ids by playlist id.
    playlists: dict[str, list[str]] = field(default_factory=dict)
    # When set, every call raises SourceUnavailable with this message.
    unavailable: str | None = None
    # Every call as (method, argument), in order.
    calls: list[tuple[str, str]] = field(default_factory=list)
    # The known ids each list_videos call was given, in order. The fake lists everything regardless.
    listings_known: list[frozenset[str]] = field(default_factory=list)

    def _call(self, method: str, argument: str) -> None:
        self.calls.append((method, argument))
        if self.unavailable is not None:
            raise SourceUnavailable(self.unavailable)

    def resolve_channel(self, url_or_handle: str) -> ChannelInfo:
        self._call("resolve_channel", url_or_handle)
        for channel in self.channels:
            if url_or_handle in channel.handles or url_or_handle == channel.info.channel_id:
                return channel.info
        raise ChannelNotFound(f"No YouTube channel found for {url_or_handle}")

    def list_videos(self, channel_id: str, known_ids: Collection[str] = ()) -> Sequence[VideoListing]:
        self._call("list_videos", channel_id)
        self.listings_known.append(frozenset(known_ids))
        for channel in self.channels:
            if channel.info.channel_id == channel_id:
                return [v.listing for v in channel.all_videos]
        raise ChannelNotFound(f"No YouTube channel found for {channel_id}")

    def list_playlist(self, playlist_id: str) -> Sequence[str]:
        self._call("list_playlist", playlist_id)
        if playlist_id not in self.playlists:
            raise PlaylistNotFound(f"No YouTube playlist found for {playlist_id}")
        return self.playlists[playlist_id]

    def fetch_video(self, video_id: str) -> tuple[VideoDetails, Transcript]:
        for channel in self.channels:
            for video in channel.all_videos:
                if video.listing.video_id == video_id:
                    if video.before_fetch is not None:
                        video.before_fetch()
                    self._call("fetch_video", video_id)
                    if video.failure is not None:
                        raise video.failure
                    return video.details, video.transcript
        self._call("fetch_video", video_id)
        raise VideoUnavailable(f"Video {video_id} not found", permanent=True)


@dataclass
class _FakeModel:
    """Loads instantly unless told otherwise. Like the real models, calls raise ModelUnavailable until loaded."""

    model_name: str = "fake-model"
    # When set, every call raises ModelUnavailable with this message, as if the GPU ran out of memory.
    unavailable: str | None = None
    # Called on the loading thread once loading has started, e.g. to hold loading mid-way.
    before_load: Callable[[], None] | None = None
    # What status() reports while loading, e.g. download progress.
    status_while_loading: ModelStatus | None = None
    # When set, loading fails with this message.
    load_error: str | None = None
    _status: ModelStatus | None = field(default=None, init=False, repr=False)

    def load(self) -> None:
        self._status = self.status_while_loading or ModelStatus(self.model_name, "loading")
        if self.before_load is not None:
            self.before_load()
        if self.load_error is None:
            self._status = ModelStatus(self.model_name, "ready")
        else:
            self._status = ModelStatus(self.model_name, "failed", error=self.load_error)

    def status(self) -> ModelStatus:
        return self._status or ModelStatus(self.model_name, "waiting")

    def _check(self) -> None:
        status = self.status()
        if status.state != "ready":
            raise ModelUnavailable(status.error or f"The model {self.model_name} is still loading; try again shortly")
        if self.unavailable is not None:
            raise ModelUnavailable(self.unavailable)


@dataclass
class FakeEmbedder(_FakeModel):
    """Bag of hashed words, L2-normalised: texts sharing words have similar vectors."""

    dimension: int = 64
    model_name: str = "fake-embedder"
    # Every passage embedded, in order.
    passages: list[str] = field(default_factory=list)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimension] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        self._check()
        self.passages += texts
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self._check()
        return self._embed(text)


@dataclass
class FakeReranker(_FakeModel):
    """Logit-like scores from -5 to 5: the share of distinct query words present in the passage, scaled."""

    model_name: str = "fake-reranker"
    # Every call as (query, passages), in order.
    calls: list[tuple[str, list[str]]] = field(default_factory=list)

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self._check()
        self.calls.append((query, list(passages)))
        wanted = set(_tokens(query))
        if not wanted:
            return [-5.0 for _ in passages]
        return [10 * len(wanted & set(_tokens(p))) / len(wanted) - 5 for p in passages]


@dataclass
class FakeChatEngine:
    """Streams the script for every turn, or, when `respond` is set, whatever it yields for the request.

    `engine` decides which half of the pair this stands in for, and what a ready status looks like: the
    Claude CLI reports the path it found, the API engine never has one.
    """

    engine: EngineName = "cli"
    script: list[ChatEvent] | None = None
    # E.g. calls the request's tools as a model would before answering.
    respond: Callable[[ChatRequest], AsyncIterator[ChatEvent]] | None = None
    # Every request, in order.
    requests: list[ChatRequest] = field(default_factory=list)
    # What status() reports; ready for this engine unless set.
    engine_status: ChatEngineStatus | None = None

    def __post_init__(self) -> None:
        if self.script is None:
            session = "session-1" if self.engine == "cli" else None
            self.script = [TextDelta("Nothing to say."), ChatDone(session)]
        if self.engine_status is None:
            path = "/usr/bin/claude" if self.engine == "cli" else None
            self.engine_status = ChatEngineStatus(self.engine, "ready", path)

    async def status(self) -> ChatEngineStatus:
        assert self.engine_status is not None
        return self.engine_status

    async def stream(self, request: ChatRequest) -> AsyncGenerator[ChatEvent]:
        self.requests.append(request)
        if self.respond:
            async for event in self.respond(request):
                yield event
        else:
            for event in self.script or []:
                yield event
