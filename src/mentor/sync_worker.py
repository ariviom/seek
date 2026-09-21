import asyncio
import contextlib
import logging
import sqlite3
import time
import uuid
from dataclasses import replace

from mentor import segments, syncs, videos
from mentor.db import Database
from mentor.events import Events
from mentor.ports import (
    ChannelNotFound,
    Embedder,
    GpuOutOfMemory,
    ModelUnavailable,
    PlaylistNotFound,
    SourceUnavailable,
    TranscriptSource,
    VideoUnavailable,
)
from mentor.syncs import ClaimedSync, Sync
from mentor.videos import ExclusionRules, PendingVideo, PipelineStage, StageOutcome, Video

log = logging.getLogger(__name__)

# Short enough that a crashed server's Syncs resume soon after restart; renewed every quarter of it.
LEASE_SECONDS = 20.0
# Videos in a row the source may refuse before the Sync stops: YouTube is blocking this machine, not one Video.
THROTTLE_LIMIT = 3


class SyncWorker:
    """Runs queued Syncs one at a time, only while holding the lease shared by every mentor process."""

    def __init__(
        self,
        database: Database,
        transcripts: TranscriptSource,
        embedder: Embedder,
        min_duration_seconds: int,
        poll_seconds: float,
        events: Events,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._database = database
        self._transcripts = transcripts
        self._embedder = embedder
        self._min_duration_seconds = min_duration_seconds
        self._events = events
        # Polling picks up Syncs queued by other processes and leases they give up.
        self._poll_seconds = poll_seconds
        self._holder = uuid.uuid4().hex
        self._wake = asyncio.Event()
        self._lease_lost = False
        # After a Sync stops for throttling, no Sync is claimed for cooldown_seconds, doubling for each Sync in a
        # row that stops so, rather than running the next one into the same wall.
        self._cooldown_seconds = cooldown_seconds
        self._cooldown_until = 0.0
        self._throttled_syncs = 0
        # Videos refused in a row within the running Sync.
        self._throttled_videos = 0
        # The Videos the running Sync is still to work through, once it has listed them; its remaining work is
        # these and nothing else, so a failure a retry clears meanwhile is left to the Sync that retry queued.
        self._queue: list[int] | None = None

    def wake(self) -> None:
        self._wake.set()

    async def run(self) -> None:
        while True:
            # Cleared before draining, so a Sync queued mid-drain wakes the next pass immediately.
            self._wake.clear()
            try:
                await self._drain()
            except Exception:
                log.exception("Sync worker failed; retrying")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._poll_seconds)

    async def run_until_finished(self, sync_ids: list[int]) -> list[Sync]:
        """Runs queued Syncs until these have finished, waiting while another process holds the lease; returns
        those that still exist."""
        while True:
            self._wake.clear()
            await self._drain()
            current = await self._database.run(lambda conn: syncs.get_syncs(conn, sync_ids))
            if all(sync.status in ("done", "failed") for sync in current):
                return current
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._poll_seconds)

    async def _drain(self) -> None:
        if time.monotonic() < self._cooldown_until or not await self._database.run(syncs.has_work):
            return
        if not await self._database.run(lambda conn: syncs.acquire_lease(conn, self._holder, LEASE_SECONDS)):
            return
        self._lease_lost = False
        # Taking the lease may have requeued or failed Syncs a stopped worker left running.
        self._events.syncs()
        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            # Queued Syncs wait while the embedding model loads (the app wakes the worker when it's done); if it
            # failed to load, they fail with its reason.
            # A throttled Sync starts a cooldown that the Syncs still queued wait out too.
            while (
                not self._lease_lost
                and time.monotonic() >= self._cooldown_until
                and self._embedder.status().state in ("ready", "failed")
            ):
                claimed = await self._database.run(lambda conn: syncs.claim_next(conn, self._holder))
                if claimed is None:
                    break
                await self._run_sync(claimed)
        finally:
            heartbeat.cancel()
            if self._lease_lost:
                # The Sync stopped without finishing; the next holder requeues it.
                self._events.syncs()
            # Logged rather than raised, so a failing release can't replace a shutdown's CancelledError.
            try:
                await self._database.run(lambda conn: syncs.release_lease(conn, self._holder))
            except Exception:
                log.exception("Could not release the Sync lease; it expires on its own")

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(LEASE_SECONDS / 4)
            try:
                renewed = await self._database.run(lambda conn: syncs.renew_lease(conn, self._holder, LEASE_SECONDS))
            except Exception:
                log.exception("Could not renew the Sync lease")
                renewed = False
            if not renewed:
                self._lease_lost = True
                return

    async def _run_sync(self, sync: ClaimedSync) -> None:
        # Returning without finishing is deliberate in two cases: the Channel was deleted (its Sync went with
        # it), or the lease was lost (the next holder requeues the Sync).
        rules = ExclusionRules(self._min_duration_seconds, sync.filters)
        self._throttled_videos = 0
        self._queue = None
        try:
            # Shows the Sync running, with any failures a retry cleared when it was claimed.
            if not await self._progress(sync):
                return
            if (model := self._embedder.status()).state == "failed":
                # Not worth any YouTube calls: no Video could be embedded.
                raise ModelUnavailable(model.error or f"The embedding model {model.name} failed to load")
            if sync.retry_failed:
                self._events.videos(sync.channel_id)
            playlist_video_ids = None
            if sync.filters.playlist_id is not None:
                playlist_video_ids = set(
                    await asyncio.to_thread(self._transcripts.list_playlist, sync.filters.playlist_id)
                )
            # A listing may stop at the Videos already known once a Sync has completed, unless the most-recent
            # filter needs the whole order or a retry wants everything looked at again.
            known: set[str] = set()
            if sync.filters.most_recent is None and not sync.retry_failed:
                known = await self._database.run(
                    lambda conn: (
                        videos.youtube_ids(conn, sync.channel_id)
                        if syncs.completed_before(conn, sync.channel_id)
                        else set()
                    )
                )
            listings = await asyncio.to_thread(self._transcripts.list_videos, sync.youtube_channel_id, known)
            new_videos = await self._database.run(
                lambda conn: videos.record_discovery(
                    conn, sync.id, sync.channel_id, listings, playlist_video_ids, rules
                )
            )
            if new_videos is None:
                return
            self._events.videos(sync.channel_id)
            if not await self._progress(sync, new_videos):
                return
            attempted: set[int] = set()
            while True:
                pending = await self._database.run(lambda conn: videos.pending_videos(conn, sync.channel_id))
                pending = [video for video in pending if video.id not in attempted]
                if not pending:
                    self._queue = []
                    break
                for i, video in enumerate(pending):
                    self._queue = [v.id for v in pending[i:]]
                    attempted.add(video.id)
                    if not await self._advance(sync, rules, video):
                        return
                self._queue = []
                if sync.filters.most_recent is None:
                    break
                # A Video excluded only once its details arrived frees a place among the most recent N.
                if not await self._database.run(
                    lambda conn: videos.reapply_exclusions(
                        conn, sync.id, sync.channel_id, listings, playlist_video_ids, rules
                    )
                ):
                    return
                self._events.videos(sync.channel_id)
        except _Throttled as e:
            error: str | None = str(e)
            wait = self._cooldown_seconds * 2**self._throttled_syncs
            self._throttled_syncs += 1
            self._cooldown_until = time.monotonic() + wait
            log.warning("Sync %s stopped: %s; no Sync runs for the next %.0f s", sync.id, e, wait)
        except (ChannelNotFound, PlaylistNotFound, SourceUnavailable, ModelUnavailable) as e:
            error = str(e)
        except Exception as e:
            log.exception("Sync %s failed", sync.id)
            error = f"Unexpected error: {e}"
        else:
            error = None
            self._throttled_syncs = 0
        finished = await self._database.run(lambda conn: syncs.finish(conn, sync.id, error, self._queue))
        if finished is not None:
            self._events.sync(finished)

    async def _progress(
        self,
        sync: ClaimedSync,
        new_videos: int | None = None,
        video: PendingVideo | None = None,
        fetching: str | None = None,
    ) -> bool:
        """Refreshes and publishes the Sync's counts (naming the Video being fetched, if any), and the Video's stage
        if given; False if the Sync is gone.

        A Video that has just reached done or failed is marked as finished with by this Sync, which counts it
        once however many times it is processed.
        """

        def refresh(conn: sqlite3.Connection) -> tuple[Sync | None, Video | None]:
            changed = None if video is None else videos.get_video(conn, video.id)
            finished = changed.id if changed is not None and changed.stage in ("done", "failed") else None
            return syncs.update_progress(conn, sync.id, new_videos, finished, self._queue), changed

        updated, changed = await self._database.run(refresh)
        if changed is not None:
            self._events.video(sync.channel_id, changed)
        if updated is None:
            return False
        self._events.sync(replace(updated, fetching=fetching))
        return True

    async def _advance(self, sync: ClaimedSync, rules: ExclusionRules, video: PendingVideo) -> bool:
        """Runs the Video's remaining stages in order; False if the Sync should stop without finishing."""
        for stage in videos.PIPELINE[videos.PIPELINE.index(video.pipeline_stage) + 1 :]:
            if self._lease_lost:
                return False
            if stage == "transcript_fetched" and not await self._progress(sync, fetching=video.title):
                return False
            try:
                outcome = await self._run_stage(rules, video, stage)
            except _Throttled:
                # The refusal that stops the Sync still failed this Video, which the Sync has finished with.
                await self._progress(sync, video=video)
                raise
            if outcome == "gone" or not await self._progress(sync, video=video):
                return False
            if outcome == "stopped":
                return True
        return True

    async def _run_stage(self, rules: ExclusionRules, video: PendingVideo, stage: PipelineStage) -> StageOutcome:
        """Runs one stage after discovery, which the whole Channel completes at once."""
        if stage == "transcript_fetched":
            return await self._fetch_transcript(rules, video)
        try:
            if stage == "segmented":
                advanced = await self._database.run(lambda conn: segments.record_segments(conn, video.id))
            elif stage == "embedded":
                advanced = await self._embed(video)
            else:
                advanced = await self._database.run(lambda conn: videos.record_done(conn, video.id))
        except GpuOutOfMemory as e:
            # Another program holds the GPU for now. Fetching needs none of it, so the Sync goes on and this
            # Video, transcript kept, waits for Retry failed videos.
            log.warning("Stage %s failed for Video %s: %s", stage, video.youtube_video_id, e)
            return await self._record_failure(rules, video, stage, VideoUnavailable(str(e), permanent=False))
        except ModelUnavailable:
            # Not about this Video: the Sync stops, and the Video resumes from its last stage next time.
            raise
        except Exception as e:
            # As when fetching, one Video that can't be processed must not block its Channel's Syncs.
            log.exception("Stage %s failed for Video %s", stage, video.youtube_video_id)
            failure = VideoUnavailable(f"Unexpected error: {e}", permanent=False)
            return await self._record_failure(rules, video, stage, failure)
        return "advanced" if advanced else "gone"

    async def _record_failure(
        self, rules: ExclusionRules, video: PendingVideo, attempted: PipelineStage, failure: VideoUnavailable
    ) -> StageOutcome:
        recorded = await self._database.run(
            lambda conn: videos.record_failure(conn, video.id, attempted, failure, rules)
        )
        return "stopped" if recorded else "gone"

    async def _embed(self, video: PendingVideo) -> bool:
        """False if the Video is gone."""
        texts = await self._database.run(lambda conn: segments.segment_texts(conn, video.id))
        # A Video with no spoken text has no Segments; the model isn't needed for it.
        vectors = await asyncio.to_thread(self._embedder.embed_passages, [text for _, text in texts]) if texts else []
        pairs = [(segment_id, vector) for (segment_id, _), vector in zip(texts, vectors, strict=True)]
        return await self._database.run(lambda conn: segments.record_embeddings(conn, video.id, pairs))

    async def _fetch_transcript(self, rules: ExclusionRules, video: PendingVideo) -> StageOutcome:
        failure: VideoUnavailable | None = None
        try:
            details, transcript = await asyncio.to_thread(self._transcripts.fetch_video, video.youtube_video_id)
        except VideoUnavailable as e:
            failure = e
            if e.throttled:
                # This Video fails on its own and is retried by a later Sync; a run of them stops the Sync.
                self._throttled_videos += 1
                if self._throttled_videos >= THROTTLE_LIMIT:
                    outcome = await self._record_failure(rules, video, "transcript_fetched", failure)
                    if outcome == "gone":
                        return outcome
                    raise _Throttled(
                        f"{e.reason}. {THROTTLE_LIMIT} Videos in a row were refused, so the Sync stopped; the "
                        "Channel's remaining Videos wait for the next Sync"
                    ) from None
            else:
                self._throttled_videos = 0
        except SourceUnavailable:
            raise
        except Exception as e:
            # One misbehaving Video must not stop its Channel's Syncs for good; it is retried next Sync.
            log.exception("Fetching Video %s failed", video.youtube_video_id)
            failure = VideoUnavailable(f"Unexpected error: {e}", permanent=False)
            self._throttled_videos = 0
        else:
            self._throttled_videos = 0
            if transcript.language != "en":
                failure = VideoUnavailable(
                    f"Captions are in {transcript.language!r}; only English is ingested",
                    permanent=True,
                    language=transcript.language,
                    details=details,
                )
        if failure is not None:
            return await self._record_failure(rules, video, "transcript_fetched", failure)
        return await self._database.run(
            lambda conn: videos.record_transcript(conn, video.id, details, transcript, rules)
        )


class _Throttled(SourceUnavailable):
    """The source refused THROTTLE_LIMIT Videos in a row."""
