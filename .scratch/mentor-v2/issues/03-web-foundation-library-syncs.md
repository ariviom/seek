# 03 — Web foundation, Library, and Syncs

**What to build:** The new shell and stack from spec 0002 §Web stack and §Shell, with the Library (Channels, Groups) and Syncs sections complete. Chats and Search keep their ticket-02 components, mounted in the main pane under their rail items, so `main` stays usable between tickets.

**Blocked by:** 02

**Status:** open

Stack
- [ ] shadcn/ui installed the standard way (`components.json`, `@/` alias in `tsconfig.json` and `vite.config.ts`, `web/src/components/ui/`), zinc, CSS variables, `@custom-variant dark`; Geist via `@fontsource-variable/geist`; Barlow packages removed. `index.css` holds Tailwind, the shadcn variables, and base rules; the shop palette and `rule-ticks` go, and `ui.ts` shrinks to what the old Chats/Search still import until 04 and 05 delete them.
- [ ] `lib/url-state.ts` (`view` and selection in the query string, `replaceState`), `lib/theme.ts` (`light | dark | system`, `localStorage`, `dark` class on `<html>`), `lib/changes.ts` (`useChanges` moved), `lib/format.ts` (`formatDuration`, `stageLabels`), `lib/api.ts` and `lib/events.ts` moved.

Shell
- [ ] `App.tsx` renders Rail, ListColumn, main, and an Inspector slot; sections switch on `view`. Rail: mark, four sections (Syncs dot while one runs, from the events stream), theme toggle, health dot with tooltip.
- [ ] `shell/Notices.tsx`: server unavailable and live-updates-stopped as a top Alert in the main pane; model and Claude CLI notices rendered above the old Chat for now (04 moves them to the composer). The v1 footer is gone.
- [ ] Responsive per spec (inspector hidden below 1280, list column as a Sheet below 1024, rail as a bottom bar below 768).

Library
- [ ] List column: Tabs (Channels, Groups), the add button for the tab, rows per spec; empty states ("Add a channel to start", no Groups). "Add channel" Dialog: input → resolve → editable name → Add. "New group" Dialog.
- [ ] Channel page per spec §Library: header (avatar, name linking to YouTube, Group badges, New chat → opens the old Chat with a Channel scope; disabled with a hint when not indexed), Indexing card (filters summary, last synced, Sync now, Retry failed videos, Filters Dialog with the v1 form, Videos toggle with the v1 table restyled), `syncs/StageRule.tsx` redrawn on the shadcn palette with a legend, Rename, Stop/Resume indexing, Remove channel with confirm.
- [ ] Group page: header, New chat (disabled with a hint when empty), Channels card with Switches (each change calls `PUT /groups/{id}/members`), Rename, Delete group with confirm.

Syncs
- [ ] List with status dot and live updates (`useLiveList`), "Sync all"; detail page per spec with Retry failed videos.

Verify
- [ ] `pnpm --dir web run typecheck` and `build`; `tests/test_smoke.py` rewritten for the shell, Library, and Syncs; throwaway Playwright script: add a Channel, make a Group and toggle a member, filters Dialog round-trip, Syncs live update, theme toggle, reload restores `view` and selection.
