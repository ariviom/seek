import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from seek.events import Events

# Proxies otherwise hold events back until a buffer fills: nginx-style ones for X-Accel-Buffering, and compressing
# ones for no-transform.
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def events_router(events: Events, keepalive_seconds: float) -> APIRouter:
    router = APIRouter()

    @router.get("/events")
    async def stream_events() -> StreamingResponse:
        async def stream() -> AsyncIterator[str]:
            with events.subscribe() as subscription:
                # Sent once subscribed, so a client that reloads on it misses no later change.
                yield 'data: {"type": "ready"}\n\n'
                while not subscription.overflowed:
                    try:
                        data = await asyncio.wait_for(subscription.queue.get(), keepalive_seconds)
                    except TimeoutError:
                        # Keeps proxies from closing an idle stream.
                        yield ": keepalive\n\n"
                    else:
                        yield f"data: {data}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)

    return router
