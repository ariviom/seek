# 02 — Channel model: web rename and docs

**What to build:** Bring the v1 web UI and the documents onto the Channel model so `main` is coherent before the rebuild starts. No restyling; the sections keep their v1 look.

**Blocked by:** 01

**Status:** open

Web (v1 components, renamed)
- [ ] `api.ts`: `Channel`, `Group {channels}`, `Conversation*.scope`, `SearchResult`/`Expansion`/`Citation` with `channel_id`, calls for `/channels`, `/groups/{id}/members {channel_ids}`, `/channels/{id}/conversations`, search `channels`.
- [ ] `Mentors.tsx` → `Channels.tsx`: add by URL with the proposed name editable, rename, indexed toggle, filters, Sync, Retry failed, Videos, delete; the "attach another channel" form is gone. `Groups.tsx`: members are Channels; "Ask" disabled when empty.
- [ ] `Chat.tsx` takes a `scope` (`{kind, id}`), posts to the matching conversations route, shows the scope's name and read-only state from `scope`; `Conversations.tsx` filters by Group or Channel and shows the scope; `Search.tsx` "Ask about this" uses the searched Group or the result's `channel_id`; `Syncs.tsx` and `Player.tsx` drop `mentor_name`; `consultedVideos` keys on `channel_name`.
- [ ] Every label, hint, and empty state says channel or group; "Mentor" appears only as the app title.
- [ ] `tests/test_smoke.py` updated for the new copy and flows; `pnpm --dir web run build`, `uv run pytest -q` green.

Docs
- [ ] `CONTEXT.md`: remove Mentor and Mentor Group; define Group as a named set of Channels and the Conversation scope; relationships and the "Decisions reflected in the language" lines rewritten.
- [ ] README: wording, `mentor list` output, API paths.
- [ ] `HANDOFF.md`: conventions paragraphs say Channel; point at spec 0002 and `.scratch/mentor-v2/issues/`.
