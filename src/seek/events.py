"""Live changes pushed to the web UI: Sync progress, Video stage changes, and model loading, from this process only.

Syncs run in the server process whenever it is up, so its subscribers see every Sync that matters.
"""

import asyncio
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from fastapi.encoders import jsonable_encoder

from seek.ports import ModelStatus
from seek.syncs import Sync
from seek.videos import Video

# Events a subscriber may fall behind by before its stream is closed; the client reconnects and reloads.
MAX_BACKLOG = 10_000


class Subscription:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue(MAX_BACKLOG)
        self.overflowed = False


class Events:
    """Fans each event out to every open stream, as JSON with a `type`. Call only from the event loop."""

    def __init__(self) -> None:
        self._subscriptions: set[Subscription] = set()

    @contextmanager
    def subscribe(self) -> Iterator[Subscription]:
        subscription = Subscription()
        self._subscriptions.add(subscription)
        try:
            yield subscription
        finally:
            self._subscriptions.discard(subscription)

    def _publish(self, event: dict[str, object]) -> None:
        data = json.dumps(jsonable_encoder(event))
        for subscription in self._subscriptions:
            try:
                subscription.queue.put_nowait(data)
            except asyncio.QueueFull:
                subscription.overflowed = True

    def sync(self, sync: Sync) -> None:
        """The Sync's record changed."""
        self._publish({"type": "sync", "sync": sync})

    def video(self, channel_id: int, video: Video) -> None:
        """One Video changed."""
        self._publish({"type": "video", "channel_id": channel_id, "video": video})

    def videos(self, channel_id: int) -> None:
        """Many of the Channel's Videos may have changed; reload them."""
        self._publish({"type": "videos", "channel_id": channel_id})

    def syncs(self) -> None:
        """Syncs were removed or their names changed; reload them."""
        self._publish({"type": "syncs"})

    def models(self, statuses: Mapping[str, ModelStatus]) -> None:
        """A model's download or loading progressed; statuses are by role, as Health reports them."""
        self._publish({"type": "models", "models": statuses})

    def settings(self) -> None:
        self._publish({"type": "settings"})

    def credentials(self) -> None:
        self._publish({"type": "credentials"})
