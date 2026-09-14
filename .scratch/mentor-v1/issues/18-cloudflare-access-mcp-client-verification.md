# 18 — Cloudflare Access MCP client verification

**What to build:** Confirm, on Drew's real Cloudflare Zero Trust setup, that Claude Code, Codex, and Claude Desktop can reach mentor's MCP endpoint through Access over the public URL, and document the working configuration. Access may answer unauthenticated clients with an HTML login redirect rather than an MCP-style auth challenge, and Desktop custom connectors can't send service-token headers, so the working setup is unknown. (Stories 32, 33, 47a.)

**Blocked by:** 17 — Remote access hardening

**Status:** needs-human — Drew configures the Access application and runs each client login

- [x] Agent researches the current Cloudflare Access options for MCP clients (Access-managed OAuth, MCP server portals, service tokens) from primary docs and writes a short setup checklist
- [ ] Drew applies the setup; Claude Code, Codex, and Claude Desktop each list and call `search` over the public URL, or the blocker for each client is recorded
- [ ] README documents the working Access configuration per client, or states which client is unsupported and why

From ticket 15 review:
- README "Register mentor with your agents" shows only local URLs for Claude Code and Codex, and a bare public URL for Claude Desktop with a warning to gate it. Once the Access setup is decided, add the public-URL variants and the Access steps there.

## Setup checklist (researched 2026-09-14)

Approach: one **self-hosted** Access application over the whole hostname with **Managed OAuth** on. With it, Access answers non-browser clients with `401` + `WWW-Authenticate` pointing at its OAuth metadata (instead of a `302` to the login page), registers clients dynamically, and forwards the usual `Cf-Access-Jwt-Assertion` to the origin, so mentor's existing check works unchanged. One app, because mentor accepts a single `cf_access_aud`; covering the whole host also protects the web UI and `/.well-known/*`. Sources: [Managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/), [Secure MCP servers](https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/secure-mcp-servers/), [Claude connector auth](https://claude.com/docs/connectors/building/authentication).

**Cloudflare**
1. The mentor hostname is proxied through Cloudflare (orange-cloud DNS to the reverse proxy, or a Tunnel public hostname).
2. Zero Trust → Access controls → Applications → Add → Self-hosted. Domain `mentor.<domain>`, no path.
3. Allow policy for your identity; pick the identity provider.
4. Edit → Advanced settings → **Managed OAuth** on, then: Allow localhost clients on (Claude Code), Allow loopback clients on (Codex), Allowed redirect URIs `https://claude.ai/api/mcp/auth_callback` (Claude Desktop). Set Grant session duration to how often you accept re-logging in.
5. Copy the application's Audience (AUD) tag and your team domain (`<team>.cloudflareaccess.com`).

**This machine**
6. `~/.config/mentor/config.toml`: `allowed_hosts = ["mentor.<domain>"]`, `cf_access_team_domain`, `cf_access_aud`. Then `systemctl --user restart mentor`.
7. Proxy sends `X-Forwarded-*` (README "Publishing through a reverse proxy").

**Smoke checks**
8. `curl -si -X POST https://mentor.<domain>/mcp` → `401` with `WWW-Authenticate` (a `302` means Managed OAuth is off).
9. `curl -s https://mentor.<domain>/.well-known/oauth-authorization-server` → JSON.
10. `curl -si -H 'X-Forwarded-For: 1.2.3.4' http://127.0.0.1:7337/api/health` → `403` (the bypass guard is on).

**Clients** (each: authenticate, list tools, call `search`; on failure record the step, the error, and `journalctl --user -u mentor -e`)
11. Claude Code: `claude mcp add --transport http --scope user mentor-remote https://mentor.<domain>/mcp`, then `/mcp` → Authenticate.
12. Codex: `codex mcp add mentor-remote --url https://mentor.<domain>/mcp`, then `codex mcp login mentor-remote`.
13. Claude Desktop: Settings → Connectors → Add custom connector → `https://mentor.<domain>/mcp` → Connect.

Failure hints: OAuth succeeds but mentor answers 403 → AUD mismatch. Desktop callback rejected → redirect URI missing in step 4. Fallback for Claude Code and Codex only: a service token plus a Service Auth policy, sent as `CF-Access-Client-Id`/`CF-Access-Client-Secret` headers; Desktop has no header option.

## Exposure check (2026-09-14)

mentor runs with `listen_all_interfaces` behind the Access app (AUD `<aud>…`, team `myteam.cloudflareaccess.com`);
requests arrive from a relay at 192.168.50.247, which the router's port 443 on the public IP also reaches.
- Through `remote.example.com` unauthenticated: every path and method probed (API, `/mcp`, events, docs, assets,
  `.well-known`, path-normalisation variants) stops at Cloudflare with a 302 to login, or 403 for OPTIONS.
- Around Cloudflare (public IP with the mentor hostname, the LAN address, a forged or `alg: none` token): mentor 403.
- WebSockets now go through the same check (they previously passed it and only failed on the static mount).
- Not checkable from here: the Access policy's include rules (who may sign in).
