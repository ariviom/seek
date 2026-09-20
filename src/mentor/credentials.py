"""Stored Anthropic credentials and generation-bound validation; no health-time provider work."""

import asyncio
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Literal
from uuid import uuid4

import anthropic

from mentor.events import Events
from mentor.ports import Secrets, SecretsUnavailable

# SDK debug tracebacks can include provider-echoed credentials. Suppress its transport
# diagnostics only in the task currently holding a key, leaving unrelated requests/logs alone.
_using_key = ContextVar("using_credential", default=False)


class _CredentialLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _using_key.get()


logging.getLogger("anthropic._base_client").addFilter(_CredentialLogs())


@contextmanager
def suppressed_sdk_logs() -> Iterator[None]:
    """Keeps SDK transport diagnostics out of the log while this task sends a credential.

    Entry-time validation and chat turns both need it: either can make the SDK log a request the
    provider echoed a key into.
    """
    token = _using_key.set(True)
    try:
        yield
    finally:
        _using_key.reset(token)

Validity = Literal["unverified", "valid", "invalid"]


@dataclass(frozen=True)
class Credential:
    generation: str
    key: str = field(repr=False)
    validity: Validity = "unverified"


@dataclass(frozen=True)
class CredentialStatus:
    present: bool
    validity: Validity


class Credentials:
    """A single stored envelope commits the key, generation and last-known result together.

    Provider work runs outside the lock so replacement/deletion need not wait for the network.
    Future turns retain a Credential snapshot and report authentication failures by generation.
    """

    def __init__(self, secrets: Secrets, events: Events) -> None:
        self.secrets = secrets
        self.events = events
        self._lock = asyncio.Lock()

    async def _read(self) -> Credential | None:
        value = await asyncio.to_thread(self.secrets.get, "anthropic")
        if value is None:
            return None
        try:
            data = json.loads(value)
            if (not isinstance(data, dict) or not isinstance(data.get("key"), str)
                or not data["key"] or not isinstance(data.get("generation"), str)
                or data.get("validity") not in ("unverified", "valid", "invalid")):
                raise ValueError
            return Credential(data["generation"], data["key"], data["validity"])
        except (ValueError, TypeError):
            raise SecretsUnavailable("The stored credential could not be read. Replace or delete it.") from None

    async def _write(self, credential: Credential) -> None:
        await asyncio.to_thread(self.secrets.set, "anthropic", json.dumps({
            "key": credential.key, "generation": credential.generation, "validity": credential.validity,
        }))

    async def current(self) -> Credential | None:
        async with self._lock:
            return await self._read()

    async def status(self) -> CredentialStatus:
        current = await self.current()
        return self._status(current)

    @staticmethod
    def _status(current: Credential | None) -> CredentialStatus:
        return CredentialStatus(current is not None, current.validity if current else "unverified")

    async def replace(self, key: str) -> CredentialStatus:
        credential = Credential(str(uuid4()), key)
        await asyncio.shield(self._commit(credential))
        validity: Validity = "unverified"
        with suppressed_sdk_logs():
            try:
                async with anthropic.AsyncAnthropic(
                    api_key=key, base_url="https://api.anthropic.com", max_retries=0, timeout=10,
                ) as client:
                    # Per-request headers win over SDK custom-header environment values.
                    await client.models.list(
                        limit=1, extra_headers={"X-Api-Key": key, "Authorization": anthropic.omit}
                    )
                validity = "valid"
            except anthropic.AuthenticationError:
                validity = "invalid"
            except anthropic.APIError:
                # Rate limits, connection failures, overload and permission errors do not prove an invalid key.
                pass
        return await asyncio.shield(self._result(credential.generation, validity))

    async def _commit(self, credential: Credential | None) -> None:
        # The shielded operation holds the lock through storage and publication even
        # if its HTTP caller disconnects while a blocking keychain call is running.
        async with self._lock:
            if credential is None:
                await asyncio.to_thread(self.secrets.delete, "anthropic")
            else:
                await self._write(credential)
            self.events.credentials()

    async def _result(self, generation: str, validity: Validity) -> CredentialStatus:
        async with self._lock:
            current = await self._read()
            if current is not None and current.generation == generation and current.validity != validity:
                current = replace(current, validity=validity)
                await self._write(current)
                self.events.credentials()
            return self._status(current)

    async def invalidate(self, generation: str) -> CredentialStatus:
        """Report a turn's authentication rejection without affecting a newer credential."""
        return await asyncio.shield(self._result(generation, "invalid"))

    async def delete(self) -> CredentialStatus:
        await asyncio.shield(self._commit(None))
        return self._status(None)
