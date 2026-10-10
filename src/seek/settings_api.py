from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from seek.db import Database
from seek.events import Events
from seek.settings import Settings, read_settings, write_settings


def settings_router(database: Database, events: Events) -> APIRouter:
    router = APIRouter()

    @router.get("/settings")
    async def get_settings() -> Settings:
        return await database.run(read_settings)

    @router.patch("/settings")
    async def patch_settings(request: Request) -> Settings:
        # A misplaced credential must not be reflected in validation errors, including unknown field names.
        try:
            body = Settings.model_validate_json(await request.body())
        except ValidationError:
            raise HTTPException(
                422,
                "Use engine (api, cli or null), provider (anthropic), model (fast or deep) and thumbnails "
                "(true or false).",
            ) from None
        updated = await database.run(lambda conn: write_settings(conn, body))
        if body.model_fields_set:
            events.settings()
        return updated

    return router
