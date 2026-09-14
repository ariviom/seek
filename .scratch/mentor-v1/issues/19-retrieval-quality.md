# 19 — Retrieval quality

**What to build:** Segments are embedded, lexically indexed, and reranked with their Video and chapter context, and search results are spread across Videos instead of stacking overlapping windows of one passage. From the 2026-09-14 functional review.

**Blocked by:** nothing (independent of 18)

**Status:** done

- [x] Embed each Segment as `"{video_title} — {chapter_title}\n{text}"` (chapter part omitted when None); `segments.text` stays the bare cue text so display and cue offsets are unchanged. `segments.segment_texts` joins `videos` for the title. Keep the embedding-model prompt behaviour (`encode_document`) as is.
- [x] Rerank on the same contextual text, not the bare Segment text (`Search.search` passes `c.text` today).
- [x] Add the title/chapter prefix to the FTS5 row too (a new indexed column, or the same composed text), so a title word matches lexically. Migration is additive; the FTS content follows via the existing triggers or a rebuild.
- [x] Cap results per Video in `Search.search` (2 or 3) before truncating to `limit`, so adjacent overlapping windows of one passage don't fill the top 10. The cap applies after reranking and recency so the best window of each Video wins.
- [x] A way to re-embed existing data after the passage text changes: a `mentor reindex [--channel]` command (or a Sync flag) that steps done Videos back to `segmented` and enqueues Syncs. Mentor's own index on this machine has to be rebuilt after this ticket.
- [x] Tests: what `FakeEmbedder.passages` records includes the title; a search over one Video with many overlapping hits returns at most the cap for that Video.

Notes from the review:
- Qwen3-Embedding's document prompt is empty (verified in the cached `config_sentence_transformers.json`), so nothing frames the passage today.
- `chapter_title` is stored on the Segment but reaches neither index.

Implementation notes (2026-09-14): the context is a stored `segments.context` column ("{title} — {chapter}") set at
segmentation, so the FTS5 delete trigger removes exactly what was inserted; migration 7 rebuilds `segments_fts` with
`(context, text)`. Reindex is a Sync flag (`syncs.reindex`, `POST /api/syncs` or `/api/channels/{id}/syncs` with
`{"reindex": true}`, `mentor reindex`) that steps Videos back to `transcript_fetched` when claimed, since the context
is written at segmentation. `search.spread_across_videos` caps at 3 per Video and fills from the overflow so a
one-Video scope still gets a full list.
