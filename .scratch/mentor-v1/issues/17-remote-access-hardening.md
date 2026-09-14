# 17 — Remote access hardening

**What to build:** mentor behaves correctly when published through Drew's reverse proxy under a public hostname or path prefix. The optional Cloudflare Access JWT check blocks any request that bypasses Access, including one relayed by a local proxy. (Stories 47, 47a–47c.)

**Blocked by:** 07 — Live Sync progress; 11 — MCP server

**Status:** ready-for-agent

- [ ] Honours `X-Forwarded-Proto` and `X-Forwarded-Host` for every absolute URL the server emits (list those URLs in the ticket's PR); optional root path prefix works for API, SSE, MCP, and static assets
- [ ] With `CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD` set, every request (API, MCP, SSE, static) needs a valid `Cf-Access-Jwt-Assertion`, verified against cached team keys
- [ ] Loopback exemption applies only to loopback requests with no `X-Forwarded-*` or `Cf-*` headers; a loopback request with forwarded headers and no valid JWT is rejected
- [ ] MCP allowed hosts include the configured public hostname
- [ ] SSE stays open through a buffering-prone proxy (keepalives observed)
- [ ] Tests with locally generated signing keys: valid, invalid, missing, expired JWT; the loopback cases; prefix URLs

From ticket 01 review: Health returns the absolute database path; decide whether that is acceptable once published. Relative fetch URLs need the prefix root to end in a slash; the static mount has no SPA fallback for client-side routes.

From ticket 07 review: behind Cloudflare Access, an expired session answers the EventSource with an HTML redirect; `web/src/events.ts` then reopens every 5 s with no sign in the UI that live updates stopped.

From ticket 11 review:
- The MCP app is added as a `Route("/mcp", ...)` in `app.py` wrapping the SDK's Starlette app, whose own route is also `/mcp`; check it still matches under a root path prefix. `/mcp/` answers 405 from the static mount.
- Only `/mcp` has DNS-rebinding protection (Host and Origin allowlists from `LOOPBACK_HOSTS` plus `mcp_allowed_hosts`); `/api`, including mutating endpoints, checks neither, and the loopback exemption would let a rebinding page in a local browser reach it.
