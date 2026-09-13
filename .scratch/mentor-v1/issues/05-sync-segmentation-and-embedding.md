# 05 — Sync: segmentation and embedding

**What to build:** A Sync takes transcribed Videos through segmentation and embedding to `done`, so the knowledge base holds searchable Segments. Deleting a Mentor or Channel removes its Videos, Transcripts, Segments, and embeddings completely. (Story 7; uses fakes.)

**Blocked by:** 04 — Sync: discovery and transcripts

**Status:** done

- [x] Segmentation (a pure function with its own tests): 60–90 s windows snapped to cue starts, 15 s overlap, never crossing a chapter boundary, carrying the chapter title, storing start, end, text, and ordered cue offsets
- [x] Segments are stored with an FTS5 index and a vec0 index; vec0 carries the Channel id as a metadata column for scoped KNN
- [x] Re-running a stage for a Video replaces that Video's prior Segments and vectors in one transaction, so a crash never leaves duplicates
- [x] Embedding model name and dimension are stored; starting with a config whose dimension or model differs refuses with a clear message
- [x] Deleting a Mentor or Channel cascades into the FTS5 and vec0 tables; tests assert those indexes' row counts go to zero
- [x] Videos reach `done`; stage counts reflect it

From ticket 04 review: `tests/test_sync.py` asserts that a finished Sync leaves Videos at `transcript_fetched` (stage and `stage_counts`). Once segmentation and embedding run, the terminal stage becomes `done`; update those expectations as part of this ticket's behaviour change. The worker currently skips Videos whose `pipeline_stage` isn't `discovered`; add the later stages there (`sync_worker._run_sync`).

Done note: segmentation windows grow greedily to 90 s from a cue start; the next window starts at the latest cue that keeps at least 15 s of overlap; a final window under 60 s starts earlier (never past 90 s). Cues are sorted, blank ones dropped, a cue belongs to the chapter it starts in and a window's end is cut at the next chapter start. Segments store `(start, offset)` per cue, where offset is the character index in the Segment text. Mid-section slivers still happen when a single cue is very long; accepted. The vec0 table `segment_vectors` (and its delete trigger) is created at startup by `db.ensure_embedding_model`, not in `MIGRATIONS`, because its dimension comes from the model; the model may change freely until the first vector is stored. The check uses the Embedder port's `model_name`/`dimension`, which `mentor serve` builds from config (`embedding_model`, `embedding_dimension`). `ModelUnavailable` stops the Sync (the Video resumes from its last stage); any other error in segmentation or embedding fails only that Video, transiently. FTS5 uses the porter tokenizer. A Video whose Transcript has no spoken text reaches `done` with no Segments.
