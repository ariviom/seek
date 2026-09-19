# 10 — Ship and verify the documented friends installation path

**What to build:** A friend on Apple Silicon can follow the README, install from the public repository with uv,
run Mentor, ingest a small Channel, ask a cited question and later update with one command. Linux retains its
supported service path. (Stories 1–2, 8, 33, 40, 47; final verification of the full build.)

**Blocked by:** 03 — MPS retrieval comparison; 07 — Chat settings UI; 08 — Diagnostics and MCP configuration;
09 — First Channel and honest Sync progress.

**Status:** ready-for-agent

**Mac verification deferred (Drew, 2026-09-19):** Apple Silicon hardware is unavailable. The Mac-specific
execution and measurement checks below remain unchecked and deferred; retain them for when hardware is
available. Continue implementation and non-Mac verification in ticket order without claiming a verified Mac
release. Ticket 03's hardware-dependent comparison is likewise parked, not passed.

- [ ] Provide a per-operating-system README path for Apple Silicon macOS and Linux. State Python requirements and
  how uv supplies the compatible interpreter; enumerate uv, Node 22 (at least the web build's required minor), pnpm
  and any VCS prerequisite of the chosen public-repository install command, each with a check and rough setup time.
  Windows path resolution is preparatory work, not a claim of supported Windows installation.
- [ ] Verify prerequisites before the install/build command, with an explicit stop and remedy for a missing or
  unsupported version. Keep build-hook diagnostics clear as a backstop. Source installation builds the web bundle;
  do not commit a generated bundle to remove Node/pnpm prerequisites.
- [ ] Configure yt-dlp to accept the installed Node runtime as well as Deno. Verify the Node-only caption path on the
  friend setup and preserve Drew's Deno path. Align runtime guidance/availability reporting so Node-only users are
  not incorrectly told Deno is mandatory.
- [ ] Pin the tested yt-dlp version exactly in project metadata and update the lockfile consistently. Verify the
  version installed from the repository in an isolated uv tool environment; a repository build does not use the
  development lockfile to choose runtime dependencies.
- [ ] Make the intended public repository/release revision available and put its actual install command in the
  README. Verify unauthenticated retrieval, wheel construction and bundled web assets, not an editable local
  checkout. Repository publication must be a deliberate release action with its contents reviewed first.
- [ ] Verify the documented `uv tool upgrade` command against that installation source and a newer repository
  revision, including delivery of a changed yt-dlp pin. Record exact tested commands and versions; do not assume a
  VCS source refresh works merely because package-index upgrades do.
- [ ] Document foreground URL/start/stop, conventional paths, first-run model download size and approximate time,
  and cached offline local use. State that closing the terminal stops Mentor, that off-Linux Sync is manual, and
  that provider chat/YouTube ingestion still need connectivity.
- [ ] Document UI-only preference/key setup, the configuration/preferences/secrets separation and macOS keychain
  allow/always-allow prompts after interpreter replacement during upgrade. Include keyless capabilities and the
  supported local MCP configuration path without promising Desktop loopback support.
- [ ] Measure ingestion on a real small Channel on the Mac. Record hardware, model devices, video duration,
  catalogue size, elapsed time and download versus ingestion time. Publish a clearly rough time per hour of Video,
  explaining variation from caption pacing and video count rather than copying the roadmap's speculative rate.
- [ ] On a Mac using the published install path, begin without an API key or Claude CLI, start Mentor, add and Sync
  a friend-chosen small Channel, verify keyless search/MCP, configure a key in the UI, ask a question with a working
  Citation, reopen the Conversation, inspect usage, and produce redacted diagnostics. Check cached startup/search
  offline and the final revision against the unchanged retrieval regression fixture.
- [ ] Verify stop/restart with an unfinished Sync and one failed Video, and verify an upgrade retains config,
  database, preferences and access to the stored key. Record the manual results and any supported-path limitations.
- [ ] Update the handoff with release revision, checks and remaining work. Include a lightweight monthly check-in
  prompt asking each friend which surface they used (web or agent/MCP), which Channel they chose, and whether they
  kept using it. No telemetry or usage-reporting infrastructure is added; five retained users is a follow-up product
  outcome, not an automated test that this ticket can claim on release day.

**Verification:** Normal automated checks plus an isolated repository-source wheel/install/upgrade check. Actual Mac
install, ingestion, cited chat and regression results are mandatory. Document prerequisite failures observed at the
preflight step and run both Node-only and existing Deno paths. A developer checkout or unit-test pass cannot close it.

**Closure precondition:** Mac access and an accessible public repository. No PyPI publication, native shell,
installer, signing, auto-update or packaging-spike dependency is introduced.
