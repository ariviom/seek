"""Deterministic stand-ins for the ports, for tests."""

import hashlib
import math
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from mentor.ports import (
    ChannelInfo,
    ChannelNotFound,
    ChatEvent,
    ChatRequest,
    Transcript,
    VideoDetails,
    VideoListing,
)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class FakeVideo:
    listing: VideoListing
    details: VideoDetails
    transcript: Transcript


@dataclass
class FakeChannel:
    info: ChannelInfo
    handles: Sequence[str]
    videos: list[FakeVideo] = field(default_factory=list)


@dataclass
class FakeTranscriptSource:
    channels: list[FakeChannel] = field(default_factory=list)

    def resolve_channel(self, url_or_handle: str) -> ChannelInfo:
        for channel in self.channels:
            if url_or_handle in channel.handles or url_or_handle == channel.info.channel_id:
                return channel.info
        raise ChannelNotFound(url_or_handle)

    def list_videos(self, channel_id: str) -> Sequence[VideoListing]:
        return [v.listing for c in self.channels if c.info.channel_id == channel_id for v in c.videos]

    def fetch_video(self, video_id: str) -> tuple[VideoDetails, Transcript]:
        for channel in self.channels:
            for video in channel.videos:
                if video.listing.video_id == video_id:
                    return video.details, video.transcript
        raise LookupError(video_id)


@dataclass
class FakeEmbedder:
    """Bag of hashed words, L2-normalised: texts sharing words have similar vectors."""

    dimension: int = 64
    model_name: str = "fake-embedder"

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimension] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
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


