# Spec 0001 — Mentor v1

Status: ready-for-agent
Glossary: see `CONTEXT.md`. Terms below (Mentor, Channel, Mentor Group, Video, Transcript, Segment, Citation, Sync, Pipeline stage, Conversation) carry their glossary meaning.

## Problem Statement

I learn hands-on disciplines such as woodworking from a handful of YouTube creators. Their knowledge is scattered across hundreds of hours of video. When I have a specific question I cannot ask them, and searching YouTube surfaces titles, not answers. When a model answers from general knowledge I cannot tell whether the advice is what *my* trusted creators actually teach, and for visual techniques I need to watch the exact moment they show it.

## Solution

A locally hosted tool, `mentor`, that turns one or more YouTube channels into a searchable knowledge base of timestamped transcript Segments. I organise creators into Mentor Groups and consult a Group in two ways: from Claude Code, Claude Desktop, or Codex via MCP tools, or from a small local web UI whose chat is driven by my own Claude subscription. Every answer cites the Mentor, the Video, and a link that opens the exact moment, and the web UI plays that moment inline. Ingestion runs from the web UI, shows progress, survives interruption, and picks up where it stopped. Nothing costs money beyond electricity.

## User Stories

### Mentors, Channels, Groups
1. As a learner, I want to add a Mentor by pasting a YouTube channel URL or handle, so that I do not have to look up channel ids.
2. As a learner, I want the tool to propose the channel's display name as the Mentor name, so that setup is one click in the common case.
3. As a learner, I want to attach additional Channels to an existing Mentor, so that a creator with a main channel and a second channel is one Mentor.
4. As a learner, I want to mark a Channel as not indexed, so that a Mentor's vlog channel stays out of results without leaving the Mentor.
5. As a learner, I want to create a named Mentor Group and add or remove Mentors, so that I can consult "the woodworkers" as one voice.
6. As a learner, I want a Mentor to belong to several Groups, so that a generalist creator can advise on more than one discipline.
7. As a learner, I want to remove a Mentor or Channel and have its Videos, Transcripts, Segments, and embeddings removed with it, so that the knowledge base stays honest.
8. As a learner, I want Conversations to survive Mentor removal, so that past advice is not lost.

### Ingestion
9. As a learner, I want to start a Sync for a Channel from the web UI, so that I never need a terminal for ingestion.
10. As a learner, I want a Sync to discover every Video on the Channel and skip Shorts and Videos under a configurable minimum length by default, so that noise stays out.
11. As a learner, I want optional per-Channel filters (date range, playlist, most recent N), so that I can scope a huge channel.
12. As a learner, I want to see live progress for the running Sync: how many Videos are discovered, in each Pipeline stage, done, and failed, so that I know how long to wait.
13. As a learner, I want to see the per-Video pipeline state and any failure reason, so that I understand what was skipped and why.
14. As a learner, I want a Sync interrupted by a crash, shutdown, or network loss to resume from the unfinished Videos when rerun, so that I never re-ingest what is already done.
15. As a learner, I want a "retry failed" action per Channel, so that transient YouTube errors are recoverable in one click.
16. As a learner, I want a rerun Sync to pick up only Videos published since the last Sync, so that keeping current is cheap.
17. As a learner, I want Syncs to run one at a time and to queue further requests, so that YouTube is not hammered and the GPU is not contended.
18. As a learner, I want members-only, age-restricted, in-progress live, and caption-less Videos marked failed with a reason rather than aborting the Sync, so that one bad Video never blocks a Channel.
19. As a learner, I want Videos without English captions marked failed with the language recorded, so that a future non-English mode can revisit them.
20. As a learner, I want the tool to respect YouTube rate limits with polite delays and to back off on errors, so that my IP is not blocked.
21. As a learner, I want an optional scheduled Sync of all Channels I can enable with one command, so that the knowledge base stays current without me remembering.

### Retrieval and citation
22. As a learner, I want to search a Mentor Group with a natural-language question and get the most relevant Segments, so that I find the moment a Mentor addressed it.
23. As a learner, I want search to catch exact jargon (tool names, product names) as well as paraphrase, so that "domino joiner" finds the right clip even when phrased differently.
24. As a learner, I want results reranked by a stronger model, so that the top few are genuinely the best.
25. As a learner, I want each result to carry Mentor name, Channel, Video title, publish date, chapter name where present, the Segment text, and a Citation link to the precise matched moment, so that I can verify anything.
26. As a learner, I want newer Videos gently preferred when two address the same question, and to be able to turn that preference up or off, so that outdated advice loses ties without vanishing.
27. As a learner, I want to search across a Group, a specific list of Mentors, or everything, so that I can ask "what does just this one creator say."
28. As a learner, I want to expand a Segment to see the transcript before and after it, so that I get context without opening YouTube.
29. As a learner, I want to fetch a Video's title, chapters, and description, so that a model can reason about the source.
30. As a learner, I want a read-only SQL escape hatch, so that I can ask "how many videos mention X" without waiting for a feature.

