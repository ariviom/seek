# 09 — Hybrid search

**What to build:** From the web UI, ask a Mentor Group, a set of Mentors, or everything a natural-language question. Results are the best-matching Segments, each with Mentor, Channel, Video title, publish date, chapter, text, and a Citation link to the exact matched moment. Newer Videos win near-ties. (Stories 22–27; uses fakes.)

**Blocked by:** 03 — Mentor Groups; 05 — Sync: segmentation and embedding

**Status:** done

- [x] Vector top 50 is scoped in the KNN query itself (Channel id metadata), so a small Mentor in a large corpus still gets hits; BM25 top 50 over the same scope
- [x] Reciprocal Rank Fusion (k=60) is a pure function with tests; the fused list is truncated to the top 50 before reranking
- [x] Recency (a pure function with tests): half-life decay on a sigmoid-normalised reranker score, measured from now; `off | gentle | strong` half-lives come from config with documented defaults; default `gentle`
- [x] Scope: exactly one of Group (id or name), Mentor ids, or nothing; passing both is a validation error; not-indexed Channels are excluded everywhere
- [x] Matched cue = the Segment cue with the highest query-term overlap, else Segment start; Citation URL uses that time
- [x] Result shape matches the spec; search API and a UI results page
- [x] API tests: scoping, not-indexed exclusion, recency ordering on planted near-ties, citation fields

From ticket 03 review: Group names may be all digits (e.g. "12"), so `group` accepting "id or name" is ambiguous when a Group named "12" and a Group with id 12 both exist. Decide the rule here (e.g. JSON number = id, string = name) and document it.

From ticket 05 review:
- Scope KNN with `segment_vectors.channel_id = ?` or `IN (...)` in the MATCH query itself; sqlite-vec 0.1.9 filters metadata before k (checked). Excluded Videos have no Segments or vectors (ticket 06 deletes them on exclusion), so Channel scoping is enough.
- Matched cue: split `segments.text` at the stored cue offsets (`segments.cues` JSON, `[{start, offset}]`) to score each cue.
- `ModelUnavailable` is already mapped to 503 in `app.ERROR_STATUS`.

Done note: `POST /api/search` with `{query, group?, mentors?, limit?, prefer_recent?}` returns `SearchResult`s: segment id, text, start and matched seconds, Video id and YouTube id, title, publish date, chapter, Channel and Mentor names, score, and a `watch?v=…&t=Ns` URL. **Group rule:** a JSON number is a Group id and a JSON string is a Group name (case-insensitive), so a Group named "12" is always reachable by name. Passing both `group` and `mentors`, an empty `mentors` list, a blank query, or `limit` outside 1–50 is a 422; an unknown Group or Mentor is a 404. `search.Search` (built in `create_app`, shared with ticket 11) resolves the scope to indexed Channel ids, embeds the query, takes the vector top 50 (`channel_id IN (...)` inside the KNN query) and the BM25 top 50 (each query word quoted and OR'ed, so FTS5 syntax in a question is inert), fuses them with `ranking.fuse` (RRF k=60, top 50), reranks, and applies `ranking.recency_score`: sigmoid of the reranker score, halved per half-life of age from today's UTC date. Only Segments of `done` Videos are searchable. Half-lives are `gentle_recency_half_life_days` (3650, the default level) and `strong_recency_half_life_days` (1095). `ranking.matched_seconds` counts Porter-stemmed query words per cue (as FTS5's `porter` tokenizer does, via `snowballstemmer`), ignoring common words; the earliest best cue wins, else the Segment start. `create_app` takes a `reranker` port; `mentor serve` passes a stub `SentenceTransformerReranker` that raises ModelUnavailable until ticket 10. The web UI has a Search section at the top of the page (Every Mentor, a Group, or ticked Mentors; recency level; results with a "Watch at m:ss" Citation link).

Review fixes (both axes): lexical hits were returned for Segments of Videos still in the pipeline (segmented but not embedded, or failed at embedding); the matched cue folded only plurals, so a stemmed BM25 hit cited the Segment start; no test proved the lexical side contributes (now a jargon test beyond the vector top 50, with FTS5 syntax in the query). The Search form no longer sends a deleted Group, the Reranker port states it returns raw logits, queries are NFC-normalised, and the result assembly no longer duplicates `SearchResult`.

From ticket 09 review (deferred):
- `search._scope_channels` repeats `groups.set_members`' Mentor-existence check.
- Scope and candidates are read in two `Database.run` calls, so a Channel un-indexed in between is searched once.
- `strong` lets a new weak match beat a two-year-old strong one (tested); retune with real reranker logits in ticket 10.
