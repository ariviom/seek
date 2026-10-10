# Spec 0002 — Sidebar chat UI on a Channel model

Status: ready-for-agent
Supersedes the web UI parts of spec 0001 and amends its domain: see ADR 0003. Glossary terms after this spec: Channel,
Group, Video, Transcript, Segment, Citation, Sync, Pipeline stage, Conversation. "Mentor" is the product name only.
Reviewed 2026-09-14 by a `reviewer` critique; its findings are folded in below.

## Problem Statement

The v1 web UI is one long page: Search, Mentors, Groups, Conversations stacked, Syncs in a side rail, the chat opening
at the top. It works, but it reads as an admin form, not a place to ask questions, and the Mentor/Group split confused
its one user: to ask a single creator you had to make a Group of one. The prototype (branch
`t3code/sidebar-chat-ui-prototype`, commit `8d51635`, `?variant=B2`) settled the shape: a rail-and-list chat app in the
shadcn idiom, chats filed under the Group or Channel they consult, sources in an inspector with the video playing
inline.

## Solution

Rebuild the web UI as a four-section app (Chats, Search, Library, Syncs) behind an icon rail, with a list column, a
main pane, and a Sources inspector, styled with shadcn/ui's zinc theme in light and dark. Collapse the domain so a
Channel is the unit and a Group is a set of Channels, and let a Conversation be scoped to either. Keep the retrieval,
ingestion, MCP, and chat machinery as they are; only their vocabulary and scoping change.

## User Stories

### Channels and Groups
1. As a learner, I want to add a Channel by pasting a YouTube URL or handle and confirming the proposed name, so setup is one step.
2. As a learner, I want to create a named Group and switch Channels in and out of it, so I can consult "the woodworkers" as one voice.
3. As a learner, I want to rename or remove a Channel or Group from its own page, with removal cascading as in v1, so the knowledge base stays honest.
4. As a learner, I want a Channel's indexing (filters, sync, retry, stage counts, Videos with retry) on its page, so I need not hunt for it.

### Chats
5. As a learner, I want my chats filed under the Group or Channel they consult, so I find them the way I think of them.
6. As a learner, I want to start a chat from a folder, or from a Channel or Group page, and never be asked "who answers" as a separate step.
7. As a learner, I want the composer to show who answers and the model, with the model changeable only until the first question, so a chat's terms are visible and stable.
8. As a learner, I want each answer to show what it searched, which Videos it consulted, and its Sources as chips, so I can check its footing at a glance.
9. As a learner, I want a Sources panel listing every cited moment in the chat, grouped by Channel, so I can review the evidence without scrolling the answers.
10. As a learner, I want a cited moment to play inline in the panel, and to open large in a lightbox, so I can watch the technique without leaving the chat.
11. As a learner, I want to rename and delete chats, and to keep reading a chat whose Group or Channel is gone, as in v1.

### Search, Syncs, and the app
12. As a learner, I want transcript search with the v1 scopes (everything, a Group, chosen Channels) and age preference, results playable in the panel, "Read around it", and "Ask … about this" opening a drafted chat.
13. As a learner, I want Syncs listed with live status and a detail page with stage counts, the Video being fetched, the error, and retry, plus "Sync all".
14. As a learner, I want light and dark themes, following the system by default and switchable from the rail.
15. As a learner, I want the health notices of v1 (models loading or failed, Claude CLI missing, live updates stopped, server unavailable) where I will see them, without a permanent footer.

## Implementation Decisions

### Domain (ADR 0003)

Tables after schema 9:
- `channels(id INTEGER PRIMARY KEY AUTOINCREMENT, youtube_channel_id UNIQUE, name, indexed, published_after, published_before, playlist_id, most_recent)`. AUTOINCREMENT is new: a queued Sync holds a channel id, and a removed Channel's id must not be reused by a newly added one before the queue is reconciled.
- `groups(id INTEGER PRIMARY KEY AUTOINCREMENT, name UNIQUE COLLATE NOCASE)`; `group_channels(group_id, channel_id)` WITHOUT ROWID, cascades both ways, index on `channel_id`.
- `conversations`: `group_id REFERENCES groups ON DELETE SET NULL`, `channel_id REFERENCES channels ON DELETE SET NULL`, `scope_kind TEXT CHECK IN ('group','channel')`, `scope_name` (was `group_name`). Exactly one of `group_id`/`channel_id` is set at creation, checked in the store (no CHECK, since SET NULL must be allowed later). `scope_kind` survives deletion so a read-only chat still says what it consulted.
- `mentors`, `mentor_groups`, `mentor_group_members` are gone.
- `videos`, `transcripts`, `segments`, FTS5, vec0, `syncs`, `sync_lease`, `embedding_model`, `messages` are unchanged; `videos.channel_id` and `syncs.channel_id` keep referencing `channels` by name.

