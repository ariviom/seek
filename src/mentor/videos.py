"""Videos and their Transcripts as Syncs advance them. Functions are blocking; run them through Database.run."""

import json
import sqlite3
from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from mentor.db import now_iso, transaction
from mentor.errors import NotFound
from mentor.channels import ChannelFilters
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
    title: str
    pipeline_stage: PipelineStage


def _require_channel(conn: sqlite3.Connection, channel_id: int) -> None:
    if conn.execute("SELECT 1 FROM channels WHERE id = ?", (channel_id,)).fetchone() is None:
        raise NotFound(f"Channel {channel_id} not found")


@dataclass(frozen=True)
class ExclusionRules:
    """What a Sync excludes: Videos under the minimum length and Videos outside the Channel's filters."""

    min_duration_seconds: int
    filters: ChannelFilters


def _exclusion(rules: ExclusionRules, duration_seconds: int | None, published_on: date | None) -> str | None:
    """The reason a Video is excluded by the rules that need only its own metadata; unknown values pass."""
    if duration_seconds is not None and duration_seconds < rules.min_duration_seconds:
        return f"Shorter than the {rules.min_duration_seconds} second minimum"
    after, before = rules.filters.published_after, rules.filters.published_before
    if published_on is not None and after is not None and published_on < after:
        return f"Published before {after.isoformat()}, outside the Channel's filters"
    if published_on is not None and before is not None and published_on > before:
        return f"Published after {before.isoformat()}, outside the Channel's filters"
    return None


_VIDEO_SQL = f"""
    SELECT videos.*, {_STAGE_SQL} AS stage, transcripts.source AS transcript_source
    FROM videos LEFT JOIN transcripts ON transcripts.video_id = videos.id
"""


def _video(row: sqlite3.Row) -> Video:
    return Video(
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


def list_channel_videos(conn: sqlite3.Connection, channel_id: int) -> list[Video]:
    _require_channel(conn, channel_id)
    rows = conn.execute(
        f"{_VIDEO_SQL} WHERE videos.channel_id = ? ORDER BY videos.published_on DESC NULLS LAST, videos.id DESC",
        (channel_id,),
    )
    return [_video(row) for row in rows]


def get_video(conn: sqlite3.Connection, video_id: int) -> Video | None:
    row = conn.execute(f"{_VIDEO_SQL} WHERE videos.id = ?", (video_id,)).fetchone()
    return None if row is None else _video(row)


def stage_counts(conn: sqlite3.Connection, channel_id: int) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {_STAGE_SQL} AS stage, count(*) AS n FROM videos WHERE channel_id = ? GROUP BY stage", (channel_id,)
    )
    return {stage: 0 for stage in STAGES} | {row["stage"]: row["n"] for row in rows}


def record_discovery(
    conn: sqlite3.Connection,
    sync_id: int,
    channel_id: int,
    listings: Sequence[VideoListing],
    playlist_video_ids: Collection[str] | None,
    rules: ExclusionRules,
) -> int | None:
    """Upserts the listing by YouTube video id and re-applies the rules to every Video of the Channel.

    `listings` is newest first; `playlist_video_ids` is None when the filters name no playlist. Returns how many
    Videos are new, or None if the Sync is gone.
    """
    with transaction(conn):
        if not _sync_exists(conn, sync_id, channel_id):
            return None
        count = "SELECT count(*) FROM videos WHERE channel_id = ?"
        (before,) = conn.execute(count, (channel_id,)).fetchone()
        discovered_at = now_iso()
        # A stored publish date came from the Video's full metadata, which is more precise than a listing's.
        conn.executemany(
            """
            INSERT INTO videos (channel_id, youtube_video_id, title, duration_seconds, published_on, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (youtube_video_id) DO UPDATE SET
                title = excluded.title,
                duration_seconds = coalesce(excluded.duration_seconds, videos.duration_seconds),
                published_on = coalesce(videos.published_on, excluded.published_on)
            """,
            [
                (
                    channel_id,
                    v.video_id,
                    v.title,
                    v.duration_seconds,
                    v.published_on and v.published_on.isoformat(),
                    discovered_at,
                )
                for v in listings
            ],
        )
        (after,) = conn.execute(count, (channel_id,)).fetchone()
        _apply_exclusions(conn, channel_id, listings, playlist_video_ids, rules)
        return int(after - before)


def reapply_exclusions(
    conn: sqlite3.Connection,
    sync_id: int,
    channel_id: int,
    listings: Sequence[VideoListing],
    playlist_video_ids: Collection[str] | None,
    rules: ExclusionRules,
) -> bool:
    """Re-applies the rules with what the Sync has learned since discovery; False if the Sync is gone."""
    with transaction(conn):
        if not _sync_exists(conn, sync_id, channel_id):
            return False
        _apply_exclusions(conn, channel_id, listings, playlist_video_ids, rules)
        return True


def _sync_exists(conn: sqlite3.Connection, sync_id: int, channel_id: int) -> bool:
    # Checked rather than the Channel, because a deleted Channel's id can be reused by a new Channel.
    return conn.execute("SELECT 1 FROM syncs WHERE id = ? AND channel_id = ?", (sync_id, channel_id)).fetchone() is not None


