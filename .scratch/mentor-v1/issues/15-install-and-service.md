# 15 — Install and service

**What to build:** Following the README, a fresh `uv tool install` plus `mentor install-service` gives an always-on server at login. The README also shows how to register mentor in Claude Code, Codex, and Claude Desktop. (Stories 31–33, 45, 46, 48.)

**Blocked by:** 11 — MCP server

**Status:** done

- [x] `mentor install-service` writes and enables a systemd user unit for `mentor serve`, recording the Claude CLI path and a PATH that finds it
- [x] README: install, data location (backup is a file copy), config file and env vars
- [x] README: registration snippets for Claude Code (`claude mcp add --transport http`, user scope), Codex (`codex mcp add --url`), and Claude Desktop (custom connector with the public URL), plus troubleshooting for an unreachable server
- [x] Verified on this machine: install, service starts at login, Claude Code lists the tools over the local URL

From ticket 08 review:
- yt-dlp needs Deno on PATH for YouTube's JS challenges (`/home/linuxbrew/.linuxbrew/bin/deno` here); the unit's PATH must include it.
- README: document `youtube_delay_seconds`, `youtube_retries`, `youtube_backoff_seconds`, `youtube_cookie_file` (defaults live in `config.py`). yt-dlp writes refreshed cookies back to the cookie file, so it must be writable; a read-only one fails every call.
- README: document `reranker_model`, `reranker_temperature` (3), `gentle_recency_half_life_days` (3650), `gentle_recency_max_penalty_percent` (15), `strong_recency_half_life_days` (1095), `strong_recency_max_penalty_percent` (50), from tickets 09 and 10; defaults and their meaning are in `config.py`.
- README: models download on first start (about 2.2 GB) into the Hugging Face cache (`~/.cache/huggingface`, or `HF_HOME`) and need a CUDA GPU with about 3.5 GB free; the unit must see the same cache and GPU.
- A Sync blocked in a backoff sleep holds a worker thread that shutdown can't interrupt, so stopping the service while throttled waits out the backoff (30+60+120 s by default); consider `TimeoutStopSec`.

From ticket 11 review:
- README registration snippets must use the exact `/mcp` path: `/mcp/` falls through to the static mount and answers 405.
- README: document `mcp_allowed_hosts` (TOML list or comma-separated `MENTOR_MCP_ALLOWED_HOSTS`; `host:*` allows any port). Loopback is always allowed.

From ticket 13 review:
- Record `claude_cli_path` (or `MENTOR_CLAUDE_CLI_PATH`) in the unit: a systemd user PATH usually lacks `~/.local/bin`. Point it at the `~/.local/bin/claude` link, not the resolved `versions/<x>` path, which Claude Code updates delete.
- The chat inherits the service environment; an `ANTHROPIC_API_KEY` there bills the API (Health reports `api_key`). Don't set one in the unit.
- README: document `claude_cli_path` and the Health `claude_cli` states.

From ticket 15 review (deferred):
- Verified here: `uv tool install`, `mentor install-service` (unit enabled and active, models and Claude CLI ready), and Claude Code listing the five tools over `http://127.0.0.1:7337/mcp` through a one-off `--mcp-config`. Not done: an actual logout/login (this machine has Linger=yes, so the service starts at boot), and the README's user-scope `claude mcp add` and `codex mcp add`, which change Drew's global agent configs.
- The unit goes to `~/.config/systemd/user`; a user manager started with its own `XDG_CONFIG_HOME` wouldn't see it.
- The unit freezes the installing shell's PATH, including version-pinned directories (nvm, vite-plus); rerun `install-service` after they change. `uv run mentor install-service` or `uvx` pins the unit to that checkout's or cache's `mentor`.
- No network ordering: a boot-time start whose model cache is incomplete leaves the model failed (the process stays up) until a restart.
- `cli.install` (the health wait and its error messages) has no test; `service.install_service` does.
