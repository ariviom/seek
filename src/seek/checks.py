"""The server's automatic checks of each Channel for new Videos and each Playlist for changes."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from seek import syncs
from seek.db import Database
from seek.events import Events

log = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


async def run_checks(
    database: Database,
    events: Events,
    wake_worker: Callable[[], None],
    every_seconds: float,
    now: Callable[[], datetime] = utc_now,
) -> None:
    """Queues a normal Sync for each due Channel and Playlist at start and then every every_seconds, until cancelled.

    Only queues: the worker runs them as it runs any other, so its backoff after throttling applies unchanged.
    """
    while True:
        try:
            queued = await database.run(lambda conn: syncs.enqueue_due(conn, now()))
        except Exception:
            log.exception("Checking Channels and Playlists failed; trying again at the next check")
        else:
            for sync in queued:
                events.sync(sync)
            if queued:
                wake_worker()
        await asyncio.sleep(every_seconds)
