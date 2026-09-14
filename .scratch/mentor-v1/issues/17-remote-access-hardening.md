# 17 — Remote access hardening

**What to build:** mentor behaves correctly when published through Drew's reverse proxy under a public hostname or path prefix. The optional Cloudflare Access JWT check blocks any request that bypasses Access, including one relayed by a local proxy. (Stories 47, 47a–47c.)

**Blocked by:** 07 — Live Sync progress; 11 — MCP server

**Status:** done

- [x] Honours `X-Forwarded-Proto` and `X-Forwarded-Host` for every absolute URL the server emits (list those URLs in the ticket's PR); optional root path prefix works for API, SSE, MCP, and static assets
- [x] With `CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD` set, every request (API, MCP, SSE, static) needs a valid `Cf-Access-Jwt-Assertion`, verified against cached team keys
- [x] Loopback exemption applies only to loopback requests with no `X-Forwarded-*` or `Cf-*` headers; a loopback request with forwarded headers and no valid JWT is rejected
- [x] MCP allowed hosts include the configured public hostname
- [x] SSE stays open through a buffering-prone proxy (keepalives observed)
- [x] Tests with locally generated signing keys: valid, invalid, missing, expired JWT; the loopback cases; prefix URLs

From ticket 01 review: Health returns the absolute database path; decide whether that is acceptable once published. Relative fetch URLs need the prefix root to end in a slash; the static mount has no SPA fallback for client-side routes.

From ticket 07 review: behind Cloudflare Access, an expired session answers the EventSource with an HTML redirect; `web/src/events.ts` then reopens every 5 s with no sign in the UI that live updates stopped.

From ticket 11 review:
- The MCP app is added as a `Route("/mcp", ...)` in `app.py` wrapping the SDK's Starlette app, whose own route is also `/mcp`; check it still matches under a root path prefix. `/mcp/` answers 405 from the static mount.
- Only `/mcp` has DNS-rebinding protection (Host and Origin allowlists from `LOOPBACK_HOSTS` plus `mcp_allowed_hosts`); `/api`, including mutating endpoints, checks neither, and the loopback exemption would let a rebinding page in a local browser reach it.

From ticket 14 review:
- The Citation player embeds `https://www.youtube-nocookie.com/embed/...` in an iframe. Any CSP added here needs `frame-src https://www.youtube-nocookie.com`, and a `Referrer-Policy` of `no-referrer` breaks it (YouTube refuses embeds without a referrer).

## Outcome (2026-09-14)

Absolute URLs the server emits, all built from `scope["scheme"]`, the `Host` header, and the full path, which `proxy.ProxyMiddleware` sets from `X-Forwarded-Proto`, `X-Forwarded-Host`, and `X-Forwarded-Prefix`:
- Starlette's trailing-slash redirects (e.g. `/api/syncs/` → `/api/syncs`, and `/mentor` → `/mentor/` when the proxy doesn't strip the prefix). Tested.
- StaticFiles' directory redirect, only for a directory holding an `index.html`; the bundle root is answered by the `web_ui` route first, so it's effectively unreachable.
- Path-only, prefix-aware: the page's `<base href="{prefix}/">` (tested), FastAPI's `/docs` and `/openapi.json` `servers` (not tested).
- The MCP SDK's stateless JSON transport emits none. Citations link to YouTube itself.

Decisions on the review notes above:
- Health keeps the absolute database path: behind Access (or loopback) only the owner sees it.
- No SPA fallback: the UI has no client-side routes. The `<base href>` fixes the prefix-without-trailing-slash case.
- No CSP added. `/mcp/` still answers 405 (documented).
- `/api` now has the Host/Origin guard (`allowed_hosts`, renamed from `mcp_allowed_hosts`); the web UI says when live updates stop because the stream is refused.

From ticket 17 review (deferred, not owned by a later ticket):
- A proxy that sends no `X-Forwarded-*`, `Forwarded`, `X-Real-IP`, or `Cf-*` headers is indistinguishable from a local request, so the Access check lets it through; the README warns. Requiring a relay marker would need another signal than the peer address.
- The MCP SDK's own Host/Origin check still runs behind the middleware with exact (case-sensitive) matching, so a mixed-case `Host` on `/mcp` gets 421 where `/api` accepts it.
- Both middlewares pass non-HTTP scopes through unchecked; there are no websocket routes, but a future one would be unguarded.
- The `web_ui` route matches the literal `<head>` and serves index.html without ETag/Last-Modified.
- Stripped vs unstripped prefix is inferred from the path, so a prefix equal to `/api`, `/mcp`, `/assets`, or `/docs` is misread (README says not to use them).
- The hourly key refresh (`access.REFRESH_SECONDS`) is untested.
