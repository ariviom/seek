"""Optional Cloudflare Access verification: defence in depth against a request that reached mentor around Access.

Cloudflare remains the trust boundary; this only refuses what didn't come through it.
"""

import asyncio
import ipaddress
import logging
import time
import urllib.request
from collections.abc import Callable

import jwt
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger(__name__)

# Blocking: the body at an https URL.
type FetchKeys = Callable[[str], bytes]

# Keys rotate every six weeks, and a rotated-out key stays valid for a week, so an hour-old copy is current enough.
REFRESH_SECONDS = 3600.0


def fetch_url(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as response:
        body: bytes = response.read()
        return body


class AccessDenied(Exception):
    """The message is for the user."""


class AccessUnavailable(Exception):
    """The message is for the user."""


class AccessKeys:
    """The team's signing keys by key id, fetched when first needed and refreshed hourly.

    A token signed with a key not seen yet fetches them again, since keys rotate, but at most once every
    refetch_seconds, so tokens with made-up key ids can't make mentor hammer Cloudflare.
    """

    def __init__(self, certs_url: str, fetch: FetchKeys, refetch_seconds: float) -> None:
        self._certs_url = certs_url
        self._fetch = fetch
        self._refetch_seconds = refetch_seconds
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()

    async def get(self, kid: str) -> jwt.PyJWK | None:
        async with self._lock:
            age = None if self._fetched_at is None else time.monotonic() - self._fetched_at
            if age is None or age >= REFRESH_SECONDS or (kid not in self._keys and age >= self._refetch_seconds):
                await self._refresh()
            if not self._keys:
                raise AccessUnavailable("Could not fetch the Cloudflare Access keys to verify this request")
            return self._keys.get(kid)

    async def _refresh(self) -> None:
        # Counted as fetched even if it fails, so an outage doesn't mean a fetch per request.
        self._fetched_at = time.monotonic()
        try:
            key_set = jwt.PyJWKSet.from_json((await asyncio.to_thread(self._fetch, self._certs_url)).decode())
        except Exception as e:
            # Keys already fetched stay in use.
            log.warning("Could not fetch Cloudflare Access keys from %s: %s", self._certs_url, e)
            return
        self._keys = {key.key_id: key for key in key_set.keys if key.key_id is not None}


class AccessVerifier:
    def __init__(self, team_domain: str, audience: str, fetch: FetchKeys, refetch_seconds: float) -> None:
        self._issuer = f"https://{team_domain}"
        self._audience = audience
        self._keys = AccessKeys(f"{self._issuer}/cdn-cgi/access/certs", fetch, refetch_seconds)

    async def verify(self, token: str) -> None:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError:
            raise AccessDenied("The Cloudflare Access token is malformed") from None
        key = await self._keys.get(kid) if isinstance(kid, str) else None
        if key is None:
            raise AccessDenied("The Cloudflare Access token is signed with an unknown key")
        try:
            jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError:
            raise AccessDenied("The Cloudflare Access token has expired; sign in again") from None
        except jwt.PyJWTError as e:
            raise AccessDenied(f"The Cloudflare Access token is invalid: {e}") from None


def _direct(scope: Scope, headers: Headers) -> bool:
    """Whether a request was made on this machine rather than relayed: from loopback, and without the headers a proxy
    or Cloudflare adds, since a proxy on this machine connects from loopback too."""
    client = scope.get("client")
    loopback = client is not None and ipaddress.ip_address(client[0]).is_loopback
    relayed = any(
        name.startswith(("x-forwarded-", "cf-")) or name in ("forwarded", "x-real-ip") for name in headers.keys()
    )
    return loopback and not relayed


class AccessMiddleware:
    """Requires a valid Cloudflare Access token on every request not made directly on this machine."""

    def __init__(self, app: ASGIApp, verifier: AccessVerifier) -> None:
        self._app = app
        self._verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if not _direct(scope, headers):
            token = headers.get("cf-access-jwt-assertion")
            try:
                if token is None:
                    raise AccessDenied("Requests from outside this machine must come through Cloudflare Access")
                await self._verifier.verify(token)
            except AccessDenied as e:
                await JSONResponse({"detail": str(e)}, 403)(scope, receive, send)
                return
            except AccessUnavailable as e:
                await JSONResponse({"detail": str(e)}, 503)(scope, receive, send)
                return
        await self._app(scope, receive, send)
