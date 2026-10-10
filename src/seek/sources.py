"""The sources behind search results: a Segment's surrounding Transcript and a Video's details.

Functions are blocking; run them through Database.run.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date

from seek.errors import NotFound
from seek.ports import Chapter, Cue
from seek.scope import CHANNEL_IN_SCOPE, Scope, scope_params

DEFAULT_EXPAND_SECONDS = 60
MAX_EXPAND_SECONDS = 600


@dataclass(frozen=True)
class TimedLine:
    start_seconds: float
    text: str


@dataclass(frozen=True)
class Expansion:
    segment_id: int
    # The Segment's own span; the lines run from before it to after it.
    start_seconds: float
    end_seconds: float
    video_id: int
    youtube_video_id: str
    video_title: str
    published_on: date | None
    channel_id: int
    channel_name: str
    # Opens the Video at the Segment's start.
    url: str
    cues: list[TimedLine]


@dataclass(frozen=True)
class VideoInfo:
    video_id: int
    youtube_video_id: str
    title: str
    channel_id: int
    channel_name: str
    published_on: date | None
    duration_seconds: int | None
    chapters: list[Chapter]
    description: str | None
    url: str


def watch_url(youtube_video_id: str, seconds: int | None = None) -> str:
    """The Video's YouTube watch link, at the whole second when given."""
    url = f"https://www.youtube.com/watch?v={youtube_video_id}"
    return url if seconds is None else f"{url}&t={seconds}s"


def expand(
    conn: sqlite3.Connection, segment_id: int, before_seconds: float, after_seconds: float, scope: Scope | None = None
) -> Expansion:
    """The Transcript's lines overlapping the Segment widened by before_seconds and after_seconds.

    Given a scope, a Segment of a Channel outside it is not found.
    """
    row = conn.execute(
        f"""
        SELECT segments.start_seconds, segments.end_seconds, transcripts.cues,
               videos.id AS video_id, videos.youtube_video_id, videos.title, videos.published_on,
               channels.id AS channel_id, channels.name AS channel_name
        FROM segments
        JOIN videos ON videos.id = segments.video_id
        JOIN transcripts ON transcripts.video_id = videos.id
        JOIN channels ON channels.id = videos.channel_id
        WHERE segments.id = :segment_id AND channels.indexed = 1 AND {CHANNEL_IN_SCOPE}
        """,
        {"segment_id": segment_id, **scope_params(scope)},
    ).fetchone()
    # A not-indexed Channel is left out everywhere, as in search.
    if row is None:
        raise NotFound(f"Segment {segment_id} not found")
    window_start, window_end = row["start_seconds"] - before_seconds, row["end_seconds"] + after_seconds
    cues = sorted((Cue(**c) for c in json.loads(row["cues"])), key=lambda c: c.start)
    return Expansion(
        segment_id=segment_id,
        start_seconds=row["start_seconds"],
        end_seconds=row["end_seconds"],
        video_id=row["video_id"],
        youtube_video_id=row["youtube_video_id"],
        video_title=row["title"],
        published_on=date.fromisoformat(row["published_on"]) if row["published_on"] else None,
        channel_id=row["channel_id"],
        channel_name=row["channel_name"],
        url=watch_url(row["youtube_video_id"], int(row["start_seconds"])),
        # Whitespace collapsed and blank cues dropped, as in Segment text.
        cues=[
            TimedLine(start_seconds=c.start, text=" ".join(c.text.split()))
            for c in cues
            if c.end > window_start and c.start < window_end and c.text.strip()
        ],
    )


def get_video(conn: sqlite3.Connection, video_id: int, scope: Scope | None = None) -> VideoInfo:
    """Given a scope, a Video of a Channel outside it is not found."""
    row = conn.execute(
        f"""
        SELECT videos.*, channels.name AS channel_name
        FROM videos
        JOIN channels ON channels.id = videos.channel_id
        WHERE videos.id = :video_id AND channels.indexed = 1 AND {CHANNEL_IN_SCOPE}
        """,
        {"video_id": video_id, **scope_params(scope)},
    ).fetchone()
    if row is None:
        raise NotFound(f"Video {video_id} not found")
    return VideoInfo(
        video_id=row["id"],
        youtube_video_id=row["youtube_video_id"],
        title=row["title"],
        channel_id=row["channel_id"],
        channel_name=row["channel_name"],
        published_on=date.fromisoformat(row["published_on"]) if row["published_on"] else None,
        duration_seconds=row["duration_seconds"],
        chapters=[Chapter(**c) for c in json.loads(row["chapters"] or "[]")],
        description=row["description"],
        url=watch_url(row["youtube_video_id"]),
    )
