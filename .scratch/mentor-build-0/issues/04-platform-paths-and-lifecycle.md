# 04 — Start Mentor in a terminal with platform-appropriate directories

**What to build:** A friend's first foreground run creates Mentor's directories in the expected places, prints a
usable URL, and explains that closing the terminal stops Mentor. Linux service users retain their existing setup.
(Stories 3–5.)

**Blocked by:** None — can start once the shared implementation prerequisites are resolved.

**Status:** ready-for-agent

- [ ] Resolve config and data directories through two pure functions of environment and platform, with any home
  directory input explicit. Keep platform-specific path choices in that module.
- [ ] Preserve Linux XDG defaults, including the XDG data directory as the default data location. Honour explicit
  XDG config/data variables on all platforms and retain explicit operational data-directory overrides.
- [ ] Use macOS Application Support for both config and data; use Windows roaming application data for config and
  local application data for data. Supporting these path rules does not claim a native Windows release.
- [ ] First startup creates missing config/data directories without overwriting existing configuration or databases.
  All commands resolve the same locations; failures such as unwritable directories produce useful messages.
- [ ] Foreground startup prints the loopback URL with the configured port and states that closing the terminal
  stops Mentor. Startup errors remain visible; printing a URL must not falsely claim the server is ready.
- [ ] Off Linux, service installation refuses with a pointer to `mentor serve` before attempting systemd schedule
  validation or unit creation, including when a Sync schedule was requested.
- [ ] Off Linux, ordinary foreground and Sync commands do not require systemctl. Manual UI Sync and `mentor sync`
  remain supported; do not introduce a scheduler or replacement service manager.
- [ ] Keep Linux service installation, environment handling and existing scheduled Sync behaviour working. Update
  the path/lifecycle documentation and note that ADR 0002's XDG location remains the Linux rule.

**Verification:** Pure path tables for platforms, overrides and defaults; CLI startup/refusal checks, including a
schedule argument on a non-Linux platform; existing service and standalone-Sync behaviour checks. Device execution
is verified by ticket 02, so it is not an artificial prerequisite for this path/lifecycle slice.
