# 07 — Set up chat in the app and see Conversation token usage

**What to build:** A friend can choose an available engine, enter and validate a key, select a default model and
understand the current Conversation's model and usage without editing a file. (Stories 16–18, 20–21, 27–29, 41–45.)

**Blocked by:** 02 — Inference devices; 06 — Selectable chat engines.

**Status:** complete

- [x] Add an accessible settings screen reachable from the app's existing shell. It shows both engines' availability,
  the selected preference and any requirement preventing that engine from running.
- [x] Let a friend enter, replace or delete an Anthropic key. Show validation progress and actionable success/failure;
  never read the key back from the server or store it in browser persistence. Explain any private-file fallback.
- [x] Present fast/deep default model choices with engine-appropriate labels and persist them through the settings
  API. An unpinned existing Conversation follows changes on its next question; a pinned one stays pinned and is
  visibly distinguished from following the default.
- [x] Keep the engine-aware composer and context visibility delivered in 06 working. Existing CLI-context
  Conversations explain why API cannot continue them; do not silently remove their saved context.
- [x] When no engine is ready, disable the composer with a direct route to settings and guidance on obtaining a key
  or logging into the CLI. Key acceptance and settings/status events update open tabs without a reload. Search,
  Library, Syncs and existing Conversation history remain accessible.
- [x] Show read-only per-model device, precision, readiness and fallback information. The rail health indicator and
  setup messages describe the active engine consistently.
- [x] Show running Conversation input, output and cache-read token totals from stored usage. Reopening/reloading a
  Conversation preserves totals; legacy unknown usage is labelled honestly. Do not invent a currency estimate.
  Include reported usage from failed/stopped turns and visibly identify incomplete totals when a provider did not
  report final usage; an unsuccessful answer must not make already-reported usage disappear.
- [x] Respect existing theme, responsive shell, keyboard navigation, focus and error/empty-state conventions. The
  screen clearly separates preferences from operational settings that belong in configuration.

**Verification:** Extend the served Playwright smoke test with no-engine composer state, usable keyless Library/
Search/Syncs, settings entry, accepted-key activation without reload, model preference persistence, pinned versus
unpinned behaviour and token readout. Use fake engines/secrets and deterministic provider responses, not live keys.
Run web typecheck, rebuild the served bundle and keep existing chat/Citation flows green.
