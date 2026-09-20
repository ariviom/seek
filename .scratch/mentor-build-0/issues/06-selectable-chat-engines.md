# 06 — Ship selectable API and CLI chat with coherent history and status

**What to build:** A friend can chat through a stored Anthropic key or their own logged-in Claude Code CLI, with the
same scoped Mentor tools, streamed answers and Citations. Engine choice, model choice, history and health agree on
every surface at the end of the ticket. (Stories 15–16, 19–26, 29, 41–45; backend part of 21 and 42–43.)

**Blocked by:** 05 — Store validated API keys and persistent user preferences.

**Status:** complete

- [x] Add `ApiEngine` behind the existing `ChatEngine` port. Wire both engines, Secrets and preferences through
  explicit application arguments; grow the harness to two fake engines plus fake Secrets. Add no new routing port.
- [x] Select the engine once at the start of each turn. Honour an explicit preference even when unavailable,
  explaining its missing requirement rather than switching silently. With no preference, choose API when a stored
  key is present, otherwise a logged-in installed CLI, otherwise no engine. An invalid present key is reported as
  such, not silently bypassed through the CLI.
- [x] No ready engine disables chat alone. HTTP/MCP search, Library and Syncs remain usable. Return actionable
  missing/invalid-key and CLI availability messages; settings changes affect the next turn, not an active one.
- [x] Derive provider tool schemas from the actual scoped MCP tool listing through one translator. Execute tool
  uses through the in-process scoped server, append provider-compatible results, and repeat until done or the
  existing turn limit. Unknown/disallowed tools cannot escape the Conversation scope.
- [x] Stream text, tool calls, tool results, completion and failure through the existing event contract. Preserve
  stop/cancellation and resource cleanup. Enable adaptive thinking and cache control on system prompt and tools;
  preserve the provider blocks required for valid multi-step thinking/tool continuations.
- [x] Use the grounded-advisor prompt and scoped tools for both engines. API turns with project or web context are
  refused before a provider request, including existing Conversations created on the CLI. Do not promise unsupported
  context in the API prompt or implement substitute project/web tools.
- [x] Give each engine its own mapping from fast/deep choices to identifiers: API Sonnet 5/Opus 5 full IDs versus CLI
  aliases. Verify provider identifiers and SDK support against official documentation when implementing. The API
  default is explicit; the CLI's optional own-default behaviour must not turn into a missing API model.
- [x] A stored Conversation model remains a pin; an unpinned Conversation uses the current preference on its next
  turn, including mid-thread. Handle existing stored CLI model choices deliberately when switching engines; never
  send a CLI alias verbatim as an API model ID or silently discard a pin.
- [x] API history is replayed from the store every turn, with a documented bounded truncation rule mirroring CLI
  replay. Handle interrupted/unanswered turns and long history while keeping a valid provider message sequence.
- [x] Make completion's session identifier optional. Clear the old CLI session identifier atomically when accepting
  and persisting an API turn's user message, before starting provider work. CLI → API → CLI must replay every saved
  turn even if the API turn fails or is canceled without an answer. Session-lost retry remains CLI-only.
- [x] Add the second additive migration for per-message engine, model and input/output/cache-read usage. Record the
  actual resolved engine/model, aggregate all provider requests within a turn without double-counting streamed
  usage, and expose Conversation totals. Preserve old messages with unknown provenance/usage honestly. Adapt CLI
  event mapping to retain usage when supplied by its SDK; unknown usage is not fabricated as measured zero.
- [x] Persist reported usage even when a later tool-loop request fails or the turn is canceled. Associate that
  accounting with the originating user message so it survives without saving a partial assistant answer, and count
  each provider request once on successful completion too. Mark incomplete/unreported usage explicitly; totals
  include known usage from failed/stopped turns without claiming to be an exact provider bill. Include the needed
  accounting/completeness fields in the same additive message migration.
- [x] Authentication failure during a turn invalidates only the credential generation used by that turn and
  publishes engine-status change only if that generation is still current. A delayed failure from old key A must
  not invalidate newly validated key B or undo key deletion. Coordinate this with the credential state from 05.
  Rate limits/overload say to retry without invalidating the key; other errors expose a safe provider message.
  Health reads last-known key state and never probes the provider, including offline startup.
- [x] Report both engines' availability and the active engine identity, with `no_key` and `invalid_key` states.
  Publish status changes and consume them in the existing web chat so validation can re-enable the composer without
  reload. Reconnection refreshes the current state rather than relying on an event that was missed.
- [x] Rename the Claude-specific health field and update the status command's served and no-server paths, web API
  types, App/rail/composer consumers, tests and served bundle in this same ticket. Update serialized message types
  alongside provenance/usage. No merge may leave a client reading the removed field.
- [x] Make existing composer model options engine-aware and hide project/web context while API is active as part of
  this integration. The richer settings screen belongs to ticket 07; until then API setup is verifiable through
  endpoints and the existing chat UI must already be truthful and usable.
- [x] Strip `ANTHROPIC_API_KEY` from the CLI subprocess environment without changing the parent process globally;
  retain the unit's explicit unset and the CLI's explanatory degraded state where applicable. The API SDK never
  discovers a credential from the environment.

**Verification:** Direct ChatEngine contract tests use the real Anthropic SDK with injected scripted HTTP transport
and the real in-process scoped MCP server. Cover multi-step tool execution, streaming, usage, turn limit, cancellation
and provider errors. HTTP tests cover both fake engines, selection/model precedence, readiness, context refusal,
restart history and CLI → API → CLI after successful, failed and canceled API turns. Verify retained usage after a
successful tool-loop request followed by failure/cancellation, and a delayed key-A rejection after replacing it with
validated key B. Test health without provider requests and the complete client rename. Run normal
checks, rebuild the web bundle and keep the served Playwright smoke test green.

**Atomic delivery:** This is intentionally one larger integration ticket. Do not publish ApiEngine without selection
and status, or rename health separately from either client and the rebuilt bundle.
