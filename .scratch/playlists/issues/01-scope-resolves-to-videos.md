# 01: Scope resolves to Videos

**What to build:** A behaviour-preserving prefactor. Every scope (everything, a Group, a Channel, chosen Channels) resolves to a set of searchable Videos instead of a set of Channels, so a later Playlist scope, and a paused Channel's Videos reached through a Playlist, need no second path. Search, `expand`, `get_video`, saved Citations, and per-scope Channel summaries all use the one Video-level predicate. The vector index filters on `video_id` instead of `channel_id`, and existing embeddings are carried over, so nothing is re-embedded. See Spec 0004 §Schema (last bullet) and §Scope resolves to Videos.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] A migration rebuilds `segment_vectors` with a `video_id` metadata column in place of `channel_id`, copying every embedding. It follows the verified order in Spec 0004: temporary copy, drop trigger, drop table, create under the final name, insert, recreate trigger. It doesn't create-then-rename or rely on `legacy_alter_table`. Fresh databases get the new shape.
- [x] One Video-level scope predicate replaces the Channel-level one in search, `expand`, `get_video`, Citations, and Channel summaries. Summary counts come from the predicate, not from `channels.indexed`.
- [x] Search filters KNN and FTS with `video_id IN (SELECT value FROM json_each(?))`.
- [x] The migration test migrates a populated database whose vectors match the fake embedder's dimension. It checks that the vector count and each segment's Video survive and that a search finds the migrated Segment. The fixture's insert and assertion move from `channel_id` to `video_id`.
- [x] The existing search, sources, conversations, groups, and MCP tests pass unchanged.
- [x] The retrieval baseline is rerun on real models and is unchanged.

## Comments

**2026-10-10, implemented.**

What landed:
- Migration 19 (`_vectors_by_video`) rebuilds `segment_vectors` around `video_id` in the spec's order, copying every embedding. Fresh databases get the shape from `ensure_embedding_model`.
- `scope.VIDEO_IN_SCOPE` is the one predicate behind search, `expand`, `get_video`, Citations, and the summary counts. `CHANNEL_IN_SCOPE` stays only to list which Channels a scope names (a Group's members, synced or not) and to name them in the chat prompt.
- Search resolves a scope to Video ids and filters KNN and FTS with `video_id IN (SELECT value FROM json_each(?))`.
- The frozen-baseline runner migrates its disposable copy, since Search no longer reads the schema-11 vector table. The snapshot itself stays at schema 11.

Verification:
- `uv run pytest -q`: 590 passed (588 before, plus the migration test and one MCP test). `uv run mypy` and `pnpm --dir web run typecheck` clean.
- Retrieval baseline on CUDA (RTX 3090), run before and after the change in the same environment: 10/10 both times, with rankings and scores identical to each other and rankings identical to `docs/baselines/ticket-02-cuda.json`. Snapshot checksum unchanged.
- On a copy of the frozen corpus (49,403 vectors, 1,791 searchable Videos): the migration takes about 26 s, almost all of it sqlite-vec reading and re-inserting the vectors; KNN over everything is 100 ms with the `video_id` filter against 91 ms with `channel_id`, and returns the same 50 Segments. A one-Video scope returns only that Video's Segments, so the filter is applied inside the KNN.

Behaviour that changed, both following from the predicate:
- `expand` and `get_video` no longer find a Video that isn't done (they used to find any Video on an Active Channel). The spec's predicate is "done and not excluded".
- Search embeds the query before answering an empty scope, so "model still loading" is reported even when the scope covers no Videos. With Channel-level resolution a Channel with no done Videos still counted as covered; `test_search_reports_a_model_still_loading_as_a_tool_error` depends on that. The cost is that an empty Library with a model that isn't ready now answers 503 instead of an empty list.

For later tickets:
- `storyboards.read_frames` and `storyboards.missing` still test `channels.indexed = 1` themselves. This ticket's list didn't name them, but ticket 05 needs them on `VIDEO_IN_SCOPE`, or a Paused creator's Playlist Videos will be cited without frames.
- `group_summaries` now builds each Group from `channel_summaries(conn, Scope("group", id))`, one query per Group, so a Playlist's creators can be listed the same way.
