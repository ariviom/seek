"""Serving behind a reverse proxy: public URLs from forwarded headers, and refusing hosts and origins that aren't
seek's own."""

import re
from collections.abc import Sequence
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Host headers of local clients, with or without a port.
LOOPBACK_HOSTS = ("127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*")
# A path prefix is plain path segments, none of them "." or ".."; anything else would end up in the page's <base href>.
_PREFIX = re.compile(r"(/(?!\.\.?(/|$))[A-Za-z0-9._~-]+)+")


def _first(value: str | None) -> str | None:
    """The first of a header's comma-separated values, as a proxy chain appends its own."""
    if value is None:
        return None
    return value.split(",")[0].strip() or None


def host_allowed(host: str, allowed: Sequence[str]) -> bool:
    """Whether a Host header matches an allowed host; "name:*" matches the name with any port."""
    host = host.lower()
    for pattern in allowed:
        pattern = pattern.lower()
        if pattern.endswith(":*"):
            if host.startswith(pattern[:-1]) and host[len(pattern) - 1 :].isdigit():
                return True
        elif host == pattern:
            return True
    return False


class ProxyMiddleware:
    """Refuses DNS rebinding (a Host or Origin that isn't seek's), then takes the scheme, host, and path prefix a
    proxy forwarded, so URLs the server builds point at the public address."""

    def __init__(self, app: ASGIApp, allowed_hosts: Sequence[str]) -> None:
        self._app = app
        self._allowed_hosts = [*LOOPBACK_HOSTS, *allowed_hosts]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        forwarded_host = _first(headers.get("x-forwarded-host"))
        # The proxy's own Host as well as the forwarded one: a rebinding page can add headers to its requests.
        hosts = [headers.get("host", ""), *([] if forwarded_host is None else [forwarded_host])]
        if not all(host_allowed(host, self._allowed_hosts) for host in hosts):
            await JSONResponse({"detail": "Invalid Host header"}, 421)(scope, receive, send)
            return
        origin = headers.get("origin")
        if origin is not None and not self._origin_allowed(origin):
            await JSONResponse({"detail": "Invalid Origin header"}, 403)(scope, receive, send)
            return

        scope = dict(scope)
        if (proto := _first(headers.get("x-forwarded-proto"))) in ("http", "https"):
            scope["scheme"] = proto
        if forwarded_host is not None:
            host_header = (b"host", forwarded_host.encode("latin-1"))
            scope["headers"] = [header for header in scope["headers"] if header[0] != b"host"] + [host_header]
        if prefix := (_first(headers.get("x-forwarded-prefix")) or "").rstrip("/"):
            if not _PREFIX.fullmatch(prefix):
                await JSONResponse({"detail": "Invalid X-Forwarded-Prefix header"}, 400)(scope, receive, send)
                return
            # Starlette expects the path to include root_path; a proxy that stripped the prefix sent it without.
            if scope["path"] != prefix and not scope["path"].startswith(f"{prefix}/"):
                scope["raw_path"] = prefix.encode() + scope["raw_path"]
                scope["path"] = prefix + scope["path"]
            scope["root_path"] = prefix
        await self._app(scope, receive, send)

    def _origin_allowed(self, origin: str) -> bool:
        parts = urlsplit(origin)
        return parts.scheme in ("http", "https") and host_allowed(parts.netloc, self._allowed_hosts)
