# 16 — CLI sync and scheduled Sync

**What to build:** `mentor sync --all | --channel` hands off to the running server when it's up and runs the pipeline directly when it isn't. A single command turns on a scheduled Sync of all Channels. (Stories 21, 50.)

**Blocked by:** 06 — Sync resilience and filters; 15 — Install and service

**Status:** ready-for-agent

- [ ] Enqueue-all API
- [ ] `mentor sync` detects a running server and enqueues through its API; otherwise it runs the pipeline in-process, respecting the worker lease
- [ ] `mentor install-service --timer` installs a systemd user timer running `mentor sync --all`, with a configurable schedule
- [ ] Tests: delegation when the server is up, direct run when down, and no double worker when both happen
