from collections.abc import Callable

from fastapi import APIRouter, status
from pydantic import BaseModel

from seek import syncs, videos
from seek.db import Database
from seek.events import Events
from seek.syncs import Sync
from seek.videos import PlaylistVideo, Source, Video


class SyncOptions(BaseModel):
    # Re-segment and re-embed the indexed Videos, e.g. after upgrading to a seek that composes passages differently.
    reindex: bool = False


def syncs_router(database: Database, events: Events, wake_worker: Callable[[], None]) -> APIRouter:
    router = APIRouter()

    async def start(source: Source, options: SyncOptions | None) -> Sync:
        reindex = options is not None and options.reindex
        sync = await database.run(lambda conn: syncs.enqueue(conn, source, reindex))
        events.sync(sync)
        wake_worker()
        return sync

    async def retry(source: Source) -> Sync:
        sync = await database.run(lambda conn: syncs.retry_failed(conn, source))
        events.videos(source)
        events.sync(sync)
        wake_worker()
        return sync

    @router.post("/channels/{channel_id}/syncs", status_code=status.HTTP_202_ACCEPTED)
    async def start_sync(channel_id: int, options: SyncOptions | None = None) -> Sync:
        return await start(Source("channel", channel_id), options)

    @router.post("/playlists/{playlist_id}/syncs", status_code=status.HTTP_202_ACCEPTED)
    async def start_playlist_sync(playlist_id: int, options: SyncOptions | None = None) -> Sync:
        return await start(Source("playlist", playlist_id), options)

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
        return await retry(Source("channel", channel_id))

    @router.post("/playlists/{playlist_id}/retry-failed", status_code=status.HTTP_202_ACCEPTED)
    async def retry_playlist_failed(playlist_id: int) -> Sync:
        return await retry(Source("playlist", playlist_id))

    @router.post("/videos/{video_id}/retry", status_code=status.HTTP_202_ACCEPTED)
    async def retry_video(video_id: int) -> Sync:
        channel_id, sync = await database.run(lambda conn: syncs.retry_video(conn, video_id))
        events.videos(Source("channel", channel_id))
        events.sync(sync)
        wake_worker()
        return sync

    @router.get("/syncs")
    async def list_syncs() -> list[Sync]:
        return await database.run(syncs.list_syncs)

    @router.get("/channels/{channel_id}/videos")
    async def list_videos(channel_id: int) -> list[Video]:
        return await database.run(lambda conn: videos.list_channel_videos(conn, channel_id))

    @router.get("/playlists/{playlist_id}/videos")
    async def list_playlist_videos(playlist_id: int) -> list[PlaylistVideo]:
        return await database.run(lambda conn: videos.list_playlist_videos(conn, playlist_id))

    return router
