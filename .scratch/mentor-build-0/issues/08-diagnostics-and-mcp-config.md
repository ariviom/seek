# 08 — Print pasteable diagnostics and local MCP registration

**What to build:** A friend can give Drew one safe support block and register Mentor's tools with an agent that
supports streamable HTTP over loopback. Both commands explain the situation when Mentor is not running.
(Stories 36–39, 46.)

**Blocked by:** 02 — Inference devices; 06 — Selectable chat engines (which includes preferences and platform paths).

**Status:** ready-for-agent

- [ ] `mentor doctor` prints Mentor/Python versions, platform, per-model device/precision/state/fallback, resolved
  config/data locations, effective preferences and operational settings, secret-store kind/reason, both engine
  states, yt-dlp version and JS runtime availability, schema version, row counts and recent errors.
- [ ] Recent errors are drawn from model states, failed Videos and failed Syncs already stored. Do not add a new log
  buffer, telemetry or any provider health request.
- [ ] Redact API credentials, YouTube extractor argument values and the cookie file path from every part of the
  block, including nested settings, fallback reasons and stored error text. Include no raw environment/config dump;
  also avoid exposing credential-bearing browser-cookie configuration.
- [ ] Use live server state when available; without a server, read what can safely be inspected locally and label
  unavailable runtime information. Do not load models, validate keys, start Syncs, create a database or silently
  migrate a user's database just to diagnose it. A first install with no database still yields useful output.
- [ ] Missing tools, unreadable local state or an unavailable keychain do not prevent printing the rest of the safe
  report. Do not expose unsanitized exceptions on stderr as a side channel around redaction.
- [ ] `mentor mcp-config` emits a parseable client configuration using the configured loopback port and streamable
  HTTP endpoint, with copyable registration guidance for Claude Code or equivalent supported clients. Keep human
  guidance separate from machine-readable configuration.
- [ ] Say plainly that this loopback configuration does not register a Claude Desktop custom connector, which needs
  a public URL under the spec's supported path. Remote Access/OAuth configuration remains in the older ticket.
- [ ] With no server, still print the configuration and tell the friend to run `mentor serve`; do not claim a live
  connection. Confirm listing tools and making a scoped search through the emitted local endpoint with no API key.

**Verification:** CLI tests against a served app and an unused port; absent/unreadable database and unavailable tool
cases. Seed distinctive secrets in keys, extractor arguments, cookie paths and model/Video/Sync error messages, and
assert none appear anywhere in captured stdout/stderr. Parse emitted MCP configuration and use the configured endpoint.
