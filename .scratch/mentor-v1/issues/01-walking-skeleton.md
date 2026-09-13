# 01 — Walking skeleton

**What to build:** `mentor serve` starts on 127.0.0.1:7337 and serves a web page that shows the server's Health. Behind it are the SQLite knowledge base in the XDG data directory (WAL, sqlite-vec and FTS5 loaded), the config surface, and the test harness every later ticket builds on. `uv tool install` from the repo produces a working `mentor` command with the web bundle included. See spec 0001 and its Review amendments.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] Python 3.13 uv project; `mentor serve` binds 127.0.0.1 on port 7337 by default
- [ ] Config: one TOML file in the XDG config dir, overridable by `MENTOR_*` env vars; port and data dir configurable
- [ ] Database opens in WAL mode with foreign keys on and a busy timeout for every connection; sqlite-vec and FTS5 available
- [ ] Health endpoint reports server status (model and Claude CLI fields added by later tickets)
- [ ] Vite + React + Tailwind v4 + TypeScript (no `any`) bundle, built with a relative base, served statically by the server and showing Health
- [ ] The web bundle is built as part of the Python package build; `uv tool install` from a clean checkout serves the UI
- [ ] Port interfaces for TranscriptSource, Embedder, Reranker, ChatEngine exist, with fakes (FakeTranscriptSource, hash-based FakeEmbedder, lexical-overlap FakeReranker, scripted FakeChatEngine)
- [ ] pytest-asyncio harness: in-process ASGI client against a temporary SQLite file with fakes injected; one test hits Health
- [ ] Pattern established for running blocking work (SQLite, GPU, yt-dlp) off the event loop
