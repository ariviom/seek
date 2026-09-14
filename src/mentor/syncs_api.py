from collections.abc import Callable

from fastapi import APIRouter, status
from pydantic import BaseModel

from mentor import syncs, videos
from mentor.db import Database
from mentor.events import Events
from mentor.syncs import Sync
from mentor.videos import Video


class SyncOptions(BaseModel):
    # Re-segment and re-embed the indexed Videos, e.g. after upgrading to a mentor that composes passages differently.
    reindex: bool = False


def syncs_router(database: Database, events: Events, wake_worker: Callable[[], None]) -> APIRouter:
    router = APIRouter()

    @router.post("/channels/{channel_id}/syncs", status_code=status.HTTP_202_ACCEPTED)
    async def start_sync(channel_id: int, options: SyncOptions | None = None) -> Sync:
        reindex = options is not None and options.reindex
        sync = await database.run(lambda conn: syncs.enqueue(conn, channel_id, reindex))
        events.sync(sync)
        wake_worker()
        return sync

    @router.post("/syncs", status_code=status.HTTP_202_ACCEPTED)
    async def start_all_syncs(options: SyncOptions | None = None) -> list[Sync]:
        reindex = options is not None and options.reindex
        queued = await database.run(lambda conn: syncs.enqueue_all(conn, reindex))
        for sync in queued:
            events.sync(sync)
        wake_worker()
        return queued

    @router.post("/channels/{channel_id}/retry-failed", status_code=status.HTTP_202_ACCEPTED)
    async def retry_failed(channel_id: int) -> Sync:
        sync = await database.run(lambda conn: syncs.retry_failed(conn, channel_id))
        events.videos(channel_id)
        events.sync(sync)
        wake_worker()
        return sync

    @router.get("/syncs")
    async def list_syncs() -> list[Sync]:
        return await database.run(syncs.list_syncs)

    @router.get("/channels/{channel_id}/videos")
    async def list_videos(channel_id: int) -> list[Video]:
        return await database.run(lambda conn: videos.list_channel_videos(conn, channel_id))

    return router
