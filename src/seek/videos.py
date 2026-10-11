"""Videos and their Transcripts as Syncs advance them. Functions are blocking; run them through Database.run."""

import json
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from seek import channels, storyboards
from seek.db import now_iso, transaction
from seek.errors import NotFound
from seek.channels import ChannelFilters
from seek.ports import (
    ChannelInfo,
    Chapter,
    PlaylistListing,
    SourceUnavailable,
    Transcript,
    VideoDetails,
    VideoListing,
    VideoUnavailable,
)

type PipelineStage = Literal["discovered", "transcript_fetched", "segmented", "embedded", "done"]
type Stage = PipelineStage | Literal["failed", "excluded"]
# What running one stage did to a Video: advanced it, stopped it (failed or excluded), or found it gone.
type StageOutcome = Literal["advanced", "stopped", "gone"]

PIPELINE: tuple[PipelineStage, ...] = ("discovered", "transcript_fetched", "segmented", "embedded", "done")

STAGES: tuple[Stage, ...] = (*PIPELINE, "failed", "excluded")

# Why a Playlist Sync fails when the playlist lists nothing while the Playlist has Videos.
EMPTY_LISTING = (
    "YouTube listed no Videos in this playlist, so nothing was removed. If the playlist really is empty now, "
    "delete the Playlist"
)

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


@dataclass(frozen=True)
class Source:
    """What a Sync ingests: a Channel's Videos, or the Videos a Playlist includes."""

    kind: Literal["channel", "playlist"]
    id: int

    @property
    def column(self) -> str:
        """The column that holds this source's id, on a Sync and on an event about it."""
        return f"{self.kind}_id"


def _of(source: Source, parameter: str = "?") -> str:
    """The condition on videos that picks the source's, with its id as the parameter."""
    if source.kind == "channel":
        return f"videos.channel_id = {parameter}"
    return f"videos.id IN (SELECT video_id FROM playlist_videos WHERE playlist_id = {parameter})"


@dataclass(frozen=True)
class Listed:
    """Where Videos are listed: under the Channel they are credited to, and in the Playlists that include them."""

    channel_id: int
    playlist_ids: list[int]


def listed(conn: sqlite3.Connection, video_id: int) -> Listed | None:
    """Where the Video is listed; None if it is gone."""
    row = conn.execute("SELECT channel_id FROM videos WHERE id = ?", (video_id,)).fetchone()
    if row is None:
        return None
    playlists = conn.execute(
        "SELECT playlist_id FROM playlist_videos WHERE video_id = ? ORDER BY playlist_id", (video_id,)
    )
    return Listed(row["channel_id"], [playlist["playlist_id"] for playlist in playlists])


def creators(conn: sqlite3.Connection, source: Source) -> set[int]:
    """The ids of the Channels the source's Videos are credited to: the Channel itself, or a Playlist's creators."""
    if source.kind == "channel":
        return {source.id}
    rows = conn.execute(f"SELECT DISTINCT channel_id FROM videos WHERE {_of(source)}", (source.id,))
    return {row["channel_id"] for row in rows}


def listed_by_creator(
    conn: sqlite3.Connection, source: Source, also_channel_ids: Collection[int] = ()
) -> list[Listed]:
    """Where the source's Videos are listed, a creator at a time: each Channel one of them is credited to, with
    every Playlist that includes any of that Channel's Videos.

    `also_channel_ids` names Channels to list as well, such as the creators of Videos a Playlist has just dropped.
    A Channel that is gone is left out.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT channels.id, playlist_videos.playlist_id
        FROM channels
        LEFT JOIN videos ON videos.channel_id = channels.id
        LEFT JOIN playlist_videos ON playlist_videos.video_id = videos.id
        WHERE channels.id IN (SELECT value FROM json_each(?))
        ORDER BY channels.id, playlist_videos.playlist_id
        """,
        (json.dumps(sorted({*creators(conn, source), *also_channel_ids})),),
    )
    playlists: dict[int, list[int]] = {}
    for row in rows:
        included_in = playlists.setdefault(row["id"], [])
        if row["playlist_id"] is not None:
            included_in.append(row["playlist_id"])
    return [Listed(channel_id, playlist_ids) for channel_id, playlist_ids in playlists.items()]


