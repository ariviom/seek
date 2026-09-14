# 21 — Chat and UI loop

**What to build:** The day-to-day loop (add a Channel, watch it sync, ask, follow citations) with the friction found in the 2026-09-14 functional review removed. All small; pick up in one or two sessions.

**Blocked by:** nothing (independent of 18)

**Status:** todo

Chat
- [ ] `renderMarkdown` in `web/src/Chat.tsx` also renders headings, bullet and numbered lists, italics, and paragraph breaks; citation links keep the `citationOf` behaviour.
- [ ] Show which Videos an answer consulted: parse the `search`/`expand` tool results the stream already carries (dropped today) into a "Consulted: Mentor · Video title" line under the tool chips, instead of raw Segment ids.
- [ ] A "Sources" list under each answer from the message's saved Citations, with title, publish date, and timestamp; `conversations._citations` adds `published_on` (it already joins `videos`).
- [ ] Stop button: `DELETE /api/conversations/{id}/turn` cancels the running turn task; Close is no longer disabled while answering.
- [ ] Conversation delete and rename: `DELETE /api/conversations/{id}` and `PATCH /api/conversations/{id}` with `title`, with buttons in `Conversations.tsx`.
- [ ] "Ask about this" on a search result opens the Group's chat with a prefilled draft naming the Mentor, Video, and time (`openChat` in `App.tsx` takes a `draft`).

Sync visibility
- [ ] Channel rows show indexed/failed/excluded counts and last-synced time (`mentors._select_mentors` adds them to `Channel`).
- [ ] Videos table gets a stage filter (Failed / Excluded / All) and a per-Video retry.
- [ ] "Sync all" button in the Syncs sidebar (`POST /api/syncs` exists, unused by the UI).
- [ ] The running Sync shows the Video being fetched (title in the `sync` event).

Input and CLI
- [ ] Channel URL parsing accepts `@handle/<tab>` and `channel/UC…/<tab>` (address-bar copies); playlist filter accepts a playlist URL and extracts `list=`.
- [ ] `mentor status` (health: models, Claude CLI, Sync queue) and `mentor list` (Mentors and Channels with counts) as thin wrappers over the API/store. Document in README.

Deferred, not in this ticket: chat without a Group (auto-create a one-Mentor Group from the Mentor card); changing the model mid-Conversation; page order with Groups above Mentors; "Show more" search results; highlighting the matched cue in a result.
