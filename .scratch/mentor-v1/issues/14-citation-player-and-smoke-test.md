# 14 — Citation player and smoke test

**What to build:** Clicking a Citation in a chat answer or a search result opens an embedded YouTube player beside it at that timestamp. A single Playwright smoke test covers add Mentor → Sync → search → open Citation player. (Story 41.)

**Blocked by:** 12 — Web chat

**Status:** ready-for-agent

- [ ] Citations in chat and search open an inline YouTube embed at the cited second
- [ ] Server can run with fakes for the smoke test
- [ ] Playwright smoke test against the built bundle: add Mentor, Sync, search, click Citation, assert the player's video id and start time without depending on YouTube loading

From ticket 11 review:
- The YouTube watch URL is built in `search.py` (`_unscored`), `sources.py` (`_watch_url`), and `web/src/Search.tsx` (per-line links in `TranscriptContext`). The Citation player should replace the web links; consider one server-side builder.

From ticket 12 review:
- Saved Citations carry `video_id`, `youtube_video_id`, `seconds`, names, and a canonical `url`; answer text links are rendered by `renderMarkdown` in `web/src/Chat.tsx`, where the player should hook in (match links with the same forms `chat.citation_links` reads).

From ticket 13 review:
- `web/src/Chat.tsx` entries keep only text and tool activity: `entryOf` and the `done` handler drop `message.citations`, so the player needs them added to the assistant `Entry`.