def _require_channel(conn: sqlite3.Connection, channel_id: int) -> None:
    if conn.execute("SELECT 1 FROM channels WHERE id = ? AND in_library = 1", (channel_id,)).fetchone() is None:
        raise NotFound(f"Channel {channel_id} not found")


@dataclass(frozen=True)
class ExclusionRules:
    """What a Sync excludes: Videos under the minimum length and Videos outside the Channel's filters."""

    min_duration_seconds: int
    filters: ChannelFilters


def exclusion(
    rules: ExclusionRules, duration_seconds: int | None, published_on: date | None, included: bool
) -> str | None:
    """The reason a Video is excluded by the rules that need only its own metadata; unknown values pass.

    Inclusion wins: a Video some Playlist includes is judged by the minimum length alone.
    """
    if duration_seconds is not None and duration_seconds < rules.min_duration_seconds:
        return f"Shorter than the {rules.min_duration_seconds} second minimum"
    if included:
        return None
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


@dataclass(frozen=True)
class PlaylistVideo(Video):
    """A Video as a Playlist lists it: under the Channel that made it, which may be outside the Library."""

    channel_id: int
    channel_name: str


def list_playlist_videos(conn: sqlite3.Connection, playlist_id: int) -> list[PlaylistVideo]:
    """The Playlist's Videos, in the playlist's order on YouTube."""
    if conn.execute("SELECT 1 FROM playlists WHERE id = ?", (playlist_id,)).fetchone() is None:
        raise NotFound(f"Playlist {playlist_id} not found")
    rows = conn.execute(
        f"""
        SELECT videos.*, {_STAGE_SQL} AS stage, transcripts.source AS transcript_source,
               channels.name AS channel_name
        FROM playlist_videos
        JOIN videos ON videos.id = playlist_videos.video_id
        JOIN channels ON channels.id = videos.channel_id
        LEFT JOIN transcripts ON transcripts.video_id = videos.id
        WHERE playlist_videos.playlist_id = ?
        ORDER BY playlist_videos.position
        """,
        (playlist_id,),
    )
    return [
        PlaylistVideo(**vars(_video(row)), channel_id=row["channel_id"], channel_name=row["channel_name"])
        for row in rows
    ]


def get_video(conn: sqlite3.Connection, video_id: int) -> Video | None:
    row = conn.execute(f"{_VIDEO_SQL} WHERE videos.id = ?", (video_id,)).fetchone()
    return None if row is None else _video(row)


@dataclass(frozen=True)
class SyncCounts:
    """What a Sync has finished with and what it has left, counted in Videos rather than in events."""

    completed: int
    failed: int
    remaining: int


def sync_counts(
    conn: sqlite3.Connection, sync_id: int, source: Source, queue: Collection[int] | None = None
) -> SyncCounts:
    """The Videos this Sync has finished with, of those the ones that failed, and the ones it has yet to reach.

    Once the Sync has listed the Videos it will work through, `queue` holds those it has not finished with, and
    only they are remaining: a failure a retry clears meanwhile waits for the Sync that retry queued. Before
    then, remaining is every Video the Sync would pick up now.

    A Video counts as finished with only while it is still done or failed: one put back in the queue -- a retry
    clearing its failure, a reindex stepping it back -- returns to the remaining side, so the two never describe
    the same Video at once and their sum is the work this Sync is doing. Videos left alone by this Sync -- done
    already, excluded, or permanently failed and not retried here -- are on neither side.
    """
    row = conn.execute(
        f"""
        SELECT
            count(*) FILTER (WHERE finished) AS completed,
            count(*) FILTER (WHERE finished AND failure_stage IS NOT NULL) AS failed,
            count(*) FILTER (
                WHERE NOT finished AND CASE
                    WHEN ?2 IS NULL THEN pipeline_stage != 'done' AND (failure_stage IS NULL OR failure_permanent = 0)
                    ELSE id IN (SELECT value FROM json_each(?2))
                END
            ) AS remaining
        FROM (
            SELECT id, pipeline_stage, failure_stage, failure_permanent,
                   completed_by_sync_id IS ?1 AND (pipeline_stage = 'done' OR failure_stage IS NOT NULL)
                       AS finished
            FROM videos WHERE {_of(source, "?3")} AND excluded_reason IS NULL
        )
        """,
        (sync_id, None if queue is None else json.dumps(list(queue)), source.id),
    )
    counts = row.fetchone()
    return SyncCounts(counts["completed"], counts["failed"], counts["remaining"])


