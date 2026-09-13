import asyncio
import contextlib
import logging
import uuid

from mentor import segments, syncs, videos
from mentor.db import Database
from mentor.ports import (
    ChannelNotFound,
    Embedder,
    ModelUnavailable,
    SourceUnavailable,
    TranscriptSource,
    VideoUnavailable,
)
from mentor.syncs import ClaimedSync
from mentor.videos import PendingVideo, PipelineStage, StageOutcome

log = logging.getLogger(__name__)

# Short enough that a crashed server's Syncs resume soon after restart; renewed every quarter of it.
LEASE_SECONDS = 20.0


class SyncWorker:
    """Runs queued Syncs one at a time, only while holding the lease shared by every mentor process."""

    def __init__(
        self,
        database: Database,
        transcripts: TranscriptSource,
        embedder: Embedder,
        min_duration_seconds: int,
        poll_seconds: float,
    ) -> None:
        self._database = database
        self._transcripts = transcripts
        self._embedder = embedder
        self._min_duration_seconds = min_duration_seconds
        # Polling picks up Syncs queued by other processes and leases they give up.
        self._poll_seconds = poll_seconds
        self._holder = uuid.uuid4().hex
        self._wake = asyncio.Event()
        self._lease_lost = False

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

    async def _drain(self) -> None:
        if not await self._database.run(syncs.has_work):
            return
        if not await self._database.run(lambda conn: syncs.acquire_lease(conn, self._holder, LEASE_SECONDS)):
            return
        self._lease_lost = False
        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            while not self._lease_lost:
                claimed = await self._database.run(lambda conn: syncs.claim_next(conn, self._holder))
                if claimed is None:
                    break
                await self._run_sync(claimed)
        finally:
            heartbeat.cancel()
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
        try:
            listings = await asyncio.to_thread(self._transcripts.list_videos, sync.youtube_channel_id)
            new_videos = await self._database.run(
                lambda conn: videos.record_discovery(
                    conn, sync.id, sync.channel_id, listings, self._min_duration_seconds
                )
            )
            if new_videos is None or not await self._progress(sync, new_videos):
                return
            for video in await self._database.run(lambda conn: videos.pending_videos(conn, sync.channel_id)):
                if not await self._advance(sync, video):
                    return
        except (ChannelNotFound, SourceUnavailable, ModelUnavailable) as e:
            error: str | None = str(e)
        except Exception as e:
            log.exception("Sync %s failed", sync.id)
            error = f"Unexpected error: {e}"
        else:
            error = None
        await self._database.run(lambda conn: syncs.finish(conn, sync.id, error))

    async def _progress(self, sync: ClaimedSync, new_videos: int | None = None) -> bool:
        return await self._database.run(lambda conn: syncs.update_progress(conn, sync.id, new_videos))

    async def _advance(self, sync: ClaimedSync, video: PendingVideo) -> bool:
        """Runs the Video's remaining stages in order; False if the Sync should stop without finishing."""
        for stage in videos.PIPELINE[videos.PIPELINE.index(video.pipeline_stage) + 1 :]:
            if self._lease_lost:
                return False
            outcome = await self._run_stage(video, stage)
            if outcome == "gone" or not await self._progress(sync):
                return False
            if outcome == "stopped":
                return True
        return True

    async def _run_stage(self, video: PendingVideo, stage: PipelineStage) -> StageOutcome:
        """Runs one stage after discovery, which the whole Channel completes at once."""
        if stage == "transcript_fetched":
            return await self._fetch_transcript(video)
        try:
            if stage == "segmented":
                advanced = await self._database.run(lambda conn: segments.record_segments(conn, video.id))
            elif stage == "embedded":
                advanced = await self._embed(video)
            else:
                advanced = await self._database.run(lambda conn: videos.record_done(conn, video.id))
        except ModelUnavailable:
            # Not about this Video: the Sync stops, and the Video resumes from its last stage next time.
            raise
        except Exception as e:
            # As when fetching, one Video that can't be processed must not block its Channel's Syncs.
            log.exception("Stage %s failed for Video %s", stage, video.youtube_video_id)
            return await self._record_failure(video, stage, VideoUnavailable(f"Unexpected error: {e}", permanent=False))
        return "advanced" if advanced else "gone"

    async def _record_failure(
        self, video: PendingVideo, attempted: PipelineStage, failure: VideoUnavailable
    ) -> StageOutcome:
        recorded = await self._database.run(
            lambda conn: videos.record_failure(conn, video.id, attempted, failure, self._min_duration_seconds)
        )
        return "stopped" if recorded else "gone"

    async def _embed(self, video: PendingVideo) -> bool:
        """False if the Video is gone."""
        texts = await self._database.run(lambda conn: segments.segment_texts(conn, video.id))
        # A Video with no spoken text has no Segments; the model isn't needed for it.
        vectors = await asyncio.to_thread(self._embedder.embed_passages, [text for _, text in texts]) if texts else []
        pairs = [(segment_id, vector) for (segment_id, _), vector in zip(texts, vectors, strict=True)]
        return await self._database.run(lambda conn: segments.record_embeddings(conn, video.id, pairs))

    async def _fetch_transcript(self, video: PendingVideo) -> StageOutcome:
        failure: VideoUnavailable | None = None
        try:
            details, transcript = await asyncio.to_thread(self._transcripts.fetch_video, video.youtube_video_id)
        except VideoUnavailable as e:
            failure = e
        except SourceUnavailable:
            raise
        except Exception as e:
            # One misbehaving Video must not stop its Channel's Syncs for good; it is retried next Sync.
            log.exception("Fetching Video %s failed", video.youtube_video_id)
            failure = VideoUnavailable(f"Unexpected error: {e}", permanent=False)
        else:
            if transcript.language != "en":
                failure = VideoUnavailable(
                    f"Captions are in {transcript.language!r}; only English is ingested",
                    permanent=True,
                    language=transcript.language,
                    details=details,
                )
        if failure is not None:
            return await self._record_failure(video, "transcript_fetched", failure)
        return await self._database.run(
            lambda conn: videos.record_transcript(conn, video.id, details, transcript, self._min_duration_seconds)
        )
