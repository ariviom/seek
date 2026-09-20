# Ticket 05 branch review — 2026-09-19

Fixed point: `e752f13` (main after ticket 04). Independent Standards and Spec agents
reviewed `git diff e752f13...5d68696` and the follow-up `5d68696..7775530`, ticket 05,
spec 0003, CONTEXT, HANDOFF conventions and the relevant ADRs. Available worker agents
substituted for the handoff's unavailable named Opus workers.

## Standards

Zero documented-standard violations and zero actionable smell findings. Separate injected
ports, additive migration, typed preferences, external-boundary fakes and running-app tests
preserve existing conventions. Focused re-review confirmed zero remaining findings.

## Spec

One initial finding: a credential stored only in a keychain cannot be copied to fallback if
that keychain becomes unreadable after a restart. An unconditional plaintext backup would
contradict story 17. The spec now explicitly records the boundary: recoverable credentials
fall back durably; unknown locked credentials report unavailable, preserve the key, and allow
unlocking, replacement or deletion. Diagnostics were corrected to avoid claiming a working
fallback in this state. An added running-app test exercises replacement into fallback,
restart persistence, deletion and recovery without resurrecting the original key.

Independent focused re-review closed the finding. No other missing or partial requirements,
scope creep or implementation errors were found. CLI chat and its health contract stay intact.

## Verification

- `uv run pytest -q`: 442 passed, 4 opt-in deselected, including Playwright smoke.
- `uv run mypy`: 86 source files pass.
- `pnpm --dir web run typecheck`: pass; no web source changes.
- Final focused credential/storage checks: 30 passed. Scripted HTTP exercises the real
  Anthropic SDK, including authentication rejection, transient failures, environment auth
  isolation, debug-log redaction, canceled writes and generation races. No live provider calls.
- Real frozen baseline preparation check passed checksum, schema-11/model verification and
  disposable-copy validation. Original corpus and fixture manifest unchanged; no model inference
  was changed or rerun for this ticket.
- No live service deployment, live database migration, or real keychain modification.
  Mac hardware verification remains deferred by Drew.

Standards: 0 findings. Spec: initial 1, resolved 1, remaining 0.