def mark_completed(conn: sqlite3.Connection, video_id: int, sync_id: int) -> None:
    """Within a transaction: records that this Sync is the one that last finished with the Video."""
    conn.execute("UPDATE videos SET completed_by_sync_id = ? WHERE id = ?", (sync_id, video_id))


def stage_counts(conn: sqlite3.Connection, source: Source) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {_STAGE_SQL} AS stage, count(*) AS n FROM videos WHERE {_of(source)} GROUP BY stage", (source.id,)
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
        if not _sync_exists(conn, sync_id, Source("channel", channel_id)):
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
        if not _sync_exists(conn, sync_id, Source("channel", channel_id)):
            return False
        _apply_exclusions(conn, channel_id, listings, playlist_video_ids, rules)
        return True


def record_playlist_discovery(
    conn: sqlite3.Connection,
    sync_id: int,
    playlist_id: int,
    listing: PlaylistListing,
    avatars: Mapping[str, str | None],
    rules: ExclusionRules,
) -> int | None:
    """Records the playlist's listing: a creator not yet known becomes a Channel outside the Library, a Video not
    yet known is credited to its creator and judged by the rules, and the Playlist includes each Video at its
    place in the listing. A Video already known, such as one a Library Channel has ingested, is judged again as
    one a Playlist includes, which lifts an exclusion by its Channel's filters. The Playlist stops including a
    Video the listing no longer has.

    A video YouTube lists without its creator (a private or deleted one) has no entry, only its id. Nothing new
    is recorded for it, but a Video the Playlist already includes stays while its id is listed: it was not taken
    out of the playlist, and its Transcript may be impossible to fetch again.

    `listing` is one that completed: one that failed must not get here, since every Video it lacks leaves the
    Playlist. YouTube can also answer with nothing listed and no error, so an empty listing for a Playlist that
    has Videos raises SourceUnavailable and nothing is removed.

    `avatars` holds the avatar of each creator that may be new, by YouTube channel id. Returns how many Videos
    are new to the Playlist, or None if the Sync is gone.
    """
    with transaction(conn):
        if not _sync_exists(conn, sync_id, Source("playlist", playlist_id)):
            return None
        members = conn.execute(
            """
            SELECT playlist_videos.video_id, videos.youtube_video_id
            FROM playlist_videos JOIN videos ON videos.id = playlist_videos.video_id
            WHERE playlist_videos.playlist_id = ?
            """,
            (playlist_id,),
        )
        included = {row["youtube_video_id"]: row["video_id"] for row in members}
        if included and not listing.video_ids:
            raise SourceUnavailable(EMPTY_LISTING)
        # Each video's place among everything the playlist lists, with a creator or not.
        place = {video_id: position for position, video_id in enumerate(listing.video_ids)}
        in_listing: set[int] = set()
        discovered_at = now_iso()
        for entry in listing.entries:
            row = conn.execute(
                """
                SELECT id, duration_seconds, pipeline_stage, excluded_reason FROM videos
                WHERE youtube_video_id = ?
                """,
                (entry.video_id,),
            ).fetchone()
            if row is not None:
                judge_included(conn, row, rules)
            else:
                creator = ChannelInfo(entry.channel_id, entry.channel_name, avatars.get(entry.channel_id))
                row = conn.execute(
                    """
                    INSERT INTO videos (channel_id, youtube_video_id, title, duration_seconds, excluded_reason,
                                        discovered_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (
                        channels.credited_channel(conn, creator),
                        entry.video_id,
                        entry.title,
                        entry.duration_seconds,
                        exclusion(rules, entry.duration_seconds, None, included=True),
                        discovered_at,
                    ),
                ).fetchone()
            conn.execute(
                """
                INSERT INTO playlist_videos (playlist_id, video_id, position) VALUES (?, ?, ?)
                ON CONFLICT (playlist_id, video_id) DO UPDATE SET position = excluded.position
                """,
                (playlist_id, row["id"], place[entry.video_id]),
            )
            in_listing.add(row["id"])
        # A Video listed without its creator keeps its membership, and follows the listing's order as the rest do.
        conn.executemany(
            "UPDATE playlist_videos SET position = ? WHERE playlist_id = ? AND video_id = ?",
            [
                (place[youtube_video_id], playlist_id, video_id)
                for youtube_video_id, video_id in included.items()
                if youtube_video_id in place and video_id not in in_listing
            ],
        )
        # Worked out before any delete, since the memberships are what say which Videos to settle.
        removed = {video_id for youtube_video_id, video_id in included.items() if youtube_video_id not in place}
        conn.execute(
            "DELETE FROM playlist_videos WHERE playlist_id = ? AND video_id IN (SELECT value FROM json_each(?))",
            (playlist_id, json.dumps(sorted(removed))),
        )
        apply_keep_rule(conn, removed, rules.min_duration_seconds)
        return len(in_listing - set(included.values()))


def judge_included(conn: sqlite3.Connection, video: sqlite3.Row, rules: ExclusionRules) -> None:
    """Within a transaction: judges the Video, a row with its id, duration_seconds, pipeline_stage, and
    excluded_reason, as one a Playlist includes. Only the minimum length excludes it, so an exclusion by its
    Channel's filters is lifted."""
    _set_exclusion(conn, video, exclusion(rules, video["duration_seconds"], None, included=True))


def apply_keep_rule(conn: sqlite3.Connection, video_ids: Collection[int], min_duration_seconds: int) -> None:
    """Within a transaction: settles Videos that have just lost a Playlist that included them, or the Library
    Channel they were credited to. A Video is kept while its Channel is in the Library or any Playlist includes it.

    - A Video some Playlist still includes is left as it is.
    - One whose Channel is in the Library is no longer included, so it is judged again from what is stored: by
      the minimum length and its Channel's date window. The Channel's playlist filter and most-recent count need
      a listing, so they catch up at the Channel's next Sync.
    - Any other is deleted, with its Transcript, Segments, vectors, and storyboard. Every creator that leaves with
      no Videos is then forgotten.

    Read `video_ids` before deleting what kept them: a Playlist's memberships go with the Playlist, and then
    nothing says which Videos to look at.
    """
    no_longer_included = conn.execute(
        """
        SELECT videos.id, videos.channel_id, videos.duration_seconds, videos.published_on, videos.pipeline_stage,
               videos.excluded_reason, channels.in_library, channels.published_after, channels.published_before,
               channels.playlist_id, channels.most_recent
        FROM videos JOIN channels ON channels.id = videos.channel_id
        WHERE videos.id IN (SELECT value FROM json_each(?))
          AND NOT EXISTS (SELECT 1 FROM playlist_videos WHERE playlist_videos.video_id = videos.id)
        """,
        (json.dumps(sorted(video_ids)),),
    ).fetchall()
    unkept = [row for row in no_longer_included if not row["in_library"]]
    for row in no_longer_included:
        if row["in_library"]:
            rules = ExclusionRules(min_duration_seconds, channels.read_filters(row))
            published_on = date.fromisoformat(row["published_on"]) if row["published_on"] else None
            _set_exclusion(conn, row, exclusion(rules, row["duration_seconds"], published_on, included=False))
    conn.execute(
        "DELETE FROM videos WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps([row["id"] for row in unkept]),),
    )
    # Last, so a creator is judged by the Videos left once every delete is done. Only the creators of the Videos
    # just deleted are looked at, and only outside the Library: a Library Channel stays with no Videos at all.
    conn.execute(
        """
        DELETE FROM channels
        WHERE id IN (SELECT value FROM json_each(?)) AND in_library = 0
          AND NOT EXISTS (SELECT 1 FROM videos WHERE videos.channel_id = channels.id)
        """,
        (json.dumps(sorted({row["channel_id"] for row in unkept})),),
    )


def delete_channel(conn: sqlite3.Connection, channel_id: int, min_duration_seconds: int) -> list[Listed]:
    """Removes the Channel from the Library; its Conversations stay readable.

    A Channel with no Video in any Playlist is deleted, with everything ingested from it and its Group
    memberships. One a Playlist still draws on is taken out of the Library instead: the Videos Playlists include
    stay, credited as before, and the keep rule deletes the rest.

    Returns where the Videos that stay are listed, for the pages that list them to reload.
    """
    with transaction(conn):
        _require_channel(conn, channel_id)
        # Read before anything is deleted, as apply_keep_rule asks.
        rows = conn.execute(
            """
            SELECT id, EXISTS (SELECT 1 FROM playlist_videos WHERE playlist_videos.video_id = videos.id) AS included
            FROM videos WHERE channel_id = ?
            """,
            (channel_id,),
        ).fetchall()
        if not any(row["included"] for row in rows):
            conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
            return []
        channels.leave_library(conn, channel_id)
        apply_keep_rule(conn, [row["id"] for row in rows], min_duration_seconds)
        return listed_by_creator(conn, Source("channel", channel_id))


def _sync_exists(conn: sqlite3.Connection, sync_id: int, source: Source) -> bool:
    # A Sync goes with its Channel or Playlist, so this is how either is found to have been deleted meanwhile.
    found = conn.execute(f"SELECT 1 FROM syncs WHERE id = ? AND {source.column} = ?", (sync_id, source.id))
    return found.fetchone() is not None


def _apply_exclusions(
    conn: sqlite3.Connection,
    channel_id: int,
    listings: Sequence[VideoListing],
    playlist_video_ids: Collection[str] | None,
    rules: ExclusionRules,
) -> None:
    rows = conn.execute(
        """
        SELECT id, youtube_video_id, duration_seconds, published_on, pipeline_stage, excluded_reason,
               EXISTS (SELECT 1 FROM playlist_videos WHERE playlist_videos.video_id = videos.id) AS included
        FROM videos WHERE channel_id = ? ORDER BY id
        """,
        (channel_id,),
    ).fetchall()
    reasons: dict[int, str | None] = {}
    for row in rows:
        published_on = date.fromisoformat(row["published_on"]) if row["published_on"] else None
        reason = exclusion(rules, row["duration_seconds"], published_on, bool(row["included"]))
        if (
            reason is None
            and not row["included"]
            and playlist_video_ids is not None
            and row["youtube_video_id"] not in playlist_video_ids
        ):
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

        # A Video a Playlist includes takes none of the places: the Channel keeps its N newest besides.
        eligible = sorted(
            (row for row in rows if reasons[row["id"]] is None and not row["included"]), key=newest_first
        )
        for row in eligible[rules.filters.most_recent :]:
            reasons[row["id"]] = (
                f"Not among the {rules.filters.most_recent} most recent Videos, outside the Channel's filters"
            )
    for row in rows:
        _set_exclusion(conn, row, reasons[row["id"]])


def _set_exclusion(conn: sqlite3.Connection, video: sqlite3.Row, reason: str | None) -> None:
    """Records why the Video, a row with its id, pipeline_stage, and excluded_reason, is excluded, or that it no
    longer is.

    An excluded Video leaves the search indexes but keeps its Transcript, so lifting the exclusion re-segments it
    without fetching again. Stepping back to transcript_fetched also clears any failure at a later stage; those
    are all transient, so lifting the exclusion retries them.
    """
    if reason != video["excluded_reason"]:
        conn.execute("UPDATE videos SET excluded_reason = ? WHERE id = ?", (reason, video["id"]))
    if reason is not None and video["pipeline_stage"] in ("segmented", "embedded", "done"):
        conn.execute("DELETE FROM segments WHERE video_id = ?", (video["id"],))
        complete_stage(conn, video["id"], "transcript_fetched")


def youtube_ids(conn: sqlite3.Connection, channel_id: int) -> set[str]:
    """The YouTube ids of every Video of the Channel."""
    rows = conn.execute("SELECT youtube_video_id FROM videos WHERE channel_id = ?", (channel_id,))
    return {row["youtube_video_id"] for row in rows}


def pending_videos(conn: sqlite3.Connection, source: Source) -> list[PendingVideo]:
    """Videos a Sync should advance: not done, not excluded, and not permanently failed."""
    rows = conn.execute(
        f"""
        SELECT id, youtube_video_id, title, pipeline_stage FROM videos
        WHERE {_of(source)} AND pipeline_stage != 'done' AND excluded_reason IS NULL
          AND (failure_stage IS NULL OR failure_permanent = 0)
        ORDER BY id
        """,
        (source.id,),
    )
    return [PendingVideo(row["id"], row["youtube_video_id"], row["title"], row["pipeline_stage"]) for row in rows]


def _exclusion_by_details(
    conn: sqlite3.Connection, video_id: int, details: VideoDetails, rules: ExclusionRules
) -> str | None:
    """The reason the Video's full metadata excludes it, if it does."""
    included = conn.execute("SELECT 1 FROM playlist_videos WHERE video_id = ? LIMIT 1", (video_id,)).fetchone()
    return exclusion(rules, details.duration_seconds, details.published_on, included is not None)


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
            _exclusion_by_details(conn, video_id, details, rules),
            video_id,
        ),
    )
    if cursor.rowcount != 1:
        return False
    # The extraction that brought the metadata offered the storyboard too, so keeping it costs no YouTube call.
    # Passed even when it is None, which clears a template this extraction no longer backs.
    storyboards.record(conn, video_id, details.storyboard)
    return True


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
        return "stopped" if _exclusion_by_details(conn, video_id, details, rules) else "advanced"


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


