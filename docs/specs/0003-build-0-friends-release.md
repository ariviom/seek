# Spec 0003 — Build 0: Mentor on a friend's machine

Status: ready-for-agent
Scope of record for what ships next. `docs/product/desktop-mvp.md` remains the longer-range roadmap; where the two
differ, this spec wins, and the brief's milestones 1 and 4 to 6 are deferred by the decisions below. Glossary unchanged
(ADR 0003): Channel, Group, Video, Transcript, Segment, Citation, Sync, Pipeline stage, Conversation. New decisions:
ADR 0004 (chat engines), ADR 0005 (inference device). Shaped by a grilling session on 2026-09-17.

Execution amendment — Drew, 2026-09-19: no Apple Silicon machine is available. Real Mac testing for tickets
02, 03 and 10 is explicitly deferred. Land ticket 02's reviewed implementation with its recorded Linux CPU/CUDA
evidence, park ticket 03, and continue with ticket 04. Keep Mac checks unchecked with reopening instructions;
this supersedes the Mac-in-this-session closure gates below without claiming MPS or Mac installation verified.

## Problem Statement

Mentor runs on exactly one machine in the world. A friend who wanted to try it could not: the embedding and reranking
models refuse to load without a CUDA GPU, the service is a systemd unit, the data and config directories follow Linux
XDG conventions, yt-dlp needs Deno on PATH, chat requires the Claude Code CLI installed and logged in, and there is no
published package to install from.

The question Drew wants answered is not "does it work" — it does, for him — but "does anyone else keep using it".
That question cannot be asked until roughly five friends, most of them on Apple Silicon Macs, are running Mentor
against creators they chose themselves.

## Solution

A rough, honest, self-installed build. A friend installs Mentor as a uv tool from a public repository, runs
`mentor serve` in a terminal, adds their own Anthropic API key (or uses the Claude Code login they already have), adds
a Channel, watches it Sync with an honest estimate, and asks questions that come back with Citations. Search, the
Library, Syncs and the MCP tools work without any key at all; only chat needs one.

The models run on whatever the machine has — CUDA, Apple Silicon, or CPU — chosen at load. There is no installer, no
code signing, no auto-update, no telemetry, and no hosted anything. Updates are `uv tool upgrade`, which matters
because yt-dlp breaks a few times a year and the fix has to reach five people the same day.

Success is five friends with a Channel of their own choosing, and a conversation about it at the monthly meeting.

## User Stories

### Getting it running
1. As a friend on a Mac, I want to install Mentor with one documented command, so I do not have to understand its build system.
2. As a friend, I want the README to tell me exactly which prerequisites to install first and how long each takes, so I can decide whether to start now or after dinner.
3. As a friend, I want `mentor serve` to start the service in my terminal and print the URL to open, so there is one obvious next step.
4. As a friend, I want to be told plainly that closing the terminal stops Mentor, so I am not surprised when it is gone tomorrow.
5. As a friend, I want the first run to create its own data and config directories in the conventional place for my operating system, so nothing lands where I would not look for it.
6. As a friend, I want the first-run model download to show progress and a total size, so I know whether it is working or hung.
7. As a friend, I want Mentor to work offline once the models are cached, so a bad hotel connection only stops ingestion.
8. As a friend, I want `uv tool upgrade` to be the whole update story, so Drew can fix a YouTube breakage with a one-line message.

### Running the models on my machine
9. As a friend with an Apple Silicon Mac, I want the embedding and reranking models to use the GPU, so ingestion finishes in a plausible amount of time.
10. As a friend with no discrete GPU, I want the models to run on the CPU rather than refuse to load, so Mentor works at all.
11. As a friend, I want to see which device Mentor chose, so I can tell whether it is using my hardware.
12. As Drew, I want my CUDA machine to behave exactly as it does today, so this change costs me nothing.
13. As a friend, I want a model that fails on my device to fall back rather than take the whole app down, so one bad component does not cost me search as well as chat.
14. As Drew, I want proof that search results did not change when the device changed, so I can trust the ranking after the switch.

