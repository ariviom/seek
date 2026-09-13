import asyncio
import contextlib
import logging
import uuid

from mentor import syncs, videos
from mentor.db import Database
from mentor.ports import ChannelNotFound, SourceUnavailable, TranscriptSource, VideoUnavailable
from mentor.syncs import ClaimedSync
from mentor.videos import PendingVideo

log = logging.getLogger(__name__)

# Short enough that a crashed server's Syncs resume soon after restart; renewed every quarter of it.
LEASE_SECONDS = 20.0


class SyncWorker:
    """Runs queued Syncs one at a time, only while holding the lease shared by every mentor process."""

    def __init__(
        self, database: Database, transcripts: TranscriptSource, min_duration_seconds: int, poll_seconds: float
    ) -> None:
        self._database = database
        self._transcripts = transcripts
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
                if video.pipeline_stage != "discovered":
                    continue
                if self._lease_lost or not await self._fetch_transcript(video) or not await self._progress(sync):
                    return
        except (ChannelNotFound, SourceUnavailable) as e:
            error: str | None = str(e)
        except Exception as e:
            log.exception("Sync %s failed", sync.id)
            error = f"Unexpected error: {e}"
        else:
            error = None
        await self._database.run(lambda conn: syncs.finish(conn, sync.id, error))

    async def _progress(self, sync: ClaimedSync, new_videos: int | None = None) -> bool:
        return await self._database.run(lambda conn: syncs.update_progress(conn, sync.id, new_videos))

    async def _fetch_transcript(self, video: PendingVideo) -> bool:
        """False if the Video is gone."""
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
            unavailable = failure
            return await self._database.run(
                lambda conn: videos.record_failure(
                    conn, video.id, "transcript_fetched", unavailable, self._min_duration_seconds
                )
            )
        return await self._database.run(
            lambda conn: videos.record_transcript(conn, video.id, details, transcript, self._min_duration_seconds)
        )
