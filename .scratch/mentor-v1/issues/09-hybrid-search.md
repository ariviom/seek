# 09 — Hybrid search

**What to build:** From the web UI, ask a Mentor Group, a set of Mentors, or everything a natural-language question. Results are the best-matching Segments, each with Mentor, Channel, Video title, publish date, chapter, text, and a Citation link to the exact matched moment. Newer Videos win near-ties. (Stories 22–27; uses fakes.)

**Blocked by:** 03 — Mentor Groups; 05 — Sync: segmentation and embedding

**Status:** ready-for-agent

- [ ] Vector top 50 is scoped in the KNN query itself (Channel id metadata), so a small Mentor in a large corpus still gets hits; BM25 top 50 over the same scope
- [ ] Reciprocal Rank Fusion (k=60) is a pure function with tests; the fused list is truncated to the top 50 before reranking
- [ ] Recency (a pure function with tests): half-life decay on a sigmoid-normalised reranker score, measured from now; `off | gentle | strong` half-lives come from config with documented defaults; default `gentle`
- [ ] Scope: exactly one of Group (id or name), Mentor ids, or nothing; passing both is a validation error; not-indexed Channels are excluded everywhere
- [ ] Matched cue = the Segment cue with the highest query-term overlap, else Segment start; Citation URL uses that time
- [ ] Result shape matches the spec; search API and a UI results page
- [ ] API tests: scoping, not-indexed exclusion, recency ordering on planted near-ties, citation fields

From ticket 03 review: Group names may be all digits (e.g. "12"), so `group` accepting "id or name" is ambiguous when a Group named "12" and a Group with id 12 both exist. Decide the rule here (e.g. JSON number = id, string = name) and document it.