### Chat, keys, and engines
15. As a friend, I want to use Mentor's search, Library, Syncs and MCP tools before I have supplied any key, so I can see what it does before paying for anything.
16. As a friend without a key, I want the chat composer to tell me plainly what is missing and where to get it, so the dead end is a signpost.
17. As a friend, I want to paste an Anthropic API key into the app once and have it stored in my operating system's keychain, so it is not sitting in a text file.
18. As a friend, I want to know my key was accepted before I rely on it, so a typo surfaces immediately rather than mid-question.
19. As a friend who already has Claude Code installed and logged in, I want to use that instead of an API key, so Mentor costs me nothing extra.
20. As a friend, I want to choose between a fast default model and a slower, better one, so I can spend more only on hard questions.
21. As a friend, I want to see how many tokens a Conversation has used, so I can trust that this is not quietly expensive.
22. As a friend, I want an expired, revoked, or rate-limited key to produce a sentence I can act on, so I am not reading a stack trace.
23. As a friend, I want answers to stream as they are written, with tool calls visible as they happen, exactly as they do on the Claude Code path, so the two engines feel like one product.
24. As a friend, I want the model to be held to the same grounded-advisor rules and the same scoped tools whichever engine runs it, so Citations stay trustworthy.
25. As a friend, I want a Conversation to continue correctly after I close and reopen the app, so my history is real.
26. As Drew, I want each message to record which engine and model produced it, so provenance and cost are answerable later.

### Settings
27. As a friend, I want a settings screen in the app for the things that are mine — engine, key, model — so I never open a TOML file.
28. As a friend, I want my settings to persist across restarts, so I set them once.
29. As a friend, I want changing the model to take effect on my next question without restarting, so it feels like an app.
30. As Drew, I want operational knobs to stay in the config file, so a friend's preferences and my deployment settings never collide.

### Ingesting
31. As a friend, I want the app to tell me to start with a small Channel and why, at the moment I am adding one, so my first Sync finishes while I still care.
32. As a friend, I want a running rate and an estimated finish time during a Sync, so an hour-long wait is a known quantity rather than a hang.
33. As a friend, I want the README to give me a rough per-hour-of-video ingestion rate, so I can predict a Sync before I start one.
34. As a friend, I want a Sync to survive being left alone, and to resume where it stopped when I restart, so an interrupted evening does not cost me the work.
35. As a friend, I want per-Video failures reported without failing the whole Sync, so one unavailable Video does not stop the Channel.

### When it breaks
36. As a friend, I want one command that prints everything Drew needs to diagnose my problem, so support is one paste rather than ten questions.
37. As a friend, I want that output to contain no secrets, so I can paste it into a group chat.
38. As Drew, I want the diagnostic output to name versions, platform, device, model states, paths, and the last errors, so I can answer without a call.

### Using it from my own agent
39. As a friend with Claude Desktop or Claude Code, I want a command that prints the configuration block to register Mentor's tools, so I can consult my Channels from the agent I already use.
40. As Drew, I want to know which surface each friend actually used, so the check-in tells me what Mentor really is to them.

### From the review
41. As a friend on the API engine, I want the project-and-web context option to be absent rather than broken, so the app never promises a capability the engine does not have.
42. As a friend, I want the settings screen to tell me which engines my machine can actually run, so choosing between them is informed rather than a guess.
43. As a friend, I want the chat composer to come alive the moment my key is accepted, without a reload, so the setup step ends where it should.
44. As a friend who switches engines mid-Conversation, I want the thread to stay coherent, so my history is not silently forgotten by the new engine.
45. As a friend, I want a model I pinned in one Conversation to stay pinned, while unpinned Conversations follow my default, so a one-off deep answer does not become permanent.
46. As Drew, I want the diagnostics to redact the YouTube extractor arguments and cookie path as well as the API key, so a pasteable block stays pasteable.
47. As Drew, I want a friend's install to break loudly at the prerequisite step rather than deep inside a build, so "it didn't install" is one question.

## Implementation Decisions

### Inference device (ADR 0005)
- Device choice becomes a pure function of a probe result, ordered CUDA, then MPS, then CPU, and is passed to both
  models. The CUDA-only refusal that exists today is removed; running without a GPU is a supported configuration, not
  an error.