### MCP integration
31. As a Claude Code user, I want to register mentor once at user scope and have its tools in every session, so that I can consult my Mentors mid-task.
32. As a Codex user, I want the same server registered by URL, so that both agents share one knowledge base.
33. As a Claude Desktop user, I want to add mentor as a custom connector by its public URL, so that Desktop works without a local bridge.
34. As an MCP user, I want tool descriptions that instruct the model to answer only from retrieved Segments, cite every claim, name the Mentor, surface disagreements, flag old sources, and admit gaps, so that behaviour matches the web chat.
35. ~~Dropped in review.~~ As an MCP user, I want a clear error when the server is not running, so that I know to start it.

### Web chat
36. As a learner, I want to open a Mentor Group and chat with it in the web UI, so that I do not need Claude Code for a quick question.
37. As a learner, I want the chat to run on my Claude subscription through the local Claude CLI, so that it costs nothing extra.
38. As a learner, I want the chat model restricted to mentor tools only, so that a web chat can never touch my filesystem or shell.
39. As a learner, I want answers to stream token by token with tool calls visible, so that I can watch the research happen.
40. As a learner, I want the assistant to behave as a grounded advisor: only from Segments, every claim cited and attributed, disagreements between Mentors surfaced, old-only sources flagged, gaps admitted, so that I trust what I read.
41. As a learner, I want to click a Citation and have an embedded YouTube player open beside the answer at that timestamp, so that I can watch the technique immediately.
42. As a learner, I want Conversations saved per Group, listed, reopenable, and resumable, so that I can return to last week's thread.
43. As a learner, I want to pick the Claude model per Conversation, defaulting to my CLI default, so that quick questions can use a cheaper model.
44. As a learner, I want a clear message when the Claude CLI is missing or not logged in, so that I know what to fix.

### Operations
45. As a learner, I want a single `uv tool install` and one `mentor serve` command, so that setup is minutes.
46. As a learner, I want `mentor serve` installable as a systemd user service that starts at login, so that MCP is always available.
47. As a learner, I want the server itself bound to localhost with no auth, so that the only way in from outside is through my reverse proxy.
47a. As a learner, I want to publish the server through my existing reverse proxy behind Cloudflare Zero Trust, so that MCP clients and the web UI work from any machine with my identity as the gate.
47b. As a learner, I want the server to optionally verify the Cloudflare Access JWT on every request when I configure my team domain and audience, so that a proxy misconfiguration cannot silently expose the knowledge base.
47c. As a learner, I want the server to work behind a proxy prefix and honour forwarded-host headers, so that citation links and SSE streams are correct when accessed remotely.
48. As a learner, I want the whole knowledge base in one SQLite file in a standard data directory, so that backup is a copy.
49. As a learner, I want models downloaded on first use with visible progress and cached, so that the first run is understandable.
50. As a learner, I want `mentor sync` on the CLI to delegate to the running server when it is up and run the pipeline directly when it is not, so that cron works either way and models load once.

## Implementation Decisions

### Shape
- **Retrieval service plus MCP; Claude is the brain.** The tool never runs an LLM for generation. Frontier models via Claude Code, Desktop, Codex, or the web chat do the reasoning over retrieved Segments. See ADR 0001.
- **One Python process** (`mentor serve`) hosts: the HTTP API for the web UI, the Streamable HTTP MCP endpoint, the ingestion worker, the loaded embedding and reranker models, and static serving of the built web bundle. Python 3.13 via uv (the stack installs on 3.14 too, but two libraries do not yet declare it). Default port 7337 (8080 and 4747 are already in use on this machine), configurable.
- **Web UI**: Vite, React, Tailwind v4, TypeScript with no `any`. Built into the Python package's static directory. Talks to the API over JSON and SSE.
- **Storage**: one SQLite database with sqlite-vec for vectors and FTS5 for lexical search, WAL mode, in the XDG data directory. See ADR 0002.
- **CLI** is minimal: `serve`, `sync [--all | --channel]`, `install-service`.

