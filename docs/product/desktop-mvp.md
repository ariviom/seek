# Seek Desktop: MVP technical brief

Status: draft, 2026-09-17. Product rationale is in the evaluation thread; this is the engineering shape.

Superseded in part on 2026-09-17 by `docs/specs/0003-build-0-friends-release.md`, which is the plan of record for what
ships next. A grilling session cut the first release to what a friend needs to run Seek at all and deferred the
rest; ADR 0004 and ADR 0005 record the two decisions that changed. This brief stands as the longer-range roadmap.

## What we are building

A local-first desktop app that turns the creators and sources you trust into a private, cited knowledge base, searchable from the app and from any agent over MCP. Every answer links to the moment in the video. Ingestion, embeddings, and the database stay on the user's machine. Answers come from a model the user already pays for: their own API key (Anthropic or Google) or their local Claude Code login.

Non-goals for the MVP: hosted anything, accounts, payments, shared index packs, non-YouTube sources beyond single videos and playlists, visual (frame) indexing. The pack format is designed now but not shipped.

## What exists today (v0.1, 51 commits)

- Python 3.13 service: FastAPI + uvicorn, one SQLite file with sqlite-vec and FTS5 (ADR 0002), hybrid search fused and reranked, recency adjustment.
- Ingestion: yt-dlp lists a channel and fetches captions, segmentation by chapter and time window, Qwen3-Embedding-0.6B (1024-d) via sentence-transformers and torch on an NVIDIA GPU, mxbai-rerank-base-v2 cross-encoder.
- Retrieval is the product (ADR 0001): six MCP tools (`list_groups`, `list_channels`, `search`, `expand`, `get_video`, `sql`) served over streamable HTTP at `/mcp`.
- Web chat drives the local Claude CLI through the Claude Agent SDK, locked to the Seek tools (`claude_chat.py`, behind the `ChatEngine` port).
- React 19 + Vite + Tailwind v4 + shadcn UI, inline player that seeks to the citation.
- Linux only: systemd user service, Deno on PATH for yt-dlp's JS challenges, about 3.5 GB of GPU.

The ports already in `ports.py` (`TranscriptSource`, `Embedder`, `Reranker`, `ChatEngine`) are the seams the MVP work plugs into. Almost nothing in retrieval changes.

## Architecture changes

### 1. Chat engines: add a BYO-key engine beside the Claude CLI engine

Keep `ChatEngine` as the port. Two adapters:

- `ClaudeCliEngine` (exists): subscription-billed, requires Claude Code installed and logged in. Stays the power-user path.
- `ApiEngine` (new): our own tool loop against a provider SDK, calling the same in-process MCP tools with the same system prompt and tool descriptions, emitting the same `ChatEvent` stream (`TextDelta`, `ToolCall`, `ToolResult`, `ChatDone`, `ChatFailed`).

Provider adapters inside `ApiEngine`:

| Provider | SDK | Default model | Notes |
|---|---|---|---|
| Anthropic | `anthropic` 1.x | `claude-sonnet-5` | Adaptive thinking on, `cache_control` on system prompt and tool list, streaming. `claude-opus-5` selectable as "deep answer". |
| Google | `google-genai` | `gemini-3.5-flash-lite` | Function calling. Free tier makes light use cost nothing. `gemini-3.8-flash` selectable. |

The loop is small: send messages plus tool schemas, execute `tool_use` blocks against the MCP server in process, append results, repeat until the model stops or `MAX_TURNS` (30, as today). Conversation history is replayed from our own store on every turn; no provider-side session state, which also removes today's resume-session logic for the API path.

Tool schemas come from the MCP server's `list_tools`, translated once per provider format. One function does this per provider; do not hand-copy schemas.

Settings: `chat_engine = "claude_cli" | "api"`, `api_provider`, `api_model`. Keys live in the OS keychain via `keyring`, never in `config.toml`. The health dot gains a state per engine: `no_key`, `invalid_key`, `ready`.

Cost at roughly 15k input and 800 output tokens per query: Flash-Lite under a cent, Sonnet 5 about four cents, Opus 5 about ten cents. Show a running per-conversation token count in the UI so BYO users trust it.

### 2. Inference: ONNX Runtime instead of torch

Torch plus CUDA is about 2 GB and NVIDIA-only. Replace with `onnxruntime` and pre-exported int8 models:

- Embedder: Qwen3-Embedding-0.6B ONNX int8, about 600 MB. Same model, so existing databases and future packs stay valid. Verify cosine drift against the torch path on a sample before switching; anything under 1e-3 is fine for search.
- Reranker: mxbai-rerank-xsmall-v2 ONNX by default, base as an option. Rerank scores are per-query and never persisted, so this swap has no compatibility cost.
- Execution providers: CPU everywhere, CUDA on NVIDIA, CoreML on Apple Silicon, DirectML on Windows. Pick at startup, report in `/api/health`.