- Precision per device: bfloat16 on CUDA where supported (as today), float32 on MPS and CPU. The default models are
  Qwen-derived and float16 can overflow them; float32 costs memory that a Mac has and time that build 0 accepts.
- The reranker keeps `mixedbread-ai/mxbai-rerank-base-v2` on every device. `mxbai-rerank-xsmall-v2` does not exist —
  the v2 line is base and large only — so the brief's smaller default is not available.
- Known risk, to be verified on a Mac in the same sitting: sentence-transformers' `CrossEncoder` on MPS has produced an
  unsupported-int64-operation failure. It fires when scoring, not when loading, and the model wrapper today only
  catches CUDA out-of-memory — every other exception escapes and turns each search into a server error while health
  still says ready. So the fallback is two things: a warm-up scoring call during load, which is what usually trips the
  fault, and a one-time fallback on the first scoring failure at run time. Either way the reranker alone moves to CPU,
  the embedder is untouched, and the fallback is reported in health and diagnostics rather than hidden.
- A reranker that fails on CPU as well leaves search returning fused results without reranking, not failing. Losing
  ranking quality is acceptable; losing search is not.
- Out-of-memory handling stays CUDA-specific; on MPS and CPU an allocation failure is an ordinary model failure.
- The chosen device, precision, and any fallback appear in `/api/health` and in diagnostics.
- ONNX Runtime is deferred, with a trigger: the first measurement of CPU ingestion on the Windows machine. See ADR 0005.

### Platform paths
- Config and data directory resolution becomes two pure functions of the environment and the platform, in one place.
  Linux behaviour is unchanged (XDG, with `data_dir` continuing to default to the XDG data directory); macOS uses the
  conventional application support directory for both the config file and the database; Windows uses the local and
  roaming application data directories. An explicitly set `XDG_*` variable is honoured on every platform.
- No other module learns about platforms. Keeping this in one module is what makes the later Windows port mechanical.
- This amends ADR 0002, which says the single database file lives in the XDG data directory; that remains true on Linux
  only.

### Chat engines (ADR 0004)
- `ChatEngine` stays the port; `ApiEngine` joins `ClaudeChatEngine` behind it, emitting the same `ChatEvent` stream so
  `Chat`, `chat_api` and the web UI are unchanged.
- `ApiEngine` runs its own tool loop against the Anthropic SDK: send messages plus tool schemas, execute returned tool
  uses against the in-process scoped MCP server, append results, repeat until the model stops or the existing turn
  limit is reached. Streaming is on; adaptive thinking is on; the system prompt and tool list carry cache control.
- Tool schemas are derived from the scoped MCP server's own tool listing and translated to the provider's format by one
  function. They are never hand-copied, so a tool description change cannot drift between engines.
- There is no provider-side session. Conversation history is replayed from our store every turn, and
  `ChatDone.session_id` becomes optional; the existing session-lost retry stays for the Claude CLI path only.
- Default model is Sonnet 5; Opus 5 is selectable as the slower, better answer. Anthropic is the only provider.
- **Model identifiers are per engine and must not be shared.** The Claude CLI takes aliases; the API takes full model
  ids. Each engine owns a small table from a user-facing choice ("fast", "deep") to its own identifier, and the CLI's
  "use its default" (no model) has no API equivalent — on the API engine the default is Sonnet 5, explicitly.
- **Model precedence:** settings hold the default model. A Conversation's stored model, when set, is a deliberate pin
  and wins for that Conversation; Conversations with none follow the setting immediately, including mid-thread. This is
  what makes stories 29 and 45 both true.
- **Read-only project and web context is a Claude CLI capability only.** Those tools are CLI built-ins, not MCP tools,
  and the API engine cannot serve them. In build 0 the API engine refuses a Conversation that asks for either, the
  composer's context option is hidden while the API engine is active, and the system prompt that promises those
  abilities is only used on the CLI path. Building them for the API engine is out of scope.
- **Switching engines mid-Conversation must not resume a stale session.** Accepting and saving an API turn's user
  message clears any stored CLI session id atomically, before provider work starts, so a later CLI turn replays all
  saved history even if the API turn fails or is canceled without an answer. The API engine needs its own history
  truncation rule, mirroring the CLI adapter's replay limit.