### Ports and adapters
Three external systems sit behind explicit interfaces so the core can be tested without them:
- **TranscriptSource** (YouTube via yt-dlp): resolve a channel URL or handle to id and display name; list Videos with id, title, publish date, duration, is-short, chapters, description; fetch English auto or manual captions as timestamped cues. Uses json3 subtitle format, skip-download, sleep between requests, Deno available on this machine. Cookie file optional for higher rate limits.
- **Embedder** and **Reranker** (sentence-transformers on CUDA): batch encode texts; score query and passage pairs.
- **ChatEngine** (Claude Agent SDK, Python): start or resume a session with a system prompt, an in-process MCP server exposing the mentor tools, `allowed_tools` limited to those tools, a chosen model; yields a stream of events (text delta, tool call, tool result, done, error).

### Domain and pipeline
- Video `pipeline_stage`: `discovered → transcript_fetched → segmented → embedded → done`, or `failed` with `failure_reason` and `failure_stage`. Resume is stateless: a Sync processes every Video of the Channel whose stage is not `done`, in stage order. Retry-failed resets `failed` Videos to the stage they failed at.
- Sync queue: one worker task inside the server process, FIFO, one Sync at a time. Sync record holds counts per stage and timestamps. Progress is pushed over SSE from the same counters.
- Default filters: exclude Shorts, exclude duration under 120 s. Per-Channel optional filters: published after or before, playlist id, most recent N.
- Segmentation: sliding windows of 60 to 90 s snapped to caption-cue starts, 15 s overlap, so roughly 200 to 320 tokens of spoken text. When Video chapters exist, windows never cross a chapter boundary and carry the chapter title. Each Segment stores start, end, text, ordered cue offsets so a match can cite the exact cue time.
- Transcript records `source` (`youtube_auto`, `youtube_manual`) and `language`. Only `en` is ingested in v1.

### Retrieval
- Embedding model: `Qwen/Qwen3-Embedding-0.6B`, 1024 dims, query-side instruction prompt, passages unprefixed. Fallback `Snowflake/snowflake-arctic-embed-m-v2.0`. Reranker: `mixedbread-ai/mxbai-rerank-base-v2`, fallback `BAAI/bge-reranker-v2-m3`. Both Apache-2.0, both fit the 3090 alongside each other. Model names are configuration, not code.
- Query flow: vector top 50 and FTS5 BM25 top 50 over the scoped Segments → Reciprocal Rank Fusion with k=60 → rerank the union → apply recency adjustment → return top `limit` (default 10).
- Recency: `prefer_recent` takes `off | gentle | strong`. Default `gentle`, a small multiplicative decay on reranker score by Video age so near-ties break toward newer. Publish date is always in the result.
- Scope: exactly one of Group id, list of Mentor ids, or nothing (all indexed Mentors). Channels marked not-indexed are excluded everywhere.
- Result shape: segment id, text, start and matched-cue seconds, Video id, title, publish date, chapter title, Channel name, Mentor name, score, and a YouTube URL with the timestamp parameter.

### MCP tools (same functions serve HTTP MCP and the web chat's in-process server)
- `list_groups()` → Groups with their Mentors and Video counts.
- `search(query, group?, mentors?, limit?, prefer_recent?)` → results as above.
- `expand(segment_id, before_seconds?, after_seconds?)` → contiguous transcript text with cue times around the Segment.
- `get_video(video_id)` → title, Mentor, Channel, publish date, duration, chapters, description, URL.
- `sql(query)` → rows from a read-only connection; rejects anything but a single SELECT; row and time limits.
- The server-level instructions and each tool description embed the grounded-advisor guidance from user story 34.

### Web API (JSON unless noted)
- Mentors: create from URL or handle (resolves and returns proposal), rename, delete; Channels: attach, toggle indexed, set filters, detach.
- Groups: create, rename, delete, set members.
- Syncs: enqueue for a Channel, enqueue all, retry-failed for a Channel, list; `GET /events` SSE stream of Sync progress and Video stage changes.
- Videos: list per Channel with stage, reason, and metadata.
- Search and expand mirror the MCP tools for the UI.
- Conversations: create (Group, model), list per Group, get with messages, `POST message` returning an SSE stream of ChatEngine events; messages and Claude session id persisted on completion.
- Health: server, models loaded, Claude CLI present and authenticated.

