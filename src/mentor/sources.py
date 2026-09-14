"""The sources behind search results: a Segment's surrounding Transcript and a Video's details.

Functions are blocking; run them through Database.run.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date

from mentor.errors import NotFound
from mentor.ports import Chapter, Cue

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
    channel_name: str
    mentor_name: str
    # Opens the Video at the Segment's start.
    url: str
    cues: list[TimedLine]


@dataclass(frozen=True)
class VideoInfo:
    video_id: int
    youtube_video_id: str
    title: str
    mentor_name: str
    channel_name: str
    published_on: date | None
    duration_seconds: int | None
    chapters: list[Chapter]
    description: str | None
    url: str


def _watch_url(youtube_video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={youtube_video_id}"


def expand(conn: sqlite3.Connection, segment_id: int, before_seconds: float, after_seconds: float) -> Expansion:
    """The Transcript's lines overlapping the Segment widened by before_seconds and after_seconds."""
    row = conn.execute(
        """
        SELECT segments.start_seconds, segments.end_seconds, transcripts.cues,
               videos.id AS video_id, videos.youtube_video_id, videos.title, videos.published_on,
               channels.name AS channel_name, mentors.name AS mentor_name
        FROM segments
        JOIN videos ON videos.id = segments.video_id
        JOIN transcripts ON transcripts.video_id = videos.id
        JOIN channels ON channels.id = videos.channel_id
        JOIN mentors ON mentors.id = channels.mentor_id
        WHERE segments.id = ? AND channels.indexed = 1
        """,
        (segment_id,),
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
        channel_name=row["channel_name"],
        mentor_name=row["mentor_name"],
        url=f"{_watch_url(row['youtube_video_id'])}&t={int(row['start_seconds'])}s",
        # Whitespace collapsed and blank cues dropped, as in Segment text.
        cues=[
            TimedLine(start_seconds=c.start, text=" ".join(c.text.split()))
            for c in cues
            if c.end > window_start and c.start < window_end and c.text.strip()
        ],
    )


def get_video(conn: sqlite3.Connection, video_id: int) -> VideoInfo:
    row = conn.execute(
        """
        SELECT videos.*, channels.name AS channel_name, mentors.name AS mentor_name
        FROM videos
        JOIN channels ON channels.id = videos.channel_id
        JOIN mentors ON mentors.id = channels.mentor_id
        WHERE videos.id = ? AND channels.indexed = 1
        """,
        (video_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"Video {video_id} not found")
    return VideoInfo(
        video_id=row["id"],
        youtube_video_id=row["youtube_video_id"],
        title=row["title"],
        mentor_name=row["mentor_name"],
        channel_name=row["channel_name"],
        published_on=date.fromisoformat(row["published_on"]) if row["published_on"] else None,
        duration_seconds=row["duration_seconds"],
        chapters=[Chapter(**c) for c in json.loads(row["chapters"] or "[]")],
        description=row["description"],
        url=_watch_url(row["youtube_video_id"]),
    )
