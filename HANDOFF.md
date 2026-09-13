# Handoff — Mentor

State as of 2026-09-13: tickets 01–06 (walking skeleton, Mentors and Channels, Mentor Groups, Sync discovery and transcripts, Sync segmentation and embedding, Sync resilience and filters) are done, reviewed, and merged to `main`. Next up: ticket 07 (Live Sync progress).

Read in this order:
1. `CONTEXT.md` — domain glossary. Use these terms everywhere, including UI copy ("Channel", "Mentor").
2. `docs/specs/0001-mentor-v1.md` — the spec. Its "Review amendments" section wins over earlier text.
3. `docs/adr/` — two accepted decisions.
4. `.scratch/mentor-v1/issues/` — 18 tickets. Read the "From ticket NN review" notes appended to the ticket you pick up; they carry deferred findings.

## Codebase conventions so far
- `create_app(config, transcripts, embedder, static_dir, sync_poll_seconds)`: each port is its own argument, added when its first consumer lands. Lifespan starts the `SyncWorker` task (`sync_worker.py`), which is woken on enqueue and polls; it runs Syncs only while holding the `sync_lease` row. `mentor serve` wires `YouTubeTranscriptSource` (placeholder until ticket 08) and `SentenceTransformerEmbedder` (placeholder until ticket 10, built from config).
- Store: `db.Database.run(fn)` runs blocking work on a thread with a fresh connection. Writes go through `db.transaction(conn)` (`BEGIN IMMEDIATE`, guarded rollback). Do read-backs inside the transaction. Migrations are appended to `db.MIGRATIONS`: additive only, never edit a shipped entry. Exception: the vec0 table `segment_vectors` and its delete trigger are created after migrations by `db.ensure_embedding_model` (dimension comes from the model), so a migration can't reference them on a fresh database.
- Sync pipeline: `videos.pipeline_stage` is the last completed stage; failure (`failure_stage` = stage attempted) and exclusion are separate columns, and the API derives a single `stage`. `SyncWorker._advance` runs each Video through its remaining stages; `videos.complete_stage` advances and clears failures. Segments are replaced per Video in one transaction; FTS5 and vec0 rows follow via triggers. Pipeline store functions return False/None when their row vanished mid-Sync (Channel deleted) rather than raising. Exclusions (minimum length plus Channel filters, bundled as `videos.ExclusionRules`) are recomputed for the whole Channel at discovery by `videos._apply_exclusions`; an excluded Video loses its Segments and steps back to `transcript_fetched`. A Sync uses the filters as they were when claimed. Retry-failed is a Sync flag (`syncs.retry_failed`) that clears failures when claimed.
- Errors: domain code raises `errors.NotFound` / `errors.Conflict`; ports raise `ChannelNotFound` / `PlaylistNotFound` (Sync-only, not in `ERROR_STATUS`) / `SourceUnavailable` / `ModelUnavailable`, and `VideoUnavailable` for one Video (reason, permanent, language, partial details). All messages are user-facing and mapped to statuses in `app.ERROR_STATUS`.
- Tests: HTTP API seam through `tests/harness.running(app)`, which runs lifespan; `harness` also has `add_mentor`, `fake_channel`, `fake_video` (optional `cues`; `date_listed=False` leaves the listing undated), `Gate` (holds a fake fetch mid-Sync), `start_sync`, `wait_for_syncs`, `list_videos`, `fetched`, and `query` / `row_counts` for index state no API exposes yet. The `embedder` fixture is a `FakeEmbedder` (`unavailable="..."` raises `ModelUnavailable`; `passages` records what was embedded). The `client` fixture uses a seeded `FakeTranscriptSource`; it supports `unavailable="..."` for 503 cases and `playlists` for playlist filters. Listing order in a fake Channel is newest first. Pure-function tests only for intricate logic.
- UI: `web/src/api.ts` has typed calls and `errorText`. Components use Tailwind v4; shared classes and `useChanges` (a per-section busy lock that serialises changes and refreshes) live in `web/src/ui.ts`. App lifts the Mentor list from `Mentors` into `Groups`. Run `pnpm --dir web run build` before testing the served UI.
- Checks: `uv run pytest -q`, `uv run mypy`, `pnpm --dir web run typecheck`.

## Process
- `/implement` one ticket per session in the worktree `.claude/worktrees/mentor-v1` (branch `mentor-v1`). Then `/code-review` against `main` on both axes, fix what is in scope, and append deferred findings to the owning tickets. Mark the ticket done, commit, and fast-forward `main` before the next ticket.
- The `reviewer` agent definition pins Fable 5.1. When Fable is rate-limited, pass `model: opus` (Drew's session model).
- Ticket 18 needs Drew at the Cloudflare dashboard.

## Environment gotchas
- The worktree guard rejects shell heredocs, `cd`-then-git chains, and setting `XDG_CONFIG_HOME` on commands. Use the Write/Edit tools for files, and keep git commands plain and separate.
- `EnterWorktree` couldn't create a worktree because the session predated `git init`. Use `git worktree add` from the main checkout, then `EnterWorktree` with `path`. Merging into `main` needs `ExitWorktree` (keep) first.
- `pkill -f <pattern>` kills your own shell if the pattern appears anywhere in that command line; run it as a command by itself.
- Verify UI flows with a throwaway `/tmp` script that runs `create_app` with a seeded `FakeTranscriptSource` under uvicorn on a spare port (7390+), driven by Playwright. Delete the script and data dir afterwards.

Machine facts verified during design: RTX 3090 24 GB, 60 GB RAM, uv 0.11, Python 3.13 pinned (3.14 also installed), Node 22, pnpm 10.33, Deno 2.9, ffmpeg, Docker, Claude Code CLI logged in. The full Python stack (torch 2.14 CUDA, sentence-transformers 6.0, sqlite-vec 0.1.9, mcp 2.2, claude-agent-sdk 0.2.152, fastapi 0.141, yt-dlp 2026.8) installs and imports on 3.13. Ports 8080 and 4747 are taken; the default is 7337.
