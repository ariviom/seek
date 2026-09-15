# 04 — Chats: folders, conversation, composer, Sources, player

**What to build:** The Chats section from spec 0002 §Chats, replacing `Chat.tsx`, `Conversations.tsx`, and `Player.tsx`. The v1 send/stop/error behaviour, Markdown rendering, and citation matching move over unchanged.

**Blocked by:** 03

**Status:** done

List column
- [x] `chats/Folders.tsx`: one flat list of Groups and Channels sorted by newest chat (none last, alphabetical), collapsible, member avatars, chat count, "+" on hover; a trailing "Removed" folder for chats whose scope is gone; header "+" menu listing the live folders. Rows: title, `when · n messages`, DropdownMenu with Rename (inline Input) and Delete (confirm). Selection in url state, collapse state in session storage. Empty state when there are no chats.
- [x] The list reloads on the v1 triggers (a chat's first question, rename, delete, Group or Channel rename or delete).

Conversation
- [x] `ConversationView.tsx`: breadcrumb header (`scope / title`, model badge, Sources toggle), transcript (`Transcript.tsx`, `Markdown.tsx` from `renderMarkdown`/`citationOf`), tool chips, Consulted line while streaming, Source chips per message. Read-only notice when the scope is gone; loading and load-failed states as v1.
- [x] `Composer.tsx`: Textarea (Enter asks, Shift+Enter newline), `ScopeChip` (locked once the chat exists), model Select until the first question, Ask/Stop with the v1 busy guard and error return; the model/Claude CLI notices move here from `Notices.tsx`.
- [x] `NewChat.tsx`: "New chat in {scope}", one-line explanation, members card, "Edit group" link to the Group page; unavailable with the reason for an empty Group or a not-indexed Channel.

Sources and player
- [x] `lib/playback.ts` (`usePlayback`: one playback, `opening` counter, `large`, opens the lightbox when the inspector is hidden); `shell/Inspector.tsx` with `PlayerCard.tsx` (real embed as v1 `CitationPlayer`, Show large, Open on YouTube, Close, "Playing large" while the lightbox is open) and `Sources.tsx` (every Citation once, grouped by `channel_id`, first-cited order, active row).
- [x] `Lightbox.tsx`: centred 16:9 up to 64rem, caption, Esc and backdrop close; shadcn Dialog or a plain portal.
- [x] Links in answers that match a saved Citation play it (plain click) and open YouTube with a modifier, as v1.

Verify
- [x] Typecheck and build; `test_smoke.py` covers a chat turn with the `FakeChatEngine`; throwaway Playwright script: start a chat from a folder and from a Channel page, ask, see tool chips and Sources appear, play a source in the panel, Show large, Esc, hide the panel and play again (lightbox), rename and delete a chat, delete the Group and read the chat under Removed.

From ticket 03 review (deferred to here)
- `useChanges.act` is not re-entrant: buttons inside Radix portals (Dialog Save/Remove/Delete) sit outside the `<fieldset disabled>` lock, so a double-click sends the request twice. When the composer and dialogs are rebuilt, give `act` its own in-flight guard (or disable the confirm button while busy).
- Below 1024px the hidden list column (`hidden lg:flex`) stays mounted while the Sheet mounts a second copy, doubling live subscriptions and dialog instances; gate on `matchMedia` rather than CSS when Folders lands.
- `Conversations.tsx` encodes its filter scope as `"group:<id>"` strings; Folders replaces it, so give the scope a real type there.
- URL restore of an open chat (`App.tsx`) was added in ticket 03 to satisfy "reload restores the view"; fold it into the Folders/selection model rather than keeping a separate fetch.

From tickets 04 and 05 review
- Addressed: `useChanges` guard and `ConfirmDialog busy`; list column gated on `matchMedia`; Folders uses a typed `Scope`; URL restore folded into the selection (the view loads `?conversation=` itself); `ui.ts` gone; `AvatarStack` takes `ringClassName`. The rest is deferred to ticket 06.
