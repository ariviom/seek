"""Videos and their Transcripts as Syncs advance them. Functions are blocking; run them through Database.run."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from mentor.db import now_iso, transaction
from mentor.errors import NotFound
from mentor.ports import Chapter, Transcript, VideoDetails, VideoListing, VideoUnavailable

type PipelineStage = Literal["discovered", "transcript_fetched", "segmented", "embedded", "done"]
type Stage = PipelineStage | Literal["failed", "excluded"]
# What running one stage did to a Video: advanced it, stopped it (failed or excluded), or found it gone.
type StageOutcome = Literal["advanced", "stopped", "gone"]

PIPELINE: tuple[PipelineStage, ...] = ("discovered", "transcript_fetched", "segmented", "embedded", "done")

STAGES: tuple[Stage, ...] = (*PIPELINE, "failed", "excluded")

# The stage a Video shows: exclusion wins over failure, which wins over the last completed stage.
_STAGE_SQL = """
    CASE WHEN videos.excluded_reason IS NOT NULL THEN 'excluded'
         WHEN videos.failure_stage IS NOT NULL THEN 'failed'
         ELSE videos.pipeline_stage END
"""


@dataclass(frozen=True)
class Video:
    id: int
    youtube_video_id: str
    title: str
    published_on: date | None
    duration_seconds: int | None
    chapters: list[Chapter]
    stage: Stage
    # Why the Video is excluded or failed.
    reason: str | None
    failure_stage: PipelineStage | None
    permanent_failure: bool | None
    language: str | None
    transcript_source: str | None


@dataclass(frozen=True)
class PendingVideo:
    id: int
    youtube_video_id: str
    pipeline_stage: PipelineStage


def _require_channel(conn: sqlite3.Connection, channel_id: int) -> None:
    if conn.execute("SELECT 1 FROM channels WHERE id = ?", (channel_id,)).fetchone() is None:
        raise NotFound(f"Channel {channel_id} not found")


def _too_short(min_duration_seconds: int) -> str:
    return f"Shorter than the {min_duration_seconds} second minimum"


def _exclusion(duration_seconds: int | None, min_duration_seconds: int) -> str | None:
    if duration_seconds is not None and duration_seconds < min_duration_seconds:
        return _too_short(min_duration_seconds)
    return None


def list_channel_videos(conn: sqlite3.Connection, channel_id: int) -> list[Video]:
    _require_channel(conn, channel_id)
    rows = conn.execute(
        f"""
        SELECT videos.*, {_STAGE_SQL} AS stage, transcripts.source AS transcript_source
        FROM videos LEFT JOIN transcripts ON transcripts.video_id = videos.id
        WHERE videos.channel_id = ?
        ORDER BY videos.published_on DESC NULLS LAST, videos.id DESC
        """,
        (channel_id,),
    )
    return [
        Video(
            id=row["id"],
            youtube_video_id=row["youtube_video_id"],
            title=row["title"],
            published_on=date.fromisoformat(row["published_on"]) if row["published_on"] else None,
            duration_seconds=row["duration_seconds"],
            chapters=[Chapter(**c) for c in json.loads(row["chapters"] or "[]")],
            stage=row["stage"],
            reason=row["excluded_reason"] or row["failure_reason"],
            failure_stage=row["failure_stage"],
            permanent_failure=None if row["failure_permanent"] is None else bool(row["failure_permanent"]),
            language=row["language"],
            transcript_source=row["transcript_source"],
        )
        for row in rows
    ]


def stage_counts(conn: sqlite3.Connection, channel_id: int) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {_STAGE_SQL} AS stage, count(*) AS n FROM videos WHERE channel_id = ? GROUP BY stage", (channel_id,)
    )
    return {stage: 0 for stage in STAGES} | {row["stage"]: row["n"] for row in rows}


def record_discovery(
    conn: sqlite3.Connection, sync_id: int, channel_id: int, listings: Sequence[VideoListing], min_duration_seconds: int
) -> int | None:
    """Upserts the listing by YouTube video id; returns how many Videos are new, or None if the Sync is gone.

    Checking the Sync rather than the Channel matters: a deleted Channel's id can be reused by a new Channel.
    """
    with transaction(conn):
        if conn.execute("SELECT 1 FROM syncs WHERE id = ? AND channel_id = ?", (sync_id, channel_id)).fetchone() is None:
            return None
        count = "SELECT count(*) FROM videos WHERE channel_id = ?"
        (before,) = conn.execute(count, (channel_id,)).fetchone()
        discovered_at = now_iso()
        conn.executemany(
            """
            INSERT INTO videos (channel_id, youtube_video_id, title, duration_seconds, discovered_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (youtube_video_id) DO UPDATE SET
                title = excluded.title,
                duration_seconds = coalesce(excluded.duration_seconds, videos.duration_seconds)
            """,
            [(channel_id, v.video_id, v.title, v.duration_seconds, discovered_at) for v in listings],
        )
        (after,) = conn.execute(count, (channel_id,)).fetchone()
        conn.execute(
            "UPDATE videos SET excluded_reason = CASE WHEN duration_seconds < ?1 THEN ?2 END WHERE channel_id = ?3",
            (min_duration_seconds, _too_short(min_duration_seconds), channel_id),
        )
        return int(after - before)


def pending_videos(conn: sqlite3.Connection, channel_id: int) -> list[PendingVideo]:
    """Videos a Sync should advance: not done, not excluded, and not permanently failed."""
    rows = conn.execute(
        """
        SELECT id, youtube_video_id, pipeline_stage FROM videos
        WHERE channel_id = ? AND pipeline_stage != 'done' AND excluded_reason IS NULL
          AND (failure_stage IS NULL OR failure_permanent = 0)
        ORDER BY id
        """,
        (channel_id,),
    )
    return [PendingVideo(row["id"], row["youtube_video_id"], row["pipeline_stage"]) for row in rows]


def _record_details(conn: sqlite3.Connection, video_id: int, details: VideoDetails, min_duration_seconds: int) -> bool:
    cursor = conn.execute(
        """
        UPDATE videos SET title = ?, published_on = ?, duration_seconds = ?, description = ?, chapters = ?,
                          excluded_reason = ?
        WHERE id = ?
        """,
        (
            details.title,
            details.published_on.isoformat(),
            details.duration_seconds,
            details.description,
            json.dumps([asdict(c) for c in details.chapters]),
            _exclusion(details.duration_seconds, min_duration_seconds),
            video_id,
        ),
    )
    return cursor.rowcount == 1


def record_transcript(
    conn: sqlite3.Connection,
    video_id: int,
    details: VideoDetails,
    transcript: Transcript,
    min_duration_seconds: int,
) -> StageOutcome:
    """Stores metadata and the Transcript and advances the stage."""
    with transaction(conn):
        if not _record_details(conn, video_id, details, min_duration_seconds):
            return "gone"
        # A Video only found to be too short once its full metadata arrives is excluded, not advanced.
        if _exclusion(details.duration_seconds, min_duration_seconds) is not None:
            return "stopped"
        conn.execute(
            """
            UPDATE videos SET pipeline_stage = 'transcript_fetched', language = ?,
                              failure_stage = NULL, failure_reason = NULL, failure_permanent = NULL
            WHERE id = ?
            """,
            (transcript.language, video_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO transcripts (video_id, source, language, cues, fetched_at) VALUES (?, ?, ?, ?, ?)",
            (
                video_id,
                transcript.source,
                transcript.language,
                json.dumps([asdict(c) for c in transcript.cues]),
                now_iso(),
            ),
        )
        return "advanced"


def complete_stage(conn: sqlite3.Connection, video_id: int, stage: PipelineStage) -> bool:
    """Within a transaction: records the Video's last completed stage and clears any failure; False if it's gone."""
    cursor = conn.execute(
        """
        UPDATE videos SET pipeline_stage = ?, failure_stage = NULL, failure_reason = NULL, failure_permanent = NULL
        WHERE id = ?
        """,
        (stage, video_id),
    )
    return cursor.rowcount == 1


def record_done(conn: sqlite3.Connection, video_id: int) -> bool:
    """Marks the Video done; False if the Video is gone."""
    with transaction(conn):
        return complete_stage(conn, video_id, "done")


def record_failure(
    conn: sqlite3.Connection,
    video_id: int,
    attempted: PipelineStage,
    failure: VideoUnavailable,
    min_duration_seconds: int,
) -> bool:
    """Marks the Video failed at the attempted stage, keeping any metadata; False if the Video is gone."""
    with transaction(conn):
        if failure.details is not None and not _record_details(conn, video_id, failure.details, min_duration_seconds):
            return False
        cursor = conn.execute(
            """
            UPDATE videos SET failure_stage = ?, failure_reason = ?, failure_permanent = ?,
                              language = coalesce(?, language)
            WHERE id = ?
            """,
            (attempted, failure.reason, failure.permanent, failure.language, video_id),
        )
        return cursor.rowcount == 1
