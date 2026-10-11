# Handoff — implementing Playlists

You're starting the Playlists feature at ticket 01. Everything was designed, specced, critiqued, and broken down in a
previous session, and Drew approved all of it. Don't reopen design decisions: if something in a ticket looks wrong,
say so in one line and ask.

## Read first, in this order
1. `CONTEXT.md`: the glossary. **Library**, **Playlist**, and **Playlist filter** are new; use these terms exactly.
2. `docs/adr/0006-playlists-scope-videos-not-channels.md`: why a Playlist is its own scope over Videos, and why
   Videos stay credited to their real Channels.
3. `docs/specs/0004-playlists.md`: the spec, already revised after a `reviewer` critique. Its Implementation
   Decisions carry the verified details: the vec0 rebuild order, the lease-recovery fix, and the `json_each` filter
   (verified on sqlite-vec 0.1.9).
4. `.scratch/playlists/README.md`: the ticket table and blocking edges. Then read the ticket you're on.
5. `docs/agents/*.md`: tracker conventions. Tickets are local markdown, and status is the `Status:` line.

## How to work
- One ticket at a time, in number order. Every ticket adds a migration, so don't run tickets in parallel.
- Work in a worktree (`EnterWorktree`), test-first through the existing seams:
  - the `create_app` harness with fakes, over HTTP and MCP;
  - the migrations test pattern;
  - the `is_due` unit test;
  - the Playwright smoke test.
  
  Don't add new seams.
- Verify with `uv run pytest -q && uv run mypy && pnpm --dir web run typecheck`, plus `pnpm --dir web run build`
  when a ticket touches the web. Ticket 01 also reruns the retrieval baseline on real models; ticket 03 runs the
  real-yt-dlp check (`-m real_youtube`).
- When a ticket is done:
  - tick its criteria;
  - set `Status:` to done in the ticket and in the README table;
  - append a short note under `## Comments` (what landed, verification numbers, anything deferred);
  - commit.
- Run one `reviewer` pass on the whole branch at the end of the feature, not one per ticket.
- Ticket 03's private-playlist check needs Drew's YouTube cookies. If they aren't configured, record it as pending
  and carry on.

## Done when
All ten tickets are done, the full verification passes, the branch has had its `reviewer` pass with findings fixed,
and README/HANDOFF mention Playlists.
