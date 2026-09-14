# 21 — Chat and UI loop

**What to build:** The day-to-day loop (add a Channel, watch it sync, ask, follow citations) with the friction found in the 2026-09-14 functional review removed. All small; pick up in one or two sessions.

**Blocked by:** nothing (independent of 18)

**Status:** done

Chat
- [x] `renderMarkdown` in `web/src/Chat.tsx` also renders headings, bullet and numbered lists, italics, and paragraph breaks; citation links keep the `citationOf` behaviour.
- [x] Show which Videos an answer consulted: parse the `search`/`expand` tool results the stream already carries (dropped today) into a "Consulted: Mentor · Video title" line under the tool chips, instead of raw Segment ids.
- [x] A "Sources" list under each answer from the message's saved Citations, with title, publish date, and timestamp; `conversations._citations` adds `published_on` (it already joins `videos`).
- [x] Stop button: `DELETE /api/conversations/{id}/turn` cancels the running turn task; Close is no longer disabled while answering.
- [x] Conversation delete and rename: `DELETE /api/conversations/{id}` and `PATCH /api/conversations/{id}` with `title`, with buttons in `Conversations.tsx`.
- [x] "Ask about this" on a search result opens the Group's chat with a prefilled draft naming the Mentor, Video, and time (`openChat` in `App.tsx` takes a `draft`).

Sync visibility
- [x] Channel rows show indexed/failed/excluded counts and last-synced time (`mentors._select_mentors` adds them to `Channel`).
- [x] Videos table gets a stage filter (Failed / Excluded / All) and a per-Video retry.
- [x] "Sync all" button in the Syncs sidebar (`POST /api/syncs` exists, unused by the UI).
- [x] The running Sync shows the Video being fetched (title in the `sync` event).

Input and CLI
- [x] Channel URL parsing accepts `@handle/<tab>` and `channel/UC…/<tab>` (address-bar copies); playlist filter accepts a playlist URL and extracts `list=`.
- [x] `mentor status` (health: models, Claude CLI, Sync queue) and `mentor list` (Mentors and Channels with counts) as thin wrappers over the API/store. Document in README.

Deferred, not in this ticket: chat without a Group (auto-create a one-Mentor Group from the Mentor card); changing the model mid-Conversation; page order with Groups above Mentors; "Show more" search results; highlighting the matched cue in a result.

## Outcome (2026-09-14)

Web: `renderMarkdown` renders headings, lists, paragraphs, and italics; tool results from `search`/`expand` give a
"Consulted" line while an answer streams; answers list their Citations as Sources; Stop calls
`DELETE /api/conversations/{id}/turn`; Conversations can be renamed and deleted; "Ask about this" opens the searched
Group's chat (else the first Group with that Mentor) with a drafted question. Channel rows show counts, reloaded at most
once a second on `sync`/`videos` events; Videos filter by stage with per-Video Retry; Syncs has "Sync all" and the title
being fetched. CLI: `mentor status` and `mentor list` (`status_command.py`) use the server when it answers, else the
store. Verified in Chromium with a throwaway Playwright script against `create_app` with fakes.

From ticket 21 review (deferred, not owned by a later ticket):
- The "Consulted" line isn't saved (`ToolUse` holds arguments only), so a reopened Conversation doesn't show it. Its
  parser (`consultedVideos`) depends on `claude_chat._result_text` joining one pretty-printed JSON block per result;
  checked against the MCP SDK, not the real Claude CLI.
- "Ask about this" finds the Group by Mentor name, since `SearchResult` has no `mentor_id`; the fallback to the first
  Group holding the Mentor goes beyond the ticket.
- `Chat.stop` answers 404 "isn't answering" for a Conversation whose turn is starting (`_busy` set, task not yet
  created), while delete answers 409 for the same state; "not answering" is arguably a Conflict, and stop doesn't check
  the Conversation exists.
- `Sync.fetching` lives on the stored `Sync` dataclass but is only set on one published event; `GET /api/syncs`
  always returns null.
- `mentors._CHANNEL_SQL` re-encodes the derived stage rule that `videos._STAGE_SQL` owns.
- `Videos.tsx`, `Syncs.tsx`, and `Chat.tsx` each hand-roll the busy/error shape `useChanges` provides.
- `Mentors` loads twice at mount (initial load and the stream's `ready`).
- `status_command.py` holds `list` too and raises `SyncCommandError`; its `ValidationError` mapping and its `_Health`
  shape duplicate `sync_command` and the app's Health model. `mentor status` without a server reports a Sync a crashed
  server left `running` as running.
- `cli.py`'s `reindex` parser repeats `sync`'s `--all`/`--channel` group; `syncs_api` takes `SyncOptions | None`.
- `videos.clear_failure` (one Video) sits next to `clear_failures` (a Channel) with a different contract.
