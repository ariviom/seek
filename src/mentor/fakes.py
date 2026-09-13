"""Deterministic stand-ins for the ports, for tests."""

import hashlib
import math
import re
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field

from mentor.ports import (
    ChannelInfo,
    ChannelNotFound,
    ChatEvent,
    ChatRequest,
    ModelUnavailable,
    PlaylistNotFound,
    SourceUnavailable,
    Transcript,
    VideoDetails,
    VideoListing,
    VideoUnavailable,
)


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


@dataclass
class FakeTranscriptSource:
    channels: list[FakeChannel] = field(default_factory=list)
    # Video ids by playlist id.
    playlists: dict[str, list[str]] = field(default_factory=dict)
    # When set, every call raises SourceUnavailable with this message.
    unavailable: str | None = None
    # Every call as (method, argument), in order.
    calls: list[tuple[str, str]] = field(default_factory=list)

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

    def list_videos(self, channel_id: str) -> Sequence[VideoListing]:
        self._call("list_videos", channel_id)
        for channel in self.channels:
            if channel.info.channel_id == channel_id:
                return [v.listing for v in channel.videos]
        raise ChannelNotFound(f"No YouTube channel found for {channel_id}")

    def list_playlist(self, playlist_id: str) -> Sequence[str]:
        self._call("list_playlist", playlist_id)
        if playlist_id not in self.playlists:
            raise PlaylistNotFound(f"No YouTube playlist found for {playlist_id}")
        return self.playlists[playlist_id]

    def fetch_video(self, video_id: str) -> tuple[VideoDetails, Transcript]:
        for channel in self.channels:
            for video in channel.videos:
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
class FakeEmbedder:
    """Bag of hashed words, L2-normalised: texts sharing words have similar vectors."""

    dimension: int = 64
    model_name: str = "fake-embedder"
    # When set, every call raises ModelUnavailable with this message.
    unavailable: str | None = None
    # Every passage embedded, in order.
    passages: list[str] = field(default_factory=list)

    def _check(self) -> None:
        if self.unavailable is not None:
            raise ModelUnavailable(self.unavailable)

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


class FakeReranker:
    """Fraction of distinct query words present in the passage."""

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        wanted = set(_tokens(query))
        if not wanted:
            return [0.0 for _ in passages]
        return [len(wanted & set(_tokens(p))) / len(wanted) for p in passages]


@dataclass
class FakeChatEngine:
    script: list[ChatEvent] = field(default_factory=list)
    requests: list[ChatRequest] = field(default_factory=list)

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        self.requests.append(request)
        for event in self.script:
            yield event
