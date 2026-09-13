# 05 — Sync: segmentation and embedding

**What to build:** A Sync takes transcribed Videos through segmentation and embedding to `done`, so the knowledge base holds searchable Segments. Deleting a Mentor or Channel removes its Videos, Transcripts, Segments, and embeddings completely. (Story 7; uses fakes.)

**Blocked by:** 04 — Sync: discovery and transcripts

**Status:** ready-for-agent

- [ ] Segmentation (a pure function with its own tests): 60–90 s windows snapped to cue starts, 15 s overlap, never crossing a chapter boundary, carrying the chapter title, storing start, end, text, and ordered cue offsets
- [ ] Segments are stored with an FTS5 index and a vec0 index; vec0 carries the Channel id as a metadata column for scoped KNN
- [ ] Re-running a stage for a Video replaces that Video's prior Segments and vectors in one transaction, so a crash never leaves duplicates
- [ ] Embedding model name and dimension are stored; starting with a config whose dimension or model differs refuses with a clear message
- [ ] Deleting a Mentor or Channel cascades into the FTS5 and vec0 tables; tests assert those indexes' row counts go to zero
- [ ] Videos reach `done`; stage counts reflect it
