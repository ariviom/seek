from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """An in-process client for the app, with startup and shutdown run.

    httpx's ASGI transport does not send lifespan events on its own.
    """
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:7337") as client:
            yield client


type Json = dict[str, Any]


async def add_mentor(client: httpx.AsyncClient, name: str, channel: str) -> Json:
    response = await client.post("/api/mentors", json={"name": name, "channel": channel})
    assert response.status_code == 201, response.text
    mentor: Json = response.json()
    return mentor
