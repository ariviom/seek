# 05 — Store validated API keys and persistent user preferences

**What to build:** Mentor can accept and validate a friend's Anthropic key without returning it, keep it in the OS
keychain or a private fallback file, and persist engine/provider/model preferences through typed API endpoints.
This is a complete API-verifiable setup slice for the selectable engine and settings UI. (Stories 17–18, 28, 30.)

**Blocked by:** 04 — Start Mentor in a terminal with platform-appropriate directories.

**Status:** ready-for-agent

- [ ] Introduce the spec's single new port, `Secrets`, with get/set/delete by name, injected beside existing ports.
  Use `keyring` in production and a fake Secrets implementation through the running-app test harness.
- [ ] Fall back to an owner-only file in the resolved data directory for missing, locked or refused keychain
  backends and other keyring failures. Cover read, write and deletion failures, persist across restarts and expose
  the effective store and a safe fallback reason for future diagnostics.
- [ ] Replacement and deletion are coherent across stores: a stale fallback or keychain copy must not silently
  become the active credential again after deletion or after a backend recovers.
- [ ] Never use `ANTHROPIC_API_KEY` as a credential fallback, including the provider SDK's implicit environment
  lookup. Supply only the explicitly stored credential when authenticating.
- [ ] The key-entry endpoint makes one cheap authenticated provider call and reports presence and validity only.
  An authentication rejection is distinguished from transient network/rate-limit/provider failure; do not mark an
  unreachable provider as an invalid credential or claim unverified success.
- [ ] No response, settings read, event, validation error or logged credential representation includes the raw key.
  Support replacing and deleting a stored key without a restart.
- [ ] Preserve last-known validation state without health-time provider requests. Publish credential-state changes
  that ticket 06 can use for engine status, including invalidation after an authentication failure during a turn.
- [ ] Add one additive migration for typed preference rows: engine, Anthropic provider and model choice. Validate
  supported values; persist across restart; publish a settings-change event after successful writes.
- [ ] Keep preferences separate from operational configuration and credentials. Document the rule: configuration
  file for operations, settings table for preferences, keychain/fallback store for secrets.
- [ ] This slice leaves current CLI chat usable. Preferences become authoritative for turn selection in ticket 06;
  do not partially switch the running chat engine or rename health here.

**Verification:** Running-app API tests for storage, redaction, validation, deletion, restart persistence, settings
validation and events. Exercise the real Anthropic SDK with scripted HTTP responses for validation, without live
network calls or an extra port. Unit-test fallback behaviour with an unavailable/locked/refused backend and verify
private file permissions. Cover migration of an existing database without rewriting shipped migrations.
