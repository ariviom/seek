"""`seek backfill-storyboards`: the storyboard geometry of Videos ingested before it was kept.

Runs in this process, never through the server, and takes nothing from the Sync worker: it holds no Sync lease,
claims no Sync, and writes only the storyboards table, so neither waits on the other's work or its pace. What the
two do share is YouTube: both reach it from one address, so running this alongside a Sync raises the rate YouTube
sees, and a refusal it answers with can land on the Sync's throttle counter and stop it. A Sync queued or running
is warned about for that reason.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from seek import channels, db, storyboards, syncs
from seek.config import Config
from seek.ports import SourceUnavailable, TranscriptSource, VideoUnavailable
from seek.sync_command import SyncCommandError, find_channel

SYNC_RUNNING = (
    "warning: a Sync is queued or running. Both reach YouTube from this address, so a refusal brought on by the "
    "two together counts against the Sync and can stop it. Stop this and run it again when the Sync has finished."
)


@dataclass(frozen=True)
class BackfillReport:
    stored: int
    # Videos whose extraction offered no storyboard this can use; they show no frames.
    absent: int
    # Videos the source refused one at a time.
    failed: int
    # Videos left for the next run, which picks up where this one stopped.
    remaining: int
    # Why it stopped before working through them all, for the user.
    stopped: str | None = None


def backfill_storyboards(
    config: Config,
    channel: str | None,
    transcripts: TranscriptSource,
    progress: Callable[[str], None] = lambda line: None,
) -> BackfillReport:
    """Stores the storyboard geometry of each searchable Video of the Channel, or of every Channel, that has none.

    Resumable: each Video's geometry is committed as it arrives and already-stored Videos are never fetched again,
    so a run that is interrupted or stopped by the source loses nothing and the next one carries on.
    """
    conn = db.connect(config.database_path)
    try:
        try:
            # Migrated, but no embedding model is checked: nothing here reads or writes a vector.
            db.migrate(conn)
        except RuntimeError as e:
            # The knowledge base was made by a newer seek.
            raise SyncCommandError(str(e)) from e
        channel_id = None if channel is None else find_channel(channels.list_channels(conn), channel).id
        if syncs.has_work(conn):
            progress(SYNC_RUNNING)
        pending = storyboards.missing(conn, channel_id)
        return _work_through(conn, transcripts, pending, progress)
    finally:
        conn.close()


def _work_through(
    conn: sqlite3.Connection,
    transcripts: TranscriptSource,
    pending: list[tuple[int, str]],
    progress: Callable[[str], None],
) -> BackfillReport:
    stored = absent = failed = 0
    for done, (video_id, youtube_video_id) in enumerate(pending):
        try:
            found = transcripts.fetch_storyboard(youtube_video_id)
            if found is None:
                absent += 1
                progress(f"{youtube_video_id}: no storyboard offered")
                continue
            with db.transaction(conn):
                # A Video deleted since the list was read, e.g. with its Channel, stores nothing and stops nothing.
                kept = storyboards.record(conn, video_id, found)
            if not kept:
                progress(f"{youtube_video_id}: removed while this ran")
                continue
            stored += 1
            progress(f"{youtube_video_id}: {found.width}x{found.height}, {found.fragment_count} sheets")
        except VideoUnavailable as e:
            # One Video that can't be read is this Video's problem; the rest still get their frames.
            failed += 1
            progress(f"{youtube_video_id}: {e.reason}")
        except (SourceUnavailable, KeyboardInterrupt) as e:
            # YouTube refusing, or a Ctrl+C anywhere in the work: stop here rather than run into the wall, and
            # count this Video as still to do, which at worst stores it again next run.
            reason = "Interrupted" if isinstance(e, KeyboardInterrupt) else str(e)
            return BackfillReport(stored, absent, failed, len(pending) - done, reason)
    return BackfillReport(stored, absent, failed, 0)
