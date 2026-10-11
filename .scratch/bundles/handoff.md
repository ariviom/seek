# Handoff — finishing Bundles (tickets 02 to 06)

Spec 0005 was designed, critiqued, and broken down in an earlier session, and Drew approved it. Ticket 01 is done.
You are running `/implement-spec` for the five tickets that remain. Don't reopen design decisions: if a ticket looks
wrong, say so in one line and ask.

## Where things stand
- The integration branch already exists: `t3code/export-shareable-channel-embeddings`, in the worktree
  `/home/drew/.t3/serve/worktrees/mentor/t3code-999889a2`. Ticket 01 is on it (`dad580c`, `24bfca1`, `d5a2d6a`).
  Don't create another integration branch. The fixed point for the final review is `e3872f6`.
- Nothing is pushed. Don't push, merge to `main`, or deploy without asking Drew.
- The tracker is local markdown (`docs/agents/issue-tracker.md`), so there is no PR to open.

## Read first, in this order
1. `CONTEXT.md`: the glossary. **Bundle** is the new term; avoid "pack", "archive", and "export" as a noun.
2. `docs/specs/0005-bundles.md`: the spec. §Testing Decisions names the seams; don't add new ones.
3. `.scratch/bundles/README.md`: the ticket table and blocking edges.
4. Ticket 01's `## Comments` (`issues/01-…md`): the Bundle's table layout, the readings taken, and a "For later
   tickets" list with one entry each for 02, 03, and 05.
5. Ticket 02's `## Comments`: what the commit security review found in import as it stands.
6. `ticket-01-review.md`, then `src/seek/bundles.py` and `tests/test_bundles.py`. They are short, and they are the
   map: an exploration subagent is not needed.

## The task graph is a line
The blocking edges leave 02, 03, and 05 open at once, but each rewrites the same `import_bundle`, so the README's
rule stands: one ticket at a time, in number order, **02 → 03 → 04 → 05 → 06**. One implementer runs at a time and
each merge into the integration branch is a fast-forward.

Ticket 02 goes first for a second reason: until it lands, import trusts the file, and the branch must not be used on
a Bundle from someone else.

## How to work
- Subagents go through the definitions in `~/.claude/CLAUDE.md`: implementers ride Opus (`worker`, or the high-effort
  definition for 02 and 03), and review goes to `reviewer`. Brief each one with pointers to the files above, not
  with their contents.
- Each implementer builds test-first with `tdd`, at the spec's seams: the two command functions called with
  `bundle_config`, asserted through an app started on the second data directory; hand-built files through
  `import_bundle` for refusals; CLI parsing in `tests/test_cli_lifecycle.py`.
- Verify with `uv run pytest -q && uv run mypy`. No ticket adds a migration or touches the web.
- When a ticket is done: tick its criteria, set `Status:` to done in the ticket and the README table, append a
  note under `## Comments` (what landed, readings taken, what later tickets need to know), and commit.
- One `code-review` pass on the whole branch at the end, against `e3872f6`, with its record in
  `.scratch/bundles/review.md`.

## Things that will bite
- Ticket 01 refuses a Bundle whose Channel or Videos the knowledge base already has (`_known` in `bundles.py`).
  That stand-in goes in 03. Three tests pin it and change on purpose then: the second import in
  `test_import_says_what_it_added…`, `test_import_refuses_a_bundle_whose_videos…`, and the second import in the CLI
  round trip. Name each changed assertion in the ticket's comment.
- A new worktree needs `pnpm --dir web install --frozen-lockfile` before the Playwright smoke tests can build the
  web bundle.
- `tests/test_doctor.py::test_secrets_only_the_installed_service_knows_are_redacted_too` fails on this branch while
  `~/.config/seek/config.toml` carries `model_idle_unload_seconds`, a key from other work. It passes with `HOME`
  set to an empty directory. The smoke test `test_setting_up_chat…` failed for a few minutes once under load and
  passes otherwise. Neither is a Bundles regression; leave both alone and say so in the report.
- A security review runs in the background after each commit. When its notification is only a summary line, the
  detail is `.previous_findings` in the newest `~/.claude/security/security_warnings_state_*.json`. Fix what
  belongs to the ticket in hand; record the rest on the ticket that owns it.

## Done when
Tickets 02 to 06 are done, the verification passes apart from the two environmental failures above, the branch has
had its review with findings fixed, the implementer worktrees are removed, and Drew has the branch name and what is
left for him to decide (pushing and merging).