- **Key validation happens at entry, and after a failure — never on a health check.** Storing a key makes one cheap
  authenticated call to confirm it works; an authentication failure during a turn marks the key invalid. Health never
  probes the provider, so an offline machine reports the last known state instead of flapping. A change of engine
  status publishes an event, so the composer comes alive without a reload.
  Validation and failure results are tied to the credential generation used: a late result for an old key cannot
  invalidate a replacement key, overwrite its validation state, or undo deletion.
- **An unavailable stored preference is an error, not a silent switch.** A stored engine whose requirement is missing
  reports its own state and says what to add; Mentor does not quietly run the other engine.
- **Health reports the availability of both engines**, not only the active one, because the settings screen has to
  offer a choice the machine can honour.
- Selecting an engine per turn means the application is wired with both engines, the `Secrets` port, and settings, and
  `Chat` chooses between them at the start of each turn. This changes the application factory's arguments — one more
  port per argument, as the existing convention has it — and it is not a new port.
- Per-turn token counts (input, output, and cache reads) are recorded with each message, along with the engine and
  model that produced it, and summed per Conversation for display.
  Reported usage survives failed/canceled turns even when no assistant answer is saved, associated with the
  initiating user message and counted once across the turn. Unknown final usage is marked incomplete rather than
  invented as zero; the readout includes known usage but is not an exact billing statement.
- `ChatEngineStatus` gains the engine's identity and the states `no_key` and `invalid_key`. The health field currently
  named for the Claude CLI is renamed to describe the active engine; the status command and web UI follow.
- Engine selection lives in settings. With no stored preference, Mentor uses the API engine when a key is present,
  otherwise the Claude CLI when it is installed and logged in, otherwise no engine — which disables chat and nothing
  else.
- Provider errors are mapped to user-facing sentences: an authentication failure is an invalid key, a rate limit or
  overload says to try again, everything else reports the provider's message.

### Secrets
- A new `Secrets` port (get, set, delete by name) is injected into the application beside the other ports. The
  production backend is the OS keychain via `keyring`.
- Headless Linux may have no keychain, or one that is present but locked with no way to prompt. Any keyring failure —
  missing backend, locked collection, or a refused prompt — falls back to a file in the data directory with owner-only
  permissions, and diagnostics say which store is in use and why.
- **There is deliberately no `ANTHROPIC_API_KEY` fallback.** The systemd unit unsets that variable on purpose, and the
  Claude CLI reports a degraded state when it sees one in Mentor's environment — an environment fallback would make a
  friend who exported a key bill it through their subscription path without knowing. For the same reason, the CLI
  adapter strips that variable from the subprocess environment it launches, and the unit keeps unsetting it.
- A key is written through the API and never read back: responses report presence and validity only.
- On macOS, reading a keychain item from an interpreter that was just replaced by `uv tool upgrade` can raise an
  allow/always-allow prompt. The README says so, so the first upgrade is not mistaken for a bug.

### Settings
- A new `settings` table holds user preferences as typed key/value rows: chat engine, provider, model. It is read and
  written over new settings endpoints and a change publishes an event, so an open tab updates like everything else.
- The rule, to be stated in the README and honoured by every later ticket: **the config file holds operational
  settings, the settings table holds user preferences, the keychain holds secrets, and a friend touches only the UI.**

### Lifecycle and distribution
- `mentor serve` in the foreground is the supported way to run Mentor off Linux. The systemd install path is untouched
  and refuses on other platforms with a message pointing at `mentor serve`.
- There is therefore no scheduled Sync off Linux in build 0. Syncing is the button in the UI and `mentor sync`.
- Mentor is installed from a public repository as a uv tool and updated with `uv tool upgrade`. No PyPI publication yet.
- **Installing from a repository builds the wheel on the friend's machine, and the build hook compiles the web UI**, so
  Node and pnpm are prerequisites, not optional. Rather than treat that as a cost, use it: require Node 22, and pass
  yt-dlp a runtime list that includes Node so the same install satisfies the build and the caption fetching. Deno stays
  supported and is what Drew's machine uses. The alternative — committing or publishing the built bundle so no Node is
  needed — is the thing to reconsider if a friend stalls at this step.
