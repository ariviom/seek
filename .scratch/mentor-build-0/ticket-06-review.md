# Ticket 06 branch review — 2026-09-20

Fixed point: `2ce6f11` (main after ticket 05). Independent Standards and Spec agents reviewed
`git diff 2ce6f11...bb34486`, ticket 06, spec 0003, ADR 0004, CONTEXT and the HANDOFF conventions,
each asked for everything it found rather than a filtered list. Both ran the suite themselves.
The named `opus-worker` agents were available this session and were used for implementation.

## Standards

Eight confirmed defects, all fixed:

- A failing usage write in the turn's `finally` propagated before the stream's terminator was
  queued, so a locked database would have left the SSE reader waiting forever. The write is now
  logged and swallowed; the turn always terminates its stream.
- `TokenUsage` claimed cache writes were counted inside `input_tokens`. They are not — the API
  reports `cache_creation_input_tokens` separately — so the docstring asserted the opposite of the
  truth. Corrected to say the three recorded counts are a floor, which is why no total is presented
  as a bill. The schema stays at the three counts the ticket asked for.
- Three stale README claims (Claude Code listed as a hard prerequisite, engine selection described
  as unreleased, "current chat still uses the CLI") contradicted the same file's new section.
- `_result_text` probed an MCP `CallToolResult` with `getattr` chains behind an `object` parameter,
  which is how it passed `--strict` at all. It now narrows the real type, and an `InputRequiredResult`
  is refused explicitly instead of silently reading as an empty result.
- The cancellation test asserted only that no second request followed, and the transport counter
  written to detect an unclosed body was asserted nowhere. Replaced — see below; this one found a
  real bug.
- `record_usage`'s `usage is None` branch, `_usage`'s `or 0` coalescing and `claude_chat._usage`'s
  `isinstance` guard all defended against states their callers cannot produce.
- The usage totals were written as one query and four correlated subqueries that had to agree by
  hand; they are now one grouped read used by both shapes.
- Smaller: an unnecessary `cast`, a quoted forward reference to a class defined above, a missing
  blank line, four `type: ignore`s removable by annotating a test helper, and import ordering.

**The cancellation test found a real bug.** Rewritten to assert the SDK client is closed, it failed:
`ApiEngine.stream` consumed its inner generator with a bare `async for`, which does not close it when the
consumer stops early, so a stopped turn's Anthropic client and connection were left to the event loop's
async-generator finaliser instead of closing when the turn stopped. `Chat` closes that generator on every
stop and at shutdown, so this affected every cancelled turn. Fixed with `contextlib.aclosing`; the test
fails without the fix. The focused re-review measured the old behaviour and found the finaliser did close
the client within two loop iterations, so this was non-deterministic cleanup rather than an unbounded
leak — the previous test's `await asyncio.sleep(0)` was hiding exactly that.

Two raised items were deliberately left: the `contextvars` token in `suppressed_sdk_logs` is reset in
the consumer's task, which is fragile only for a caller that never closes the generator (all callers
use `aclosing`), and the per-Conversation usage totals have no UI consumer yet because the readout is
ticket 07 — the ticket asked for the totals to be exposed.

## Spec

Nine findings. One is a genuine behaviour gap, now fixed:

- **Context refusal mutated the Conversation before refusing.** `Chat.send` selected the engine and
  saved the question before the API engine ever saw the request, so a Claude CLI Conversation with a
  project directory, once a key was stored, had its question recorded and its stored Claude session
  cleared and *then* failed. The refusal now happens inside `begin_turn`'s transaction, before the
  insert, so it behaves like the unavailable-engine path: a 409, nothing saved, the CLI session intact.
  The adapter keeps its own refusal as the port's guarantee, sharing one message.
- The HTTP-level context test was tautological: it scripted the fake engine to fail and asserted the
  request reached it, so deleting the real refusal left it green. Rewritten to assert the 409, that the
  engine is never called, that no message is saved and that the Claude session still resumes.
- The no-engine 409 quoted only the Claude CLI's message, so an API consumer never learned where to get
  a key. It now carries both engines' instructions.
- `resolve_model` passed any pin verbatim to the Claude CLI, including the full API ids the composer now
  stores — the mirror of the case the ticket forbids. Pins translate in both directions.
- A late rejection of a replaced or **deleted** key had no test through the real `Credentials.replace`
  and `delete`; the existing one swapped the stored envelope by hand. Added one that drives both.
- The rename had no automated guard. The Playwright smoke test now opens the health dialog and asserts
  both engines and the API engine's "where to get a key" message, against a freshly built bundle.
- Stale `HANDOFF.md` prose naming the removed field and the old factory signature: corrected.
- **Accepted behaviour change, documented rather than fixed:** an unpinned Conversation on the Claude
  CLI now asks for `sonnet` instead of letting Claude Code pick its own default. Ticket 05's `settings`
  schema admits only `fast` and `deep`, so there is no value that means "the CLI's own default" without
  reopening a shipped migration. Recorded in the README.
- Open question left as implemented: automatic selection treats an unreadable credential store as "a key
  may be present" and reports the store rather than falling through to a ready Claude CLI, consistent
  with ticket 05's unavailable-credential boundary. The reasoning is now in `active_engine`'s docstring.

Everything else both agents checked held: selection once per turn before the save, explicit-but-
unavailable preferences as errors, invalid key over ready CLI, only chat gated, tool schemas from the
live listing with out-of-scope tools refused, separate model tables, the session cleared in the same
transaction as the question, usage counted once and kept through failure and cancellation, generation-
scoped invalidation, health never calling the provider, `ANTHROPIC_API_KEY` kept from the CLI child and
its probe without touching this process, additive migration 13 with no shipped migration edited, and no
ticket 07 scope built.

## Focused re-review

A third agent reviewed `bb34486..0ffdc94` against the findings above and confirmed every one closed,
with three corrections since applied:

- The claim that all three behaviour bugs had a test failing without the fix was false for the stranded
  stream, which had none. `test_a_turn_whose_usage_cannot_be_recorded_still_ends_its_stream` now makes
  `record_usage` raise and times out without the fix.
- The leak wording overstated what was measured; corrected above and in the code comment.
- The no-engine message test passed against the old hard-coded string too. It now asserts both engines'
  instructions appear.

It also noted `Chat.close()` could re-raise a failed usage write out of the lifespan (now logged there
instead), that the shutdown test does not discriminate the `close()` change it shipped beside (its
docstring no longer implies it does), and that the README's pin sentence read as if both engines refuse
an unknown pin up front when only the API engine does — corrected.

## Verification

- `uv run pytest -q`: 486 passed, 4 opt-in deselected, including the served Playwright smoke test.
- `uv run mypy`: 91 source files pass.
- `pnpm --dir web run typecheck`: passes. Bundle rebuilt into `src/mentor/static/`.
- Model ids and SDK parameters checked against the Claude API reference and `anthropic` 1.7.0 on
  2026-09-20: `claude-sonnet-5`, `claude-opus-5`, `claude-haiku-4-5`, and `thinking={"type": "adaptive"}`
  (`budget_tokens` is rejected on these models).
- The empty-`ANTHROPIC_API_KEY` strip was checked against the real Claude Code 2.1.278: an empty value
  reports no `apiKeySource`, a set one does.
- No live deployment, no live database change, no GPU work.