### Chat system prompt
Grounded advisor. Answer only from Segments returned by tools. Cite each claim as Mentor, Video title, timestamp link. Name which Mentor said what. Surface disagreements between Mentors. When the only supporting Video is old relative to the Group's newest content, say so. When the Mentors do not cover the question, say so and stop rather than answering from general knowledge. Prefer `search` first, `expand` for context, `sql` only for counting or listing questions.

### Deployment and remote access
- `uv tool install` from the repo. `mentor install-service` writes a systemd user unit for `mentor serve`.
- The process binds 127.0.0.1 only. Remote access is the user's existing reverse proxy publishing it at a public hostname with Cloudflare Zero Trust Access in front. TLS, identity, and session handling are Cloudflare's job, not the app's.
- **Access JWT verification, optional, default off.** When `CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD` are configured, every request (API, MCP, SSE, static) must carry a valid `Cf-Access-Jwt-Assertion`, verified against the team's public keys with caching. Requests from loopback without the header are still accepted so local clients and the systemd timer keep working. This is defence in depth against a proxy bypass; the trust boundary remains Cloudflare.
- The MCP endpoint must be usable by Claude Desktop custom connectors and Claude Code or Codex over the public URL. Cloudflare Access supports MCP clients through its OAuth flow; if a client cannot complete Access login, the fallback is an Access service token supplied as headers in that client's MCP config. Confirm the exact Access product setting during implementation and document it in the README; this is configuration on the Cloudflare side, not app code.
- Proxy awareness: respect `X-Forwarded-Proto` and `X-Forwarded-Host` for any absolute URL the server emits, support an optional root path prefix, and keep SSE responses proxy-safe (no buffering headers, periodic keepalive comments).
- Registration snippets documented for Claude Code (`claude mcp add --transport http`, local or public URL), Codex (`codex mcp add --url`), and Claude Desktop (custom connector with the public URL).

## Testing Decisions

Tests exercise external behaviour through the fewest possible seams. Internal module boundaries are not asserted on.

- **Primary seam: the HTTP API** of the server, driven with an in-process ASGI test client against a temporary SQLite file, with the three ports replaced by fakes: a `FakeTranscriptSource` seeded with channels, videos, and cues; a deterministic `FakeEmbedder` (hash-based vectors) and `FakeReranker` (lexical overlap score); a `FakeChatEngine` that emits a scripted event stream and records the options it was given. Nearly every user story is testable here: add Mentor, sync, observe stage counts over SSE, interrupt mid-Sync by raising from the fake and assert resume completes only the remainder, retry-failed, search scoping, recency ordering, citation fields, conversation persistence, tool allowlist passed to the ChatEngine, cascade on delete.
- **Secondary seam: the MCP server**, driven in-process with the MCP client from the Python SDK over an in-memory transport, asserting tool listing, descriptions containing the grounded-advisor guidance, and that `search` returns the same shape as the API. Also that `sql` rejects writes.
- **Pure-function tests without fakes** where the logic is intricate: segmentation windows from cues (chapter snapping, overlap, cue-offset citation), RRF fusion, recency adjustment. These are the only tests below the API seam.
- **Opt-in integration tests**, skipped by default, marked `real_models` and `real_youtube`: load the actual embedding and reranker on CUDA and check a known query ranks a planted Segment first; fetch captions for one short public Video.
- **Frontend**: component tests are not required in v1. A single Playwright smoke test against the built bundle and the API with fakes covers add Mentor → Sync → search → open Citation player.
- Test framework: pytest with asyncio. Prior art: none, this is a new repo. A good test names a user story, sets state through the public API only, and asserts on responses and streamed events.

## Out of Scope

- Whisper or any local transcription. Transcript `source` is recorded so it can be added later.
- Non-English captions. Language is recorded; ingestion skips them.
- Application-level user accounts or multi-user data separation. Identity is Cloudflare's; the app has one user.
- Configuring the reverse proxy or Cloudflare itself. The app only needs to be proxy-correct and optionally verify the Access JWT.
- Per-project databases or multi-user.
- A CLI mirror of the management UI.
- Description embeddings or indexing (descriptions are returned by `get_video` only).
- Automatic discovery of a creator's other channels.
- Partial-Channel Group membership (handled by marking a Channel not indexed).
- Codex or Claude Desktop as the web chat's engine. The web chat uses the Claude Agent SDK only.

## Further Notes

