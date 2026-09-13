# Handoff — Mentor

State as of 2026-09-13: design complete, spec reviewed and amended, tickets published, no code yet.

Read in this order:
1. `CONTEXT.md` — domain glossary. Use these terms everywhere.
2. `docs/specs/0001-mentor-v1.md` — the spec. Status ready-for-agent. Seams are in Testing Decisions and were accepted by Drew.
3. `docs/adr/` — two accepted decisions.
4. `.scratch/mentor-v1/issues/` — 18 tickets in dependency order. The spec's "Review amendments" section wins over earlier spec text.

Next steps per Drew's global CLAUDE.md flow:
1. `/implement` per ticket, starting at 01, working the frontier (tickets whose blockers are done), in a worktree, `tdd` inside; one `reviewer` pass on the whole branch at the end.
2. Ticket 18 needs Drew at the Cloudflare dashboard.
3. The repo is not yet a git repository; `git init` before the first worktree.

Machine facts verified during design: RTX 3090 24 GB, 60 GB RAM, uv 0.11, Python 3.12–3.14 available (pin 3.13), Node 22, pnpm, Deno 2.9, ffmpeg, Docker, Claude Code CLI 2.1.270 logged in. The full Python stack (torch 2.14 CUDA, sentence-transformers 6.0, sqlite-vec 0.1.9, mcp 2.2, claude-agent-sdk 0.2.152, fastapi 0.141, yt-dlp 2026.8) installs and imports on 3.13. Ports 8080 and 4747 are taken; spec default is 7337.
