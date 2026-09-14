# 04 — Chats: folders, conversation, composer, Sources, player

**What to build:** The Chats section from spec 0002 §Chats, replacing `Chat.tsx`, `Conversations.tsx`, and `Player.tsx`. The v1 send/stop/error behaviour, Markdown rendering, and citation matching move over unchanged.

**Blocked by:** 03

**Status:** open

List column
- [ ] `chats/Folders.tsx`: one flat list of Groups and Channels sorted by newest chat (none last, alphabetical), collapsible, member avatars, chat count, "+" on hover; a trailing "Removed" folder for chats whose scope is gone; header "+" menu listing the live folders. Rows: title, `when · n messages`, DropdownMenu with Rename (inline Input) and Delete (confirm). Selection in url state, collapse state in session storage. Empty state when there are no chats.
- [ ] The list reloads on the v1 triggers (a chat's first question, rename, delete, Group or Channel rename or delete).

Conversation
- [ ] `ConversationView.tsx`: breadcrumb header (`scope / title`, model badge, Sources toggle), transcript (`Transcript.tsx`, `Markdown.tsx` from `renderMarkdown`/`citationOf`), tool chips, Consulted line while streaming, Source chips per message. Read-only notice when the scope is gone; loading and load-failed states as v1.
- [ ] `Composer.tsx`: Textarea (Enter asks, Shift+Enter newline), `ScopeChip` (locked once the chat exists), model Select until the first question, Ask/Stop with the v1 busy guard and error return; the model/Claude CLI notices move here from `Notices.tsx`.
- [ ] `NewChat.tsx`: "New chat in {scope}", one-line explanation, members card, "Edit group" link to the Group page; unavailable with the reason for an empty Group or a not-indexed Channel.

Sources and player
- [ ] `lib/playback.ts` (`usePlayback`: one playback, `opening` counter, `large`, opens the lightbox when the inspector is hidden); `shell/Inspector.tsx` with `PlayerCard.tsx` (real embed as v1 `CitationPlayer`, Show large, Open on YouTube, Close, "Playing large" while the lightbox is open) and `Sources.tsx` (every Citation once, grouped by `channel_id`, first-cited order, active row).
- [ ] `Lightbox.tsx`: centred 16:9 up to 64rem, caption, Esc and backdrop close; shadcn Dialog or a plain portal.
- [ ] Links in answers that match a saved Citation play it (plain click) and open YouTube with a modifier, as v1.

Verify
- [ ] Typecheck and build; `test_smoke.py` covers a chat turn with the `FakeChatEngine`; throwaway Playwright script: start a chat from a folder and from a Channel page, ask, see tool chips and Sources appear, play a source in the panel, Show large, Esc, hide the panel and play again (lightbox), rename and delete a chat, delete the Group and read the chat under Removed.