- yt-dlp is pinned exactly in the project metadata, not floored. A repository install resolves from metadata and never
  sees the lockfile, so a floor means every friend silently gets a different yt-dlp, which is the opposite of what
  pinning is for.
- The README is rewritten as a per-operating-system setup path: prerequisites (uv, Node, and a JS runtime for yt-dlp)
  with a check command for each, install, first run with its download size, adding a first Channel with advice to start
  small, and the ingestion rate estimate. Prerequisites are verified up front, so a missing one fails at step one
  rather than inside a build log.

### Diagnostics and agent registration
- `mentor doctor` prints one pasteable block: Mentor and Python versions, platform, selected device and precision,
  model states, config and data paths, effective settings, which secret store is in use, chat engine status for both
  engines, yt-dlp and JS runtime availability, database schema version and row counts, and recent errors.
- Recent errors come from what is already stored — model status errors, failed Videos with their reasons, failed Syncs
  — not from a new log buffer. The point is to explain a stuck install, and those three cover it.
- Redaction covers the API key, the YouTube extractor arguments (which can carry a token) and the cookie file path, not
  just the key. A block that needs reading before pasting is not a pasteable block.
- `mentor mcp-config` prints the configuration for registering Mentor's tools with a client that speaks streamable
  HTTP over loopback — Claude Code and equivalents. Claude Desktop's custom connectors need a public URL, so the
  command says that plainly instead of printing something that will not work.

### Web UI
- A settings screen: engine choice showing each engine's availability, API key entry and validation, model choice, and
  a read-only device and model readout.
- The composer is disabled without a ready engine, and says what to add and where to get it. Search, Library and Syncs
  stay fully usable. It re-enables on the engine-status event, without a reload.
- The context option in the composer is hidden while the API engine is active.
- A per-Conversation token readout.
- Sync rate and ETA retain compatible count/time baselines after process restart, or warm up a fresh observed
  interval without resetting total progress. Pre-restart completion counts cannot be divided by post-restart time.
- The health indicator reflects the active engine's state, including `no_key` and `invalid_key`.
- Renaming the health field is a breaking API change for the web client and the status command. The rename, the two
  clients, their tests, and the rebuilt bundle land in one ticket; splitting them leaves `main` with a UI that throws
  on a missing field.

### Retrieval regression set
- Roughly ten real questions across the existing Groups, each with the Videos that must appear, kept as a fixture file
  rather than in code. It runs opt-in against the real models, and is executed on CUDA before the device change and on
  MPS after it. It exists to catch silent ranking drift, and it is the regression test for every later retrieval change.
- It runs against a **frozen snapshot copy** of the populated database, located by an environment variable and skipped
  when absent. The existing real-model test builds a temporary database with fake transcripts, which cannot answer this
  question. The snapshot is taken once and never re-synced: a Sync between the two runs changes the candidate pool and
  invalidates the comparison.
- Be clear about what the MPS run measures. Stored vectors were embedded on CUDA and are reused, so the comparison
  covers query embedding and reranking, not passage embedding. Passage-embedding drift across devices is a separate
  question, and it only matters when a friend ingests on one device what they search on another — which, for build 0,
  nobody does.
- Run it on the CUDA machine with the service stopped. Loading a second copy of both models beside the running service
  and whatever else holds the GPU is how that run fails for uninteresting reasons.

## Testing Decisions

A good test here asserts behaviour a user could observe, at the highest seam that can observe it, and never reaches
into implementation. Prefer the existing seams; this spec adds exactly one new one.

- **HTTP API through the existing running-app harness** for everything user-visible: the settings endpoints, key
  presence and validation, chat with and without a ready engine, engine selection precedence, model precedence between
  a pinned Conversation and the setting, refusal of project or web context on the API engine, and the health shape.
  This is where most of the new tests live. The harness supplies one chat engine fixture today; it grows to two
  injectable fake engines plus a fake `Secrets`, which is what lets selection be tested as behaviour rather than
  wiring.
- **The `ChatEngine` port** for `ApiEngine`, tested directly as request in, event stream out, with the Anthropic SDK
  given an injected HTTP transport returning scripted wire responses. This exercises the real SDK, schema translation,
  tool execution against a real in-process scoped MCP server, event mapping, the turn limit, and error mapping, with no
  network and no new port. Prior art: the existing Claude CLI adapter tests.
