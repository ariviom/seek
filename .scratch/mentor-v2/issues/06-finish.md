# 06 — Finish: remove what is left of v1, polish, verify end to end

**What to build:** Delete the leftovers, review states and keyboard behaviour across sections, and verify the whole UI against the served bundle.

**Blocked by:** 05

**Status:** open

- [ ] Delete `web/src/prototype/`, any remaining v1 section component, `ui.ts`, and the `?variant=` gate in `main.tsx`; the bundle has no Barlow and no prototype code.
- [ ] Keyboard and focus: visible focus on every row and button; Esc closes lightbox, sheet, menus; `⌘K`; Tabs and DropdownMenu keyboard behaviour from shadcn.
- [ ] Empty and error states reviewed together (each was built by its ticket): no Channels, no chats, a folder with none, no results, Sync failed, server unavailable, live updates stopped, models loading, Claude CLI missing.
- [ ] Responsive check at 1440, 1280, 1024, 768, and 390 wide; `prefers-reduced-motion` respected.
- [ ] README: the UI section and screenshots; themes and the lightbox.
- [ ] Verify against the real server (`mentor serve` from the worktree after `pnpm --dir web run build`), then through the Cloudflare hostname for the prefix and relative base.
- [ ] `/code-review` on the whole `mentor-v2` branch against `main`; fix in scope; deferred findings appended here.

From tickets 04 and 05 review (deferred to here)
- ⌘K below 1024px switches to Search but can't focus the query: the form lives in the closed Sheet (`MainHeader` owns its open state). Open the Sheet, then focus.
- A `?conversation=` that fails to load is not cleared from the URL (ticket 03's restore did); the breadcrumb comes from `useConversations` in `App`, so it is blank until that list loads and stays blank if it fails. Consider moving the header into `ConversationView`, which has the detail (ticket 04 placed it there).
- From ticket 03, still undecided: the Sync page's "Retry failed videos" shows only for a finished Sync with failures.
- Scope chips in `SearchForm` are `aria-pressed` buttons behaving as one choice; radio semantics would be truer. Inline chat rename cancels only with Esc. "Show large" stays enabled while large. Source chips are buttons, so a modified click no longer opens YouTube as v1's source links did.
- Every empty folder shows "No chats here yet", which is noisy with many Channels; review with the other empty states. Group avatar stacks are round in Folders and `ScopeChip` but square in `GroupList` (spec: Groups square).
- Cleanups (judgement calls): `MainHeader` keeps its own `(min-width: 1024px)` listener beside `lib/media.ts`; `useConversations` has two reload counters (`version` and `reload`); `sourcesOf` runs in `App` for the badge and again in `Sources`; `liveScope` for the open chat runs in `App` and `ConversationView`; `Composer` takes 14 props (model and stop props travel together); `ScopeChip` could take a `LiveScope`.
- Model notices show above the composer and on Search; Chats with no chat open shows none.
