# Ticket 07 branch review — 2026-09-21

Fixed point: `9d5f479` (main after ticket 06). Independent Standards and Spec agents reviewed
`git diff main...HEAD` at `21bd40b`, ticket 07, spec 0003 (stories 16–18, 20–21, 27–29, 41–45),
ADR 0004 and the HANDOFF conventions, each asked for everything it found rather than a filtered
list. Both ran the checks themselves.

## What the reviews found, and what changed

Two findings were about the UI claiming things the server does not do, and they were the round's
real defects:

- **The composer was only closed when *no* engine was available.** With a rejected key and no CLI,
  or an explicit preference for an engine that can't run, the question box stayed open and the turn
  died with `choose_engine`'s 409 after the question had been typed. `Composer` now takes a
  `Blocked` reason — `no_engine`, `engine_unready` or `context` — computed in `ConversationView`
  from the same facts the server decides on, and closes the box for all three.
- **A Conversation carrying project or web context could still be created on the API engine.** The
  explanation was shown only once the context was locked, so a new chat that had context typed
  while the CLI was active, then flipped to the API, could be created and immediately became
  unanswerable. The `context` block now covers the unlocked case with its own wording (remove the
  context, or switch engines), and nothing removes the saved context either way.

Honesty fixes to what the screen says:

- "Whichever is ready" promised a selection rule `engines.active_engine` does not implement. The
  option is now "Automatic", with a line saying it takes the API whenever a key is stored and does
  not switch engines behind your back when the one it picked can't answer.
- A failed `GET /api/settings` was swallowed and silently became "fast", so the badge and composer
  asserted a default that may not be the saved one. `App` keeps the error, passes it to the screen,
  and every surface says "your default" until the real one is known.
- An unreadable credential store hid the Delete button and left "Checking the stored key…" on
  screen forever. Deletion is offered exactly then — an unreadable key is one worth deleting — and
  the line says the key can't be read.
- The private-file line could appear when no key was stored at all, because the store still reports
  the routing its last operation took. It is shown only when a key is present.
- "These follow your hardware and aren't a setting" was untrue of the model names, which come from
  `config.toml`; the section now separates the two.
- Settings marked the chosen engine "(answering)" while the rail says "(active)"; both say
  "(active)" now, which is what checkbox 6 asks for.
- The incomplete-usage line said turns "didn't report all they used" when the commonest cause is a
  turn that reported nothing at all.
- README's "Accepting a key brings the chat box to life in every open tab" is only true when the
  engine isn't pinned to the CLI, and its Settings section now says what happens when the keychain
  can't be read.

Standards fixes:

- `Credentials._status` read `Secrets.status` outside the lock, so a concurrent replacement's
  routing could be reported as this call's. Both `status()` and `delete()` now read it under the
  lock; the comment no longer claims a guarantee the code didn't provide.
- `tests/test_credentials.py`'s keychain-refusal assertion had been loosened from exact dict
  equality to a field check. Restored to exact equality, including the fallback reason, with the
  key-not-echoed assertion the neighbouring case has.
- The token totals lived inside `Composer`, which a read-only Conversation doesn't render, so
  deleting a Group hid totals the store still holds. They moved to `ConversationView`.
- `HANDOFF.md` said `models.ts` owns the model tables that `engines.py` mirrors, which inverts the
  truth: the server resolves every model a turn asks for, and `models.ts` is a display copy. Both
  the ticket paragraph and the conventions entry now say so.
- `models.ts` didn't know `claude-haiku-4-5`, so a Conversation pinned to the CLI's `haiku` read as
  a raw id on the API engine; `modelName` now searches both vocabularies.
- Smaller: the "Default: …" wording was re-spelled inline in the composer instead of calling
  `conversationModel`; the option list duplicated its own `.map`; `modelChoices` wasn't `as const`;
  number formatting belonged in `lib/format.ts`; the sentinel constant lost its comment in a
  rename; `choiceModelName` had an unreachable branch; two single-child flex wrappers; a
  118-character import; two consecutive `if`s on the same condition; README reflow.
- Accessibility: the screen had no `<h1>` while every other main-pane page does, and focus was
  dropped on `<body>` when "Open settings" unmounted the button that was clicked. The heading is
  now the page's `h1` and takes focus when the screen opens. `autoComplete="off"` on the key box
  became `new-password`, which is the value Chrome's password manager honours.

Test coverage added for the branches the ticket names: the smoke test now drives a turn that
reports one request's usage and then fails, asserting the "at least" total, and deletes the key
through the confirm dialog, asserting chat goes back to its dead end. Visibility assertions were
added after each rail click, since the chats pane stays mounted while hidden.

## Deferred, with the owning ticket

- **Ticket 06 — a CLI turn's missing cache-read count is recorded as a measured zero.**
  `claude_chat._usage` emits a `UsageReported` when *any* of the three counts is present and fills
  the rest with 0, and `ChatDone` then marks the turn complete, so a CLI result carrying only input
  and output tokens shows "0 cache read" with no caveat. Representing unknown per-count usage needs
  `TokenUsage` and the `messages` columns to distinguish absent from zero, which is ticket 06's
  model, not this screen.
- **Ticket 06 — a stopped turn's usage can be one list reload late.** `_save_usage` shields its
  write but `_run` queues the stream terminator without waiting for it, so the client's reload after
  a stop can read totals that are about to change; no event is published on message save.
- **Ticket 07 — a Conversation pinned to a model the API engine cannot express has no remedy on
  screen.** `resolve_model` raises a Conflict advising "choose another model for it", but a saved
  Conversation's pin is immutable: `PATCH /api/conversations/{id}` only accepts a title. Changing a
  pin after creation is new API surface and was not in this ticket.

## Verification

- `uv run pytest -q`: 487 passed, 4 opt-in deselected, including both served Playwright tests.
- `uv run mypy`: 91 source files pass. `pnpm --dir web run typecheck`: passes.
- Bundle rebuilt into `src/mentor/static/`.
- The screen was driven in a real browser in light and dark themes and at 390px wide; the
  automated theme and responsive coverage remains the first smoke test's, which exercises the
  shell rather than this screen.
- No live deployment, no live database change, no GPU work, no live provider key: the Anthropic
  transport is scripted in every test.
