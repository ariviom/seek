from collections.abc import Callable

from fastapi import APIRouter, status

from mentor import syncs, videos
from mentor.db import Database
from mentor.events import Events
from mentor.syncs import Sync
from mentor.videos import Video


def syncs_router(database: Database, events: Events, wake_worker: Callable[[], None]) -> APIRouter:
    router = APIRouter()

    @router.post("/channels/{channel_id}/syncs", status_code=status.HTTP_202_ACCEPTED)
    async def start_sync(channel_id: int) -> Sync:
        sync = await database.run(lambda conn: syncs.enqueue(conn, channel_id))
        events.sync(sync)
        wake_worker()
        return sync

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
