# 06 — Ship selectable API and CLI chat with coherent history and status

**What to build:** A friend can chat through a stored Anthropic key or their own logged-in Claude Code CLI, with the
same scoped Mentor tools, streamed answers and Citations. Engine choice, model choice, history and health agree on
every surface at the end of the ticket. (Stories 15–16, 19–26, 29, 41–45; backend part of 21 and 42–43.)

**Blocked by:** 05 — Store validated API keys and persistent user preferences.

**Status:** ready-for-agent

- [ ] Add `ApiEngine` behind the existing `ChatEngine` port. Wire both engines, Secrets and preferences through
  explicit application arguments; grow the harness to two fake engines plus fake Secrets. Add no new routing port.
- [ ] Select the engine once at the start of each turn. Honour an explicit preference even when unavailable,
  explaining its missing requirement rather than switching silently. With no preference, choose API when a stored
  key is present, otherwise a logged-in installed CLI, otherwise no engine. An invalid present key is reported as
  such, not silently bypassed through the CLI.
- [ ] No ready engine disables chat alone. HTTP/MCP search, Library and Syncs remain usable. Return actionable
  missing/invalid-key and CLI availability messages; settings changes affect the next turn, not an active one.
- [ ] Derive provider tool schemas from the actual scoped MCP tool listing through one translator. Execute tool
  uses through the in-process scoped server, append provider-compatible results, and repeat until done or the
  existing turn limit. Unknown/disallowed tools cannot escape the Conversation scope.
- [ ] Stream text, tool calls, tool results, completion and failure through the existing event contract. Preserve
  stop/cancellation and resource cleanup. Enable adaptive thinking and cache control on system prompt and tools;
  preserve the provider blocks required for valid multi-step thinking/tool continuations.
- [ ] Use the grounded-advisor prompt and scoped tools for both engines. API turns with project or web context are
  refused before a provider request, including existing Conversations created on the CLI. Do not promise unsupported
  context in the API prompt or implement substitute project/web tools.
- [ ] Give each engine its own mapping from fast/deep choices to identifiers: API Sonnet 5/Opus 5 full IDs versus CLI
  aliases. Verify provider identifiers and SDK support against official documentation when implementing. The API
  default is explicit; the CLI's optional own-default behaviour must not turn into a missing API model.
- [ ] A stored Conversation model remains a pin; an unpinned Conversation uses the current preference on its next
  turn, including mid-thread. Handle existing stored CLI model choices deliberately when switching engines; never
  send a CLI alias verbatim as an API model ID or silently discard a pin.
- [ ] API history is replayed from the store every turn, with a documented bounded truncation rule mirroring CLI
  replay. Handle interrupted/unanswered turns and long history while keeping a valid provider message sequence.
- [ ] Make completion's session identifier optional. A completed API answer clears the old CLI session identifier;
  CLI → API → CLI replays all saved turns rather than resuming a stale session. Session-lost retry remains CLI-only.
- [ ] Add the second additive migration for per-message engine, model and input/output/cache-read usage. Record the
  actual resolved engine/model, aggregate all provider requests within a turn without double-counting streamed
  usage, and expose Conversation totals. Preserve old messages with unknown provenance/usage honestly. Adapt CLI
  event mapping to retain usage when supplied by its SDK; unknown usage is not fabricated as measured zero.
- [ ] Authentication failure during a turn invalidates the stored key state and publishes engine-status change.
  Rate limits/overload say to retry without invalidating the key; other errors expose a safe provider message.
  Health reads last-known key state and never probes the provider, including offline startup.
- [ ] Report both engines' availability and the active engine identity, with `no_key` and `invalid_key` states.
  Publish status changes and consume them in the existing web chat so validation can re-enable the composer without
  reload. Reconnection refreshes the current state rather than relying on an event that was missed.
- [ ] Rename the Claude-specific health field and update the status command's served and no-server paths, web API
  types, App/rail/composer consumers, tests and served bundle in this same ticket. Update serialized message types
  alongside provenance/usage. No merge may leave a client reading the removed field.
- [ ] Make existing composer model options engine-aware and hide project/web context while API is active as part of
  this integration. The richer settings screen belongs to ticket 07; until then API setup is verifiable through
  endpoints and the existing chat UI must already be truthful and usable.
- [ ] Strip `ANTHROPIC_API_KEY` from the CLI subprocess environment without changing the parent process globally;
  retain the unit's explicit unset and the CLI's explanatory degraded state where applicable. The API SDK never
  discovers a credential from the environment.

**Verification:** Direct ChatEngine contract tests use the real Anthropic SDK with injected scripted HTTP transport
and the real in-process scoped MCP server. Cover multi-step tool execution, streaming, usage, turn limit, cancellation
and provider errors. HTTP tests cover both fake engines, selection/model precedence, readiness, context refusal,
restart history and CLI → API → CLI. Test health without provider requests and the complete client rename. Run normal
checks, rebuild the web bundle and keep the served Playwright smoke test green.

**Atomic delivery:** This is intentionally one larger integration ticket. Do not publish ApiEngine without selection
and status, or rename health separately from either client and the rebuilt bundle.
