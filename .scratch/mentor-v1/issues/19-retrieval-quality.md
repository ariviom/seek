# 19 — Retrieval quality

**What to build:** Segments are embedded, lexically indexed, and reranked with their Video and chapter context, and search results are spread across Videos instead of stacking overlapping windows of one passage. From the 2026-09-14 functional review.

**Blocked by:** nothing (independent of 18)

**Status:** todo

- [ ] Embed each Segment as `"{video_title} — {chapter_title}\n{text}"` (chapter part omitted when None); `segments.text` stays the bare cue text so display and cue offsets are unchanged. `segments.segment_texts` joins `videos` for the title. Keep the embedding-model prompt behaviour (`encode_document`) as is.
- [ ] Rerank on the same contextual text, not the bare Segment text (`Search.search` passes `c.text` today).
- [ ] Add the title/chapter prefix to the FTS5 row too (a new indexed column, or the same composed text), so a title word matches lexically. Migration is additive; the FTS content follows via the existing triggers or a rebuild.
- [ ] Cap results per Video in `Search.search` (2 or 3) before truncating to `limit`, so adjacent overlapping windows of one passage don't fill the top 10. The cap applies after reranking and recency so the best window of each Video wins.
- [ ] A way to re-embed existing data after the passage text changes: a `mentor reindex [--channel]` command (or a Sync flag) that steps done Videos back to `segmented` and enqueues Syncs. Mentor's own index on this machine has to be rebuilt after this ticket.
- [ ] Tests: what `FakeEmbedder.passages` records includes the title; a search over one Video with many overlapping hits returns at most the cap for that Video.

Notes from the review:
- Qwen3-Embedding's document prompt is empty (verified in the cached `config_sentence_transformers.json`), so nothing frames the passage today.
- `chapter_title` is stored on the Segment but reaches neither index.
