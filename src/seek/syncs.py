"""The persisted Sync queue and the lease that lets one worker at a time run it.

Functions are blocking; run them through Database.run.
"""

import json
import sqlite3
import time
from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal

from seek import channels, videos
from seek.channels import ChannelFilters
from seek.db import now_iso, transaction
from seek.errors import NotFound

type SyncStatus = Literal["queued", "running", "done", "failed"]


@dataclass(frozen=True)
class Sync:
    id: int
    channel_id: int
    channel_name: str
    status: SyncStatus
    error: str | None
    queued_at: str
    started_at: str | None
    finished_at: str | None
    new_videos: int
    # Videos this Sync has finished with, done or failed, each counted once however often it was processed.
    completed_videos: int
    # Of those, the ones that failed: completed work, but nothing a question can be answered from.
    failed_videos: int
    # Videos this Sync still has to get to; with completed_videos, the whole of its work.
    remaining_videos: int
    # completed_videos as this run of the Sync was claimed. Claiming resets started_at too, so the pair is
    # always a compatible baseline: the work since counted_from took the time since started_at, and no more.
    counted_from: int
    stage_counts: dict[str, int]
    # The title of the Video being fetched, on the event published as a running Sync starts fetching it.
    fetching: str | None = None


@dataclass(frozen=True)
class ClaimedSync:
    id: int
    channel_id: int
    youtube_channel_id: str
    retry_failed: bool
    reindex: bool
    # As they were when the Sync started; changes apply from the next Sync.
    filters: ChannelFilters


