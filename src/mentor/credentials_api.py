from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, field_validator

from mentor.credentials import Credentials, CredentialStatus


class KeyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    key: SecretStr

    @field_validator("key")
    @classmethod
    def nonempty_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if not key or len(key) > 4096 or any(not 33 <= ord(c) <= 126 for c in key):
            raise ValueError("Enter a nonempty API key without whitespace.")
        return SecretStr(key)


def credentials_router(credentials: Credentials) -> APIRouter:
    router = APIRouter()

    @router.get("/credentials/anthropic")
    async def status() -> CredentialStatus:
        return await credentials.status()

    @router.put("/credentials/anthropic")
    async def set_key(request: Request) -> CredentialStatus:
        # FastAPI's default validation response includes rejected inputs, including malformed JSON.
        # Parse this sensitive body here so no validation error can echo any part of it.
        try:
            entry = KeyEntry.model_validate_json(await request.body())
        except ValidationError:
            raise HTTPException(422, "Provide a nonempty API key as the key field.") from None
        return await credentials.replace(entry.key.get_secret_value())

    @router.delete("/credentials/anthropic")
    async def delete() -> CredentialStatus:
        return await credentials.delete()

    return router
