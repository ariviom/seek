# 05 — Search

**What to build:** The Search section from spec 0002 §Search, replacing `Search.tsx`: the form in the list column, results in the main pane, playback in the inspector or lightbox, "Read around it" inline, and "Ask … about this" drafting a chat.

**Blocked by:** 04

**Status:** done

- [x] `search/SearchForm.tsx` in the list column: query, scope chips (Everything, each Group, Chosen channels with a checkbox list), age Select, Search button; the v1 rules (a deleted chosen Channel or Group is dropped, not sent). `⌘K`/`Ctrl+K` anywhere switches to Search and focuses the query.
- [x] `search/SearchResults.tsx`: header line (`n moments in {scope} for "…"`), rows per spec; play chip → `usePlayback`; `Expansion.tsx` opens the v1 expansion (cues with times, matched cue marked) under the row. Empty, loading, and error states.
- [x] "Ask … about this" → new chat in the searched Group, else in the result's Channel, with the v1 drafted question.
- [x] Inspector titled "Playing" in this section.
- [x] Delete `Search.tsx` and whatever of `ui.ts` only it used. Verify: typecheck and build; `test_smoke.py` covers a search and a play; throwaway script: search in a Group, play a result in the panel and large, read around it, ask about it and see the drafted chat.

From ticket 03 review (deferred to here)
- `ui.ts` should go entirely with `Search.tsx`; check nothing under `shell/` or `library/` still imports a class constant from it.
- `Avatar.tsx`'s `AvatarStack` ring is hard-coded to `ring-sidebar`; the first stack drawn on `bg-card` (a result row or a Sources group) needs a `ring` colour prop or `ring-background`.
- The Sync page's "Retry failed videos" is shown only for a finished Sync with failures; the spec sentence is unconditional. Decide when the Syncs detail gets its final pass alongside the inspector work.

From tickets 04 and 05 review
- Addressed: `useChanges` guard and `ConfirmDialog busy`; list column gated on `matchMedia`; Folders uses a typed `Scope`; URL restore folded into the selection (the view loads `?conversation=` itself); `ui.ts` gone; `AvatarStack` takes `ringClassName`. The rest is deferred to ticket 06.
