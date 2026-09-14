# 05 — Search

**What to build:** The Search section from spec 0002 §Search, replacing `Search.tsx`: the form in the list column, results in the main pane, playback in the inspector or lightbox, "Read around it" inline, and "Ask … about this" drafting a chat.

**Blocked by:** 04

**Status:** open

- [ ] `search/SearchForm.tsx` in the list column: query, scope chips (Everything, each Group, Chosen channels with a checkbox list), age Select, Search button; the v1 rules (a deleted chosen Channel or Group is dropped, not sent). `⌘K`/`Ctrl+K` anywhere switches to Search and focuses the query.
- [ ] `search/SearchResults.tsx`: header line (`n moments in {scope} for "…"`), rows per spec; play chip → `usePlayback`; `Expansion.tsx` opens the v1 expansion (cues with times, matched cue marked) under the row. Empty, loading, and error states.
- [ ] "Ask … about this" → new chat in the searched Group, else in the result's Channel, with the v1 drafted question.
- [ ] Inspector titled "Playing" in this section.
- [ ] Delete `Search.tsx` and whatever of `ui.ts` only it used. Verify: typecheck and build; `test_smoke.py` covers a search and a play; throwaway script: search in a Group, play a result in the panel and large, read around it, ask about it and see the drafted chat.