- yt-dlp guidance: about 300 Videos per hour unauthenticated; a browser cookie export roughly triples that. A configurable cookie file path is supported but optional. If subtitle fetches start failing with PO-token errors, the `bgutil-ytdlp-pot-provider` plugin is the documented fix; the failure reason should say so.
- Claude Desktop does not support localhost HTTP MCP servers, which is why Desktop is served through the public URL rather than a local bridge.
- The web chat spawns the Claude CLI on the server machine regardless of where the browser is, so remote web chat still uses this machine's Claude login and GPU.
- Implementation should follow the flow in the user's CLAUDE.md: `reviewer` critique of this spec, then `/to-tickets` since this exceeds one session.

## Review amendments (2026-09-13)

A `reviewer` critique found these gaps. Where an amendment conflicts with text above, the amendment wins. Tickets in `.scratch/mentor-v1/issues/` carry the detail.

- **Story 35 dropped**, along with the "stdio proxy". HTTP MCP clients report an unreachable server themselves; the Health endpoint and README troubleshooting cover the rest.
- **Excluded Videos**: Shorts, under-minimum, and out-of-filter Videos get stage `excluded` with a reason. They are not failed and not processed.
- **Discovery** is a cheap flat listing of the Channel's videos tab on every Sync, upserted by YouTube id, with current filters re-applied to decide eligibility. "Only new since last Sync" (story 16) means only new Videos are *processed*; widening a filter makes older Videos eligible. Full metadata (chapters, description) is fetched in the transcript stage.
- **Failures** are classified permanent or transient. A normal Sync resumes non-`done`, non-`failed` Videos and also retries transient failures (e.g. upcoming/live). Retry-failed resets all failures. `pipeline_stage` records the last completed stage; `failure_stage` records the stage attempted. Each stage runs per Video in one transaction that replaces that Video's prior rows for the stage.
- **Store**: foreign keys on for every connection, `busy_timeout` set, short per-Video transactions, deletes cascade into FTS5 and vec0 via triggers. vec0 carries `channel_id` as a metadata column so KNN is scoped *before* top-k. The embedding model name and dimension are stored; a mismatch with config refuses to start. A lease row prevents two Sync workers across processes. Queued Syncs persist, dedupe per Channel, and stale running Syncs are reconciled at startup. A Channel deleted mid-Sync is skipped.
- **Blocking work** (SQLite, torch, yt-dlp) runs off the event loop.
- **Retrieval**: fused RRF list is truncated to the top 50 before reranking. Recency applies a half-life decay to a sigmoid-normalised reranker score, measured from now; `gentle`/`strong` half-lives are configuration with documented defaults. Matched cue = the Segment cue with the highest query-term overlap, else Segment start. Passing both `group` and `mentors` is a validation error; `group` accepts id or name. Descriptions are not FTS-indexed in v1; `get_video` returns them.
- **Models** preload in the background at startup; tools return a "models loading" error until ready; Health exposes progress. A GPU out-of-memory error surfaces as a clear failure.
- **`sql`**: read-only URI connection, `query_only`, extension loading disabled after sqlite-vec loads, an authorizer allowlist, time limit via progress handler, row cap.
- **MCP host check**: allowed hosts are configurable so proxied requests are not rejected by DNS-rebinding protection.
- **Chat lockdown**: `allowed_tools` alone does not restrict tools. The ChatEngine must also disable built-in tools, use only its own MCP config, load no user settings/skills/plugins, and run in a fixed empty working directory. Tools are bound server-side to the Conversation's Group. The user message is persisted before streaming; one turn per Conversation at a time. Stored messages hold durable citation data (Video id, seconds, names), not just segment ids. If the Claude session can't be resumed, the Conversation is replayed from the database.
- **Conversations** survive Group deletion as read-only, as they do for Mentor removal.
- **Access JWT loopback exemption** applies only to loopback requests carrying no `X-Forwarded-*` or `Cf-*` headers, since a local proxy also connects from loopback.
- **Cloudflare Access with MCP clients** is unverified: Access may answer with an HTML login redirect, and Desktop connectors can't send service-token headers. A human-in-the-loop verification ticket decides the working setup.
- **Config**: one TOML file in the XDG config directory, overridable by `MENTOR_*` environment variables.
- **Packaging**: the web bundle is built during the Python package build so `uv tool install` from the repo includes it. Vite uses a relative base so a root path prefix works.
- **Scheduling**: `mentor install-service --timer` installs a systemd user timer that runs `mentor sync --all`. `install-service` records the Claude CLI path.
- **Expected volume** is on the order of 100k Segments; brute-force vec0 scan is acceptable at that scale.
