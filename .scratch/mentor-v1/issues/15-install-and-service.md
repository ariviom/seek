# 15 — Install and service

**What to build:** Following the README, a fresh `uv tool install` plus `mentor install-service` gives an always-on server at login. The README also shows how to register mentor in Claude Code, Codex, and Claude Desktop. (Stories 31–33, 45, 46, 48.)

**Blocked by:** 11 — MCP server

**Status:** ready-for-agent

- [ ] `mentor install-service` writes and enables a systemd user unit for `mentor serve`, recording the Claude CLI path and a PATH that finds it
- [ ] README: install, data location (backup is a file copy), config file and env vars
- [ ] README: registration snippets for Claude Code (`claude mcp add --transport http`, user scope), Codex (`codex mcp add --url`), and Claude Desktop (custom connector with the public URL), plus troubleshooting for an unreachable server
- [ ] Verified on this machine: install, service starts at login, Claude Code lists the tools over the local URL