Migration 9 is a **data-preserving rebuild**, done the way SQLite documents:
- `MIGRATIONS` entries become `str | Callable[[sqlite3.Connection], None]`. `migrate()` runs a callable entry with `PRAGMA foreign_keys = OFF` set *before* `BEGIN`, runs `PRAGMA foreign_key_check` before `COMMIT`, and turns foreign keys back on afterwards. Shipped string entries are untouched.
- Steps: create `channels_new`, `groups`, `group_channels`, `conversations_new`; copy `channels` (same ids, same names, filters, `indexed`), `mentor_groups` → `groups` (same ids), `mentor_group_members` × `channels` → `group_channels` (a Mentor's channels each join the Group), `conversations` → `conversations_new` with `scope_kind = 'group'`, `channel_id NULL`, `scope_name = group_name`; drop `conversations`, `channels`, `mentor_group_members`, `mentor_groups`, `mentors`; rename the *new* tables to their final names (renaming the new table, never the old one, so `videos`/`syncs` references resolve again); recreate indexes. Nobody has to move a database aside.
- A fresh database runs migrations 1 to 9 in order; 1 still creates `mentors`, 9 removes it.

Store, API, tools:
- `channels.py` replaces `mentors.py`: `create_channel(info, name=None)`, `rename_channel` (also updates `conversations.scope_name` for Channel-scoped chats and publishes the `syncs` event, as `rename_mentor` did), `set_indexed`, `set_filters`, `delete_channel`, `list_channels` with the v1 counts and `last_synced_at`.
- `groups.py`: members are channel ids; `Group.channels: {id, name}[]`; `rename_group` keeps `scope_name` current as before; `group_summaries` lists Channels with searchable Video counts; `channel_summaries` for MCP.
- A `Scope` value (`kind`, `id`) is the unit passed to the chat server, `search._scope_channels`, `sources.expand`/`get_video` (their `_IN_GROUP` filter becomes a scope filter), and `conversations._citations` (Citations restricted to the scope's Videos). `conversations.create_conversation(conn, scope, model)`; the "continue" check treats a chat as read-only when `scope_kind`'s id column is NULL, not when `group_id` is NULL. `list_conversations` filters by `group_id` or `channel_id`; both given is a 422.
- `syncs.Sync` drops `mentor_name`; `sync_command`, `status_command`, and `cli` print `channel_name` only; `mentor sync --channel` resolves against `GET /channels` (server) or `channels.list_channels` (store).
- Result shapes: `SearchResult`, `Expansion`, and `Citation` drop `mentor_name` and gain `channel_id` (they already carry `channel_name`), so the UI can group by Channel and start a chat with a result's Channel without resolving by name.
- Web API: `POST /channels/resolve` (unchanged); `GET /channels`; `POST /channels {channel, name?}` (name defaults to the resolved display name); `PATCH /channels/{id}` with any combination of `name`, `indexed`, `filters`; `DELETE /channels/{id}`. `PUT /groups/{id}/members {channel_ids}`. `POST /groups/{id}/conversations` and `POST /channels/{id}/conversations` (body `{model}`); a not-indexed Channel or an empty Group answers 409 with a message. `Conversation`, `ConversationSummary`, and `ConversationDetail` all carry `scope: {kind, id: number | null, name}`. `GET /conversations?group_id=` or `?channel_id=`. `/mentors/*` routes are removed. Search takes `channels` instead of `mentors` (the "at most one of" rule and messages follow).
- MCP: `list_groups()` → Groups with their Channels (id, name, searchable Videos); `list_channels()` → every indexed Channel the same way; `search(query, group?, channels?, limit?, prefer_recent?)`; `expand` and `get_video` return `channel_id` and `channel_name`. The Conversation-bound server exposes `list_channels` (the scope's Channels) always and `list_groups` only for a Group scope, so no pseudo-Group id is invented. `INSTRUCTIONS`, `GROUP_INSTRUCTIONS` (which gains a Channel-scope variant), `GROUNDED_ADVISOR`, every tool description, and the `sql` tool's table list say Channel and name `groups`/`group_channels`.
- Chat system prompt names the scope: "the Group {name} (Channels: …)" or "the Channel {name}".
- Docs: `CONTEXT.md` glossary drops Mentor and Mentor Group, adds Group and the Conversation scope, and rewrites the "Decisions reflected in the language" lines; README and HANDOFF wording follow.

### Web stack
- React 19, Vite, Tailwind v4, TypeScript with no `any`, as before. **shadcn/ui** added the standard way (`components.json`, `@/` alias, `web/src/components/ui/`), zinc base colour, CSS variables, class-based dark mode via `@custom-variant dark`. Components used: Button, Badge, Input, Textarea, Select, Tabs, Popover, DropdownMenu, Dialog, Sheet, Switch, Tooltip, ScrollArea, Separator, Alert. Icons from lucide-react. No toasts.
- Type: Geist (`@fontsource-variable/geist`); Barlow and Barlow Condensed removed. Base size 14px; titles `text-sm font-medium`; page headings `text-lg font-semibold tracking-tight`.
- Avatars are initials from the name on a deterministic tint (Channels round, Groups square). A Channel shows its YouTube avatar instead when one is known (kept from Add channel and each Sync's listing, never fetched per page view), and its initials when none is or the image fails to load (Drew, 2026-10-10).
- No router library. A `useUrlState` hook keeps `view` (`chats | search | library | syncs`) and the selection (`conversation`, `channel`, `group`, `sync`, `tab`) in the query string with `history.replaceState`, so reload and links restore the view. Relative URLs and the reverse-proxy prefix keep working as in v1.
- Theme: `dark` class on `<html>`, chosen from `localStorage` (`theme`: `light | dark | system`), default `system`.

### Shell
- Rail (48px): product mark, Chats, Search, Library, Syncs (a dot while a Sync runs), then theme toggle and a health dot (green ready; amber loading with a tooltip; red failed or Claude CLI missing, opening the notice).
- List column (260px, `bg-sidebar`): the section's list and its actions. Main pane: a 48px header (title, badges, actions) and scrolling content at `max-w-3xl`. Inspector (300px, Chats and Search only): player card and Sources; hidden with its header button, remembered per session.
- Responsive: below 1280px the inspector starts hidden; below 1024px the list column becomes a Sheet opened from the header; below 768px the rail becomes a bottom bar. Keyboard: `⌘K`/`Ctrl+K` switches to Search and focuses the query; Esc closes the lightbox, sheet, and menus; rows and folder headers are buttons with visible focus.
- Notices: server unavailable and live-updates-stopped render as a top Alert in the main pane; model loading/failed and Claude CLI state render above the composer when they block asking.

### Chats
- Folders: one flat list of Groups and Channels, sorted by their newest chat (folders with none last, alphabetical), each collapsible, with member avatars (stack for a Group, one for a Channel), a chat count, and a "+" on hover for a new chat there. Chats whose scope was deleted sit in a trailing "Removed" folder, read-only, named by `scope_name` and `scope_kind`. The header "+" opens a menu of the live folders. Chat rows: title (given title or first question), `when · n messages`, a row menu (Rename, Delete).
- Conversation view: breadcrumb header (`scope / title`, model badge, Sources toggle); transcript: user bubbles right, answers with tool chips (Badge outline), a one-line "Consulted n videos: …" (only while streaming, as v1; `consultedVideos` keys on `channel_name`), Markdown via the existing `renderMarkdown` and `citationOf`, then Source chips (avatar, title, time) for the message's saved Citations. Clicking a chip or a matching link plays it. A deleted scope shows the read-only notice and no composer.
- Composer: card with textarea (Enter asks, Shift+Enter newline), a scope chip (locked once the chat exists), model select (locked after the first question), Ask/Stop. The v1 send/stop/error-return behaviour is kept verbatim.
- New chat screen: "New chat in {scope}", one line explaining who answers, a card listing the members with their Video counts, and "Edit group" for a Group. New chat is unavailable, with the reason shown, for an empty Group or a Channel that is not indexed.
- Sources inspector: player card (real `youtube-nocookie` embed at the second, autoplay, remount on replay) with Show large, Open on YouTube, Close; below it every Citation of the chat once, grouped by Channel (`channel_id`), in first-cited order. Lightbox: centred 16:9 up to 64rem over `bg-black/80`, caption with channel, date, from-time, Open on YouTube; Esc and backdrop close; while open, the card shows "Playing large" so two players never run. When the inspector is hidden, playing opens the lightbox.

### Search
- List column: query, scope chips (Everything, each Group, Chosen channels with checkboxes), age select, Search button. Main: result rows (text, play chip, channel avatar and name, title, chapter, date, Read around it); the expansion opens inline under the row as in v1. Inspector titled "Playing".
- "Ask … about this" drafts the v1 question (Channel, Video, time) into a new chat: in the searched Group when the scope is a Group, else in the result's Channel (`channel_id`). No menu is needed.

### Library
- Tabs: Channels first, then Groups; the add button for the tab below the tabs ("Add channel" opens a Dialog: URL or handle → resolve → editable name → Add; "New group" opens a Dialog with a name). Rows: Channel with avatar, `n videos · synced when`; Group with a stack and its member names.
- Channel page: avatar, name linking to the channel on YouTube (external icon), the Groups it is in as badges, New chat; an Indexing card (filters summary, last synced, Sync now, Retry failed videos, Filters, Videos) with the stage rule and legend; Filters opens the v1 form in a Dialog; Videos toggles the v1 table (stage filter, per-Video retry) under the card; footer buttons Rename, Stop indexing / Resume indexing, Remove channel (confirm Dialog).
- Group page: square avatar, name, `n channels answer together`, New chat (disabled with a hint when empty); a Channels card with a Switch per Channel; Rename, Delete group.

### Syncs
- List: channel, status dot, when; live from the SSE stream as in v1. Detail: title, status line, fetching line, error alert, stage rule with legend, Retry failed videos. "Sync all" in the list header. There is no stop endpoint and none is added.

### Componentisation
```
web/src/
  main.tsx, App.tsx               shell, url state, health, theme
  lib/api.ts, lib/events.ts        typed calls (new shapes), SSE hooks (from v1)
  lib/url-state.ts, lib/theme.ts, lib/playback.ts, lib/changes.ts (useChanges from ui.ts), lib/format.ts
  components/ui/*                  shadcn
  shell/Rail.tsx, ListColumn.tsx, MainHeader.tsx, Inspector.tsx, Notices.tsx
  chats/Folders.tsx, ConversationView.tsx, Transcript.tsx, Markdown.tsx, Composer.tsx, ScopeChip.tsx,
        NewChat.tsx, Sources.tsx, PlayerCard.tsx, Lightbox.tsx
  search/SearchForm.tsx, SearchResults.tsx, Expansion.tsx
  library/ChannelList.tsx, ChannelPage.tsx, AddChannelDialog.tsx, ChannelFiltersDialog.tsx, VideosTable.tsx,
          GroupList.tsx, GroupPage.tsx, NewGroupDialog.tsx
  syncs/SyncList.tsx, SyncPage.tsx, StageRule.tsx
```
`Chat.tsx`, `Conversations.tsx`, `Mentors.tsx` (renamed `Channels.tsx` in the interim), `Groups.tsx`, `Search.tsx`,
`Syncs.tsx`, `Videos.tsx`, `ChannelFilters.tsx`, `Player.tsx`, `ui.ts`, and `web/src/prototype/` are deleted when their
replacements land. Logic worth keeping moves, not rewritten: `renderMarkdown`, `citationOf`, `consultedVideos`, the
send/stop flow, `useChanges`, `useServerEvents`, `useLiveList`, `useLiveUpdatesStopped`, `filtersSummary`,
`formatDuration`, `stageLabels`. `StageRule` is redrawn on the shadcn palette (emerald done, amber in progress, red
failed, striped excluded) and the `rule-ticks` utility and shop colours go with `ui.ts`.

## Testing Decisions
- Backend: the v1 harness and tests renamed to the Channel model; new tests for migration 9 on a populated schema-8 database (a Mentor with two Channels in one Group, one Conversation with messages) and on a fresh database; `POST /channels/{id}/conversations` including the 409s; a Channel-scoped chat whose `search`, `expand`, and `get_video` see only that Channel and whose saved Citations are restricted to it; `list_channels`; `scope` on all three conversation shapes; `rename_channel` updating `scope_name`.
- Web: `pnpm --dir web run typecheck` and build. `tests/test_smoke.py` (the Playwright test that builds the bundle) is kept green by every ticket and rewritten for the new UI as its sections land. Throwaway Playwright scripts against `create_app` with fakes (the v1 way) cover the flows each ticket names.
- Manual: the served bundle behind the Cloudflare hostname (relative base, prefix) after `pnpm --dir web run build`.

## Out of Scope
- A router library, multi-user state, mobile-first layouts beyond the breakpoints above.
- Changing retrieval, segmentation, ingestion, MCP transport, or remote access.
- Storing the "Consulted" line (deferred from ticket 21 stays deferred).
- Chats scoped to an ad-hoc set of Channels ("pick channels, save as a group": prototype B3). A Group is the way to consult several.

## Further Notes
- The prototype's `shad/ui.tsx` primitives mirror shadcn's recipes; the real components come from shadcn, not from the prototype. The prototype is a reference for layout, copy, and states, not code to promote.
- Ticket order: the Channel model lands first (backend, then the web rename) so the UI is built once against the final API, and `main` works after every ticket.