def _select(conn: sqlite3.Connection, where: str, params: tuple[object, ...]) -> list[Sync]:
    rows = conn.execute(
        f"""
        SELECT syncs.*, channels.name AS channel_name
        FROM syncs
        JOIN channels ON channels.id = syncs.channel_id
        {where}
        """,
        params,
    )
    return [
        Sync(
            id=row["id"],
            channel_id=row["channel_id"],
            channel_name=row["channel_name"],
            status=row["status"],
            error=row["error"],
            queued_at=row["queued_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            new_videos=row["new_videos"],
            completed_videos=row["completed_videos"],
            failed_videos=row["failed_videos"],
            remaining_videos=row["remaining_videos"],
            counted_from=row["counted_from"],
            stage_counts=json.loads(row["stage_counts"]),
        )
        for row in rows
    ]


def enqueue(conn: sqlite3.Connection, channel_id: int, reindex: bool = False) -> Sync:
    """Queues a Sync for the Channel, or returns the one already queued for it.

    A reindex Sync re-segments and re-embeds the Channel's indexed Videos when it starts.
    """
    with transaction(conn):
        return _enqueue(conn, channel_id, retry_failed=False, reindex=reindex)


def enqueue_all(conn: sqlite3.Connection, reindex: bool = False) -> list[Sync]:
    """Queues a Sync for every indexed Channel, as enqueue does for one."""
    with transaction(conn):
        channel_ids = [row["id"] for row in conn.execute("SELECT id FROM channels WHERE indexed = 1 ORDER BY id")]
        return [_enqueue(conn, channel_id, retry_failed=False, reindex=reindex) for channel_id in channel_ids]


def retry_failed(conn: sqlite3.Connection, channel_id: int) -> Sync:
    """Queues a Sync that retries every failed Video of the Channel, permanent failures too.

    Failures are cleared now, so the Videos stop showing as failed, and again when the Sync starts, in case a
    Sync still running records more meanwhile.
    """
    with transaction(conn):
        _require_channel(conn, channel_id)
        videos.clear_failures(conn, channel_id)
        return _enqueue(conn, channel_id, retry_failed=True)


def retry_video(conn: sqlite3.Connection, video_id: int) -> tuple[int, Sync]:
    """Clears one Video's failure, permanent or not, and queues a Sync for its Channel; returns the Channel's id
    and the Sync."""
    with transaction(conn):
        channel_id = videos.clear_failure(conn, video_id)
        return channel_id, _enqueue(conn, channel_id, retry_failed=False)


def _require_channel(conn: sqlite3.Connection, channel_id: int) -> None:
    if conn.execute("SELECT 1 FROM channels WHERE id = ?", (channel_id,)).fetchone() is None:
        raise NotFound(f"Channel {channel_id} not found")


def _enqueue(conn: sqlite3.Connection, channel_id: int, retry_failed: bool, reindex: bool = False) -> Sync:
    _require_channel(conn, channel_id)
    counts = json.dumps(videos.stage_counts(conn, channel_id))
    row = conn.execute("SELECT id FROM syncs WHERE channel_id = ? AND status = 'queued'", (channel_id,)).fetchone()
    if row is None:
        row = conn.execute(
            """
            INSERT INTO syncs (channel_id, status, queued_at, stage_counts, retry_failed, reindex)
            VALUES (?, 'queued', ?, ?, ?, ?)
            RETURNING id
            """,
            (channel_id, now_iso(), counts, retry_failed, reindex),
        ).fetchone()
    else:
        # The Sync already queued takes on the current counts and any retry or reindex request.
        conn.execute(
            """
            UPDATE syncs SET stage_counts = ?, retry_failed = max(retry_failed, ?), reindex = max(reindex, ?)
            WHERE id = ?
            """,
            (counts, retry_failed, reindex, row["id"]),
        )
    [sync] = _select(conn, "WHERE syncs.id = ?", (row["id"],))
    return sync


def list_syncs(conn: sqlite3.Connection, limit: int = 50) -> list[Sync]:
    """The most recent Syncs, newest first."""
    return _select(conn, "ORDER BY syncs.id DESC LIMIT ?", (limit,))


def get_syncs(conn: sqlite3.Connection, sync_ids: list[int]) -> list[Sync]:
    """The Syncs with these ids that still exist, oldest first."""
    placeholders = ", ".join("?" * len(sync_ids))
    return _select(conn, f"WHERE syncs.id IN ({placeholders}) ORDER BY syncs.id", tuple(sync_ids))


def completed_before(conn: sqlite3.Connection, channel_id: int) -> bool:
    """Whether a Sync of the Channel has ever finished, so its older Videos are all known."""
    return (
        conn.execute("SELECT 1 FROM syncs WHERE channel_id = ? AND status = 'done' LIMIT 1", (channel_id,)).fetchone()
        is not None
    )


def has_work(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM syncs WHERE status IN ('queued', 'running') LIMIT 1").fetchone() is not None


def acquire_lease(conn: sqlite3.Connection, holder: str, seconds: float) -> bool:
    """Takes or renews the worker lease; False while another holder's lease is unexpired."""
    now = time.time()
    with transaction(conn):
        row = conn.execute("SELECT holder, expires_at FROM sync_lease WHERE id = 1").fetchone()
        if row is not None and row["holder"] != holder and row["expires_at"] > now:
            return False
        conn.execute(
            """
            INSERT INTO sync_lease (id, holder, expires_at) VALUES (1, ?, ?)
            ON CONFLICT (id) DO UPDATE SET holder = excluded.holder, expires_at = excluded.expires_at
            """,
            (holder, now + seconds),
        )
        if row is None or row["holder"] != holder:
            # Any Sync still marked running belonged to a worker that no longer holds the lease; it resumes
            # from the queue, ahead of later Syncs, unless its Channel already has a newer one queued.
            conn.execute(
                """
                UPDATE syncs SET status = 'failed', error = 'Interrupted', finished_at = ?
                WHERE status = 'running' AND channel_id IN (SELECT channel_id FROM syncs WHERE status = 'queued')
                """,
                (now_iso(),),
            )
            conn.execute("UPDATE syncs SET status = 'queued', started_at = NULL WHERE status = 'running'")
        return True


def renew_lease(conn: sqlite3.Connection, holder: str, seconds: float) -> bool:
    """Extends the lease this holder already has; False if it no longer has it."""
    with transaction(conn):
        cursor = conn.execute(
            "UPDATE sync_lease SET expires_at = ? WHERE id = 1 AND holder = ?", (time.time() + seconds, holder)
        )
        return cursor.rowcount == 1


def release_lease(conn: sqlite3.Connection, holder: str) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM sync_lease WHERE holder = ?", (holder,))


def claim_next(conn: sqlite3.Connection, holder: str) -> ClaimedSync | None:
    """Marks the oldest queued Sync running, if this holder has the lease."""
    with transaction(conn):
        lease = conn.execute("SELECT holder, expires_at FROM sync_lease WHERE id = 1").fetchone()
        if lease is None or lease["holder"] != holder or lease["expires_at"] <= time.time():
            return None
        row = conn.execute(
            """
            SELECT syncs.id AS sync_id, syncs.retry_failed, syncs.reindex, channels.*
            FROM syncs JOIN channels ON channels.id = syncs.channel_id
            WHERE syncs.status = 'queued' ORDER BY syncs.id LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        if row["retry_failed"]:
            videos.clear_failures(conn, row["id"])
        if row["reindex"]:
            videos.step_back_for_reindex(conn, row["id"])
        # Videos a resumed retry or reindex puts back in the queue leave its completed count as they go, so the
        # counts are taken after. counted_from lands on the same figure, and moves with started_at, so the rate
        # measures this run from where it really restarts.
        counts = _record_counts(conn, row["sync_id"], row["id"])
        conn.execute(
            "UPDATE syncs SET status = 'running', started_at = ?, counted_from = ? WHERE id = ?",
            (now_iso(), counts.completed, row["sync_id"]),
        )
        return ClaimedSync(
            id=row["sync_id"],
            channel_id=row["id"],
            youtube_channel_id=row["youtube_channel_id"],
            retry_failed=bool(row["retry_failed"]),
            reindex=bool(row["reindex"]),
            filters=channels.read_filters(row),
        )


def _record_counts(
    conn: sqlite3.Connection, sync_id: int, channel_id: int, queue: Collection[int] | None = None
) -> videos.SyncCounts:
    """Within a transaction: stores the Sync's per-Video counts as they stand. Only a Sync that is running
    records them, so a finished one keeps its own after a later Sync takes its Videos over.

    A Video leaving the completed count -- a transient failure fetched again, a done Video newly excluded -- can
    take it below counted_from. The interval the rate is measured over then starts again from here, rather than
    measuring less work than was done in it."""
    counts = videos.sync_counts(conn, sync_id, channel_id, queue)
    conn.execute(
        """
        UPDATE syncs SET completed_videos = ?, failed_videos = ?, remaining_videos = ?, stage_counts = ?,
                         started_at = CASE WHEN ? < counted_from THEN ? ELSE started_at END,
                         counted_from = min(counted_from, ?)
        WHERE id = ?
        """,
        (
            counts.completed,
            counts.failed,
            counts.remaining,
            json.dumps(videos.stage_counts(conn, channel_id)),
            counts.completed,
            now_iso(),
            counts.completed,
            sync_id,
        ),
    )
    return counts


def update_progress(
    conn: sqlite3.Connection,
    sync_id: int,
    new_videos: int | None = None,
    finished_video_id: int | None = None,
    queue: Collection[int] | None = None,
) -> Sync | None:
    """Refreshes the Sync's counts from its Channel's Videos; None if the Sync is gone.

    `finished_video_id` names a Video this Sync has just brought to done or failed. Marking it again, when the Video
    is processed a second time, changes nothing, so it is never counted twice. `queue` is the Videos the Sync is
    still to work through, once it has listed them.
    """
    with transaction(conn):
        row = conn.execute("SELECT channel_id FROM syncs WHERE id = ?", (sync_id,)).fetchone()
        if row is None:
            return None
        if finished_video_id is not None:
            videos.mark_completed(conn, finished_video_id, sync_id)
        if new_videos is not None:
            conn.execute("UPDATE syncs SET new_videos = ? WHERE id = ?", (new_videos, sync_id))
        _record_counts(conn, sync_id, row["channel_id"], queue)
        [sync] = _select(conn, "WHERE syncs.id = ?", (sync_id,))
        return sync


def finish(
    conn: sqlite3.Connection, sync_id: int, error: str | None, queue: Collection[int] | None = None
) -> Sync | None:
    """None if the Sync is gone. `queue` is as for update_progress."""
    with transaction(conn):
        row = conn.execute("SELECT channel_id FROM syncs WHERE id = ?", (sync_id,)).fetchone()
        if row is None:
            return None
        _record_counts(conn, sync_id, row["channel_id"], queue)
        conn.execute(
            "UPDATE syncs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
            ("done" if error is None else "failed", error, now_iso(), sync_id),
        )
        [sync] = _select(conn, "WHERE syncs.id = ?", (sync_id,))
        return sync
