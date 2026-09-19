# 04 — Start Mentor in a terminal with platform-appropriate directories

**What to build:** A friend's first foreground run creates Mentor's directories in the expected places, prints a
usable URL, and explains that closing the terminal stops Mentor. Linux service users retain their existing setup.
(Stories 3–5.)

**Blocked by:** None — can start once the shared implementation prerequisites are resolved.

**Status:** done — 2026-09-19

- [x] Resolve config and data directories through two pure functions of environment and platform, with any home
  directory input explicit. Keep platform-specific path choices in that module.
- [x] Preserve Linux XDG defaults, including the XDG data directory as the default data location. Honour explicit
  XDG config/data variables on all platforms and retain explicit operational data-directory overrides.
- [x] Use macOS Application Support for both config and data; use Windows roaming application data for config and
  local application data for data. Supporting these path rules does not claim a native Windows release.
- [x] First startup creates missing config/data directories without overwriting existing configuration or databases.
  All commands resolve the same locations; failures such as unwritable directories produce useful messages.
- [x] Foreground startup prints the loopback URL with the configured port and states that closing the terminal
  stops Mentor. Startup errors remain visible; printing a URL must not falsely claim the server is ready.
- [x] Off Linux, service installation refuses with a pointer to `mentor serve` before attempting systemd schedule
  validation or unit creation, including when a Sync schedule was requested.
- [x] Off Linux, ordinary foreground and Sync commands do not require systemctl. Manual UI Sync and `mentor sync`
  remain supported; do not introduce a scheduler or replacement service manager.
- [x] Keep Linux service installation, environment handling and existing scheduled Sync behaviour working. Update
  the path/lifecycle documentation and note that ADR 0002's XDG location remains the Linux rule.

**Verification:** Pure path tables for platforms, overrides and defaults; CLI startup/refusal checks, including a
schedule argument on a non-Linux platform; existing service and standalone-Sync behaviour checks. Device execution
is verified by ticket 02, so it is not an artificial prerequisite for this path/lifecycle slice.

## Closure evidence — 2026-09-19

Implementation revision: `5971370` on `build-0/ticket-04-platform-lifecycle`, fresh worktree
`/home/drew/mentor-ticket-04` from main `2abd2e0`.

- Pure config/data path checks cover Linux, macOS and Windows defaults, XDG precedence and
  operational data overrides. `load_config` remains read-only; startup creates directories
  without replacing config/database files and reports unusable paths.
- CLI checks cover configured loopback URL, terminal lifetime, visible failure without a
  readiness claim, and non-Linux refusal before config/schedule/systemd work, including `--timer`.
  Non-Linux Sync/reindex checks use the real HTTP handoff with fake model/YouTube ports;
  existing standalone Sync and Linux service/timer checks pass.
- `uv run pytest -q`: **394 passed, 4 opt-in tests deselected** (including passing Playwright smoke).
  `uv run mypy`: **78 files pass**. `pnpm --dir web run typecheck`: **pass**.
- Isolated actual Linux foreground check: temporary XDG config/data roots, spare loopback port,
  deliberately uncached model names with Hub/Transformers offline and CUDA hidden. Health
  responded, config/data directories and database were created, no config file was generated,
  Ctrl+C produced clean startup/shutdown and exit 0. No model weights, real corpus or live service
  were touched. This verifies lifecycle, not inference; ticket 02 records real CPU/CUDA inference.
- Independent whole-branch Standards and Spec reviews: **zero findings**; record in
  `.scratch/mentor-build-0/ticket-04-review.md`.
- README documents foreground use, Linux-only service/timers and platform paths; ADR 0002 keeps
  its XDG rule for Linux. Mac hardware tests remain explicitly deferred by Drew, not passed.