- **The new `Secrets` port**, faked in tests and keychain-backed in production, so key handling is exercised from the
  API seam rather than by patching a third-party module. Its fallback order is unit-tested against an unavailable
  backend.
- **Pure functions** for device selection and for config and data directory resolution, each taking its inputs as
  arguments (probe result; environment and platform). Prior art: the existing config, ranking and youtube pure-function
  tests.
- **Opt-in real-model tests** for the device work, using the existing marker. The retrieval regression set shares the
  marker but not the fixture: it needs the frozen snapshot database described above, not the fake-transcript database
  the existing real-model test builds.
- **CLI tests against a served app** for `mentor doctor` and `mentor mcp-config`, including the no-server case. Prior
  art: the existing status command tests. Diagnostics are asserted to contain no secret material.
- **The Playwright smoke test** stays green, extended with the settings screen and the no-engine composer state.
- **Manual**, on a Mac: install from the public repository as a friend would, ingest a small Channel, ask a question,
  and run the regression set. No ticket is done because its unit tests pass if this path is broken.

## Out of Scope

- ONNX Runtime, quantised models, and CoreML or DirectML execution providers (ADR 0005 records the trigger).
- Gemini, OpenAI, or any provider other than Anthropic.
- The Tauri shell, PyInstaller sidecar, code signing, notarization, auto-update, and installers of any kind. A
  throwaway spike runs alongside this work and ships nothing.
- The native Windows port. Path handling is written to accommodate it; nothing else is.
- Playlists. Scoping to a Channel's playlists over already-ingested Videos is the shape we want later, which is
  precisely why no source-kind abstraction is introduced now. Single Videos are out permanently: YouTube does that.
- Group recipes, storyboard frames on Citations, a bundled demo database, and a model bake-off eval.
- Telemetry, usage reporting, accounts, and anything hosted. Usage is learned by asking friends at the monthly meeting.
- launchd, Windows services, and any replacement for systemd's scheduled Sync.
- Read-only project and web context on the API engine. It is a Claude CLI capability and stays one.
- Showing a Channel's Video count before the first Sync. Getting it means a paced YouTube listing that can take
  minutes, which is a worse first impression than the advice to start small.
- Registering Mentor with Claude Desktop, which needs a public URL. Drew's remote access already covers his own case.

## Further Notes

- Suggested ticket order, revised after review: retrieval regression set; device selection with the Mac verification;
  platform paths and the off-Linux lifecycle (service install refusing with a pointer to `mentor serve`, which prints
  its URL and says that closing the terminal stops it); `Secrets` and the settings table with their endpoints;
  `ApiEngine` with engine selection, the health-field rename and both its clients in the same ticket; the web settings
  screen, context-option hiding and token readout; `mentor doctor` and `mentor mcp-config`; prerequisites, README,
  pinning and the public repository. `main` works after every ticket, as in v2.
- Schema work is two additive migrations — the settings table, and the per-message engine, model and token columns —
  which the existing migration rules allow as string entries. The message shapes the web client reads change with them.
- Mac access is a precondition, not a nice-to-have: three tickets cannot close without it.
- The regression set comes first on purpose: it is the only thing that can prove the device change did not degrade
  ranking, and it is worthless if written after the change.
- Running in parallel, as a throwaway spike whose only output is an answer: does a frozen bundle of the service start
  inside a Tauri shell, can it load the sqlite-vec extension, does torch with MPS survive freezing, does a bundled
  QuickJS satisfy yt-dlp, and does the sidecar die when the app quits. It decides whether a signed installer is weeks
  or months away; it does not block anything here.
- The Apple Developer Program fee is only required to hand someone a built application. A friend who compiles locally
  hits no Gatekeeper prompt, which is another reason build 0 ships as source.
- The older-ticket prerequisite was resolved on 2026-09-18: v2 ticket 06 (broad UI finish) and v1 ticket 18
  (Cloudflare Access client verification) are explicitly parked, not completed. Their tickets and `HANDOFF.md`
  record why and when to reopen them; build-0 acceptance criteria still require fixing any blocking friend workflow.