Expected CPU ingest for a 500-video channel (about 2.7M tokens): 15 to 60 minutes as a background job. Query embedding is instant. Rerank of 20 candidates on CPU is 1 to 3 seconds with xsmall; show it in the UI as a "ranking" state rather than hiding it.

Model files download on first run as today. Keep the "one embedding model per database" rule and record `embedding_model`, `embedding_dimension`, and a `segmenter_version` in the database header. This is the pack compatibility key.

### 3. Sources: playlists and single videos

`TranscriptSource` already has `list_playlist`. Add a source kind on Channel-like entities: `channel`, `playlist`, `video`. A playlist or single video behaves as a Channel of one publisher for grouping and citation. Sync logic is unchanged; discovery differs per kind.

Superseded for playlists by ADR 0006: a Playlist is its own scope over Videos, which stay credited to their real Channels. Single videos are still open.

yt-dlp keeps needing a JS runtime. Bundle a runtime binary with the app rather than requiring Deno on PATH; yt-dlp accepts `--js-runtimes` with deno, node, bun, or quickjs. This is the biggest packaging unknown and should be spiked first.

### 4. Shareable Groups as recipes

Export a Group to JSON: name, description, list of sources (kind, id, display name, filters). Import creates the Channels, queues Syncs, and shows progress. No content travels, so no rights question. Recipes are the community hook: a woodworking starter pack is a file in a forum post.

Reserve the pack format now so a recipe can later carry content: `format_version`, `embedding_model`, `embedding_dimension`, `segmenter_version`, `publisher`, `signature`, then per-video segments and vectors. Shipping packs waits for creator consent tooling and is out of scope.

### 5. Citations with a frame

Cheap version, in scope: YouTube storyboard sprites (yt-dlp exposes them as `sb*` formats). Store the storyboard spec per video at sync time, cut the tile for a timestamp on demand, cache it, and show it next to each result and in the MCP `search` response as an image URL. Real visual indexing comes later.

### 6. Desktop packaging

- Shell: Tauri, with the Python service as a sidecar built by PyInstaller. Tauri gives a small installer, tray icon, auto-update, and keychain access; the existing Vite UI loads unchanged.
- The sidecar owns everything it owns today: SQLite, models, MCP endpoint on `127.0.0.1:7337`. Agents register the same URL as now.
- Replace systemd with the app lifecycle: the sidecar starts with the app, scheduled Sync becomes an in-app timer, `seek sync` and `seek status` keep working against the running sidecar.
- Targets: macOS Apple Silicon first (largest laptop share among likely users), Linux, then Windows.

Distribution as `uv tool install` stays for developers and is the path friends use before the shell exists.

## Data model changes

- `sources` replaces the channel-only assumption: `kind`, `external_id`, `display_name`, `filters`.
- `videos.storyboard` JSON.
- `settings` table for engine, provider, model, execution provider; secrets in the keychain.
- Database header: `embedding_model`, `embedding_dimension`, `segmenter_version`, `format_version`.
- `conversations.engine` and `model` recorded per turn, so cost and provenance are visible later.

## Milestones

1. **ONNX inference path** with a compatibility test against stored vectors, CPU and CUDA providers. Ships as a config switch first.
2. **ApiEngine** with the Anthropic adapter, keychain, settings UI, token counter. Then the Google adapter.
3. **Playlists and single videos** as sources.
4. **Group recipes** export and import.
5. **Storyboard frames** in results and in the MCP response.
6. **Tauri shell and sidecar** on macOS, bundled JS runtime for yt-dlp, first-run model download with progress.
7. **Friends build**: five people on three operating systems, each with a real Group, before any public release.

Each milestone gets an ADR where it changes a decision (0004 chat engines, 0005 ONNX, 0006 packaging) and a spec in `docs/specs` in the existing format.

## Risks to settle early

- **Claude subscription in a third-party app.** Driving the user's Claude Code login from a distributed app may not be allowed by Anthropic's consumer terms. Keep the API path as the default and read the current terms before shipping the CLI path to strangers.
- **yt-dlp breakage.** YouTube changes break caption fetching a few times a year. Pin yt-dlp per release, ship point updates fast, and surface failures per video as today.
- **JS runtime bundling** for yt-dlp on three operating systems.
- **CPU ingest speed** on older laptops. Mitigation is the background job plus, later, recipes that point at a hosted fast-ingest of the same open model.
- **Model download size** (about 1 GB total) on first run.
- **Windows** is the least-tested target for every dependency above.

## Evaluation

Before choosing default models, build a small eval: 30 real questions across the woodworking and marketing Groups with known-good citations. Score citation correctness and refusal to answer beyond sources. Run it against Flash-Lite, Sonnet 5, and the Claude CLI path. This is also the regression test for retrieval changes.