def _apply_exclusions(
    conn: sqlite3.Connection,
    channel_id: int,
    listings: Sequence[VideoListing],
    playlist_video_ids: Collection[str] | None,
    rules: ExclusionRules,
) -> None:
    rows = conn.execute(
        """
        SELECT id, youtube_video_id, duration_seconds, published_on, pipeline_stage, excluded_reason
        FROM videos WHERE channel_id = ? ORDER BY id
        """,
        (channel_id,),
    ).fetchall()
    reasons: dict[int, str | None] = {}
    for row in rows:
        published_on = date.fromisoformat(row["published_on"]) if row["published_on"] else None
        reason = _exclusion(rules, row["duration_seconds"], published_on)
        if reason is None and playlist_video_ids is not None and row["youtube_video_id"] not in playlist_video_ids:
            reason = f"Not in playlist {rules.filters.playlist_id}, outside the Channel's filters"
        reasons[row["id"]] = reason
    if rules.filters.most_recent is not None:
        position = {listing.video_id: i for i, listing in enumerate(listings)}

        def newest_first(row: sqlite3.Row) -> tuple[int, int]:
            # Listed Videos by listing position. A listing can come back short, so Videos missing from it
            # follow by publish date, then undated ones in discovery order.
            if row["youtube_video_id"] in position:
                return (0, position[row["youtube_video_id"]])
            if row["published_on"]:
                return (1, -date.fromisoformat(row["published_on"]).toordinal())
            return (2, 0)

        eligible = sorted((row for row in rows if reasons[row["id"]] is None), key=newest_first)
        for row in eligible[rules.filters.most_recent :]:
            reasons[row["id"]] = (
                f"Not among the {rules.filters.most_recent} most recent Videos, outside the Channel's filters"
            )
    conn.executemany(
        "UPDATE videos SET excluded_reason = ? WHERE id = ?",
        [(reasons[row["id"]], row["id"]) for row in rows if reasons[row["id"]] != row["excluded_reason"]],
    )
    # Excluded Videos leave the search indexes but keep their Transcripts, so lifting the exclusion re-segments
    # them without fetching again. Stepping back to transcript_fetched also clears any failure at a later
    # stage; those are all transient, so lifting the exclusion retries them.
    for row in rows:
        if reasons[row["id"]] is not None and row["pipeline_stage"] in ("segmented", "embedded", "done"):
            conn.execute("DELETE FROM segments WHERE video_id = ?", (row["id"],))
            complete_stage(conn, row["id"], "transcript_fetched")


def youtube_ids(conn: sqlite3.Connection, channel_id: int) -> set[str]:
    """The YouTube ids of every Video of the Channel."""
    rows = conn.execute("SELECT youtube_video_id FROM videos WHERE channel_id = ?", (channel_id,))
    return {row["youtube_video_id"] for row in rows}


def pending_videos(conn: sqlite3.Connection, channel_id: int) -> list[PendingVideo]:
    """Videos a Sync should advance: not done, not excluded, and not permanently failed."""
    rows = conn.execute(
        """
        SELECT id, youtube_video_id, title, pipeline_stage FROM videos
        WHERE channel_id = ? AND pipeline_stage != 'done' AND excluded_reason IS NULL
          AND (failure_stage IS NULL OR failure_permanent = 0)
        ORDER BY id
        """,
        (channel_id,),
    )
    return [PendingVideo(row["id"], row["youtube_video_id"], row["title"], row["pipeline_stage"]) for row in rows]


def _record_details(conn: sqlite3.Connection, video_id: int, details: VideoDetails, rules: ExclusionRules) -> bool:
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
            _exclusion(rules, details.duration_seconds, details.published_on),
            video_id,
        ),
    )
    return cursor.rowcount == 1


def record_transcript(
    conn: sqlite3.Connection,
    video_id: int,
    details: VideoDetails,
    transcript: Transcript,
    rules: ExclusionRules,
) -> StageOutcome:
    """Stores metadata and the Transcript and advances the stage.

    A Video found to be excluded only once its full metadata arrives keeps the Transcript but goes no further.
    """
    with transaction(conn):
        if not _record_details(conn, video_id, details, rules):
            return "gone"
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
        return "stopped" if _exclusion(rules, details.duration_seconds, details.published_on) else "advanced"


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
    rules: ExclusionRules,
) -> bool:
    """Marks the Video failed at the attempted stage, keeping any metadata; False if the Video is gone."""
    with transaction(conn):
        if failure.details is not None and not _record_details(conn, video_id, failure.details, rules):
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


def step_back_for_reindex(conn: sqlite3.Connection, channel_id: int) -> None:
    """Within a transaction: every segmented, embedded, or done Video of the Channel goes back to
    transcript_fetched, so the Sync cuts and embeds it again from its stored Transcript. Its Segments stay until
    they are replaced, but leave search at once, since only a done Video's are searchable."""
    conn.execute(
        """
        UPDATE videos SET pipeline_stage = 'transcript_fetched'
        WHERE channel_id = ? AND pipeline_stage IN ('segmented', 'embedded', 'done')
        """,
        (channel_id,),
    )


def clear_failure(conn: sqlite3.Connection, video_id: int) -> int:
    """Within a transaction: the Video, permanently failed or not, resumes from its last completed stage on the
    next Sync. Returns its Channel's id."""
    row = conn.execute("SELECT channel_id FROM videos WHERE id = ?", (video_id,)).fetchone()
    if row is None:
        raise NotFound(f"Video {video_id} not found")
    conn.execute(
        "UPDATE videos SET failure_stage = NULL, failure_reason = NULL, failure_permanent = NULL WHERE id = ?",
        (video_id,),
    )
    return int(row["channel_id"])


def clear_failures(conn: sqlite3.Connection, channel_id: int) -> None:
    """Within a transaction: every failed Video of the Channel resumes from its last completed stage."""
    conn.execute(
        """
        UPDATE videos SET failure_stage = NULL, failure_reason = NULL, failure_permanent = NULL
        WHERE channel_id = ? AND failure_stage IS NOT NULL
        """,
        (channel_id,),
    )
