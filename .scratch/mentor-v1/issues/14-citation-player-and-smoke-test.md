# 14 — Citation player and smoke test

**What to build:** Clicking a Citation in a chat answer or a search result opens an embedded YouTube player beside it at that timestamp. A single Playwright smoke test covers add Mentor → Sync → search → open Citation player. (Story 41.)

**Blocked by:** 12 — Web chat

**Status:** ready-for-agent

- [ ] Citations in chat and search open an inline YouTube embed at the cited second
- [ ] Server can run with fakes for the smoke test
- [ ] Playwright smoke test against the built bundle: add Mentor, Sync, search, click Citation, assert the player's video id and start time without depending on YouTube loading
