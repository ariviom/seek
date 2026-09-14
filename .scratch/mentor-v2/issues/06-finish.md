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
