# 18 — Cloudflare Access MCP client verification

**What to build:** Confirm, on Drew's real Cloudflare Zero Trust setup, that Claude Code, Codex, and Claude Desktop can reach mentor's MCP endpoint through Access over the public URL, and document the working configuration. Access may answer unauthenticated clients with an HTML login redirect rather than an MCP-style auth challenge, and Desktop custom connectors can't send service-token headers, so the working setup is unknown. (Stories 32, 33, 47a.)

**Blocked by:** 17 — Remote access hardening

**Status:** needs-human — Drew configures the Access application and runs each client login

- [ ] Agent researches the current Cloudflare Access options for MCP clients (Access-managed OAuth, MCP server portals, service tokens) from primary docs and writes a short setup checklist
- [ ] Drew applies the setup; Claude Code, Codex, and Claude Desktop each list and call `search` over the public URL, or the blocker for each client is recorded
- [ ] README documents the working Access configuration per client, or states which client is unsupported and why
