# 16 — CLI sync and scheduled Sync

**What to build:** `mentor sync --all | --channel` hands off to the running server when it's up and runs the pipeline directly when it isn't. A single command turns on a scheduled Sync of all Channels. (Stories 21, 50.)

**Blocked by:** 06 — Sync resilience and filters; 15 — Install and service

**Status:** done

- [x] Enqueue-all API
- [x] `mentor sync` detects a running server and enqueues through its API; otherwise it runs the pipeline in-process, respecting the worker lease
- [x] `mentor install-service --timer` installs a systemd user timer running `mentor sync --all`, with a configurable schedule
- [x] Tests: delegation when the server is up, direct run when down, and no double worker when both happen

From ticket 04 review: `SyncWorker.run()` loops forever; `mentor sync` needs a public drain-once entry (today `_drain`) that respects the lease and returns when the queue is empty.

From ticket 16 review (deferred, not owned by a later ticket):
- A direct-mode `mentor sync` publishes Sync events only in its own process, so a server started meanwhile shows those Syncs running with stale counts until it takes the lease.
- A delegated `mentor sync` exits 0 once queued, so a scheduled run's failed Syncs show in the web UI but not in `journalctl --user -u mentor-sync` (documented in the README).
- `SyncWorker.run_until_finished` doesn't retry like `run()`: an unexpected store error (e.g. locked past busy_timeout) ends the command with a traceback; the Syncs resume on the next run.
- `--channel` Syncs a not-indexed Channel, as the per-Channel API does; `--all` skips them.
- `mentor sync` waits 30 s for a server whenever `mentor.service` is active, even if this shell's config points at another port.