def standing(conn: sqlite3.Connection, video_id: int) -> StageOutcome:
    """Within a transaction, before a stage's writes: "advanced" when the Sync may go on with the Video, "gone"
    when it was deleted meanwhile, and "stopped" when it has been excluded since the Sync took it up, as deleting
    a Playlist or a Channel does at once. Excluding it removed its Segments and stepped it back, so a stage
    written now would leave it done with nothing indexed."""
    row = conn.execute("SELECT excluded_reason FROM videos WHERE id = ?", (video_id,)).fetchone()
    if row is None:
        return "gone"
    return "advanced" if row["excluded_reason"] is None else "stopped"


def record_done(conn: sqlite3.Connection, video_id: int) -> StageOutcome:
    """Marks the Video done, unless it is gone or has been excluded meanwhile."""
    with transaction(conn):
        if (outcome := standing(conn, video_id)) == "advanced":
            complete_stage(conn, video_id, "done")
        return outcome


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


def step_back_for_reindex(conn: sqlite3.Connection, source: Source) -> None:
    """Within a transaction: every segmented, embedded, or done Video of the source goes back to
    transcript_fetched, so the Sync cuts and embeds it again from its stored Transcript. Its Segments stay until
    they are replaced, but leave search at once, since only a done Video's are searchable."""
    conn.execute(
        f"""
        UPDATE videos SET pipeline_stage = 'transcript_fetched'
        WHERE {_of(source)} AND pipeline_stage IN ('segmented', 'embedded', 'done')
        """,
        (source.id,),
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


def clear_failures(conn: sqlite3.Connection, source: Source) -> None:
    """Within a transaction: every failed Video of the source resumes from its last completed stage."""
    conn.execute(
        f"""
        UPDATE videos SET failure_stage = NULL, failure_reason = NULL, failure_permanent = NULL
        WHERE {_of(source)} AND failure_stage IS NOT NULL
        """,
        (source.id,),
    )
