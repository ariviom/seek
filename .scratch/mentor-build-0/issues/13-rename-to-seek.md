# 13 — Rename Mentor to Seek before the first public push

**What to build:** Everything a friend installs, runs, reads or registers is called Seek, so the public repository
starts under its real name and no friend ever needs migrating from Mentor. Drew's own installation moves across
once, by hand.

**Blocked by:** None. Ticket 10's publication step waits for this.

**Status:** ready-for-agent

**Decisions (Drew, 2026-10-10):** the name is Seek, and the public repository is `git@github.com:ariviom/seek.git`
(public, empty). The rename lands before the first push. The logo is option 3 from the brand exploration: a custom
geometric S with 45° cut ends, and a K that is a video player's "previous" icon. The S–E gap is 9.5 units, against
14 between the other letters. The assets are in `docs/brand/`: `seek-logo.svg` (currentColor), `seek-logo-accent.svg`
(K in `#ff4a2b`) and `seek-mark.svg` (the K alone).

**Where the name is contractual, not just text:**

- Distribution and CLI: `pyproject.toml` `name` and `[project.scripts]`, `importlib.metadata.version("mentor")` in
  `doctor.py`, `argparse` `prog`, and the `src/mentor` package itself, which every import uses.
- Paths: `config.config_dir`/`data_dir` (`…/mentor` on every platform) and the database name `mentor.db`.
- Keychain: the service name `"mentor"` in `secrets.py`.
- Linux service: `UNIT_NAME` and `TIMER_NAME` in `service.py`, and the unit's recorded environment.
- Agents: the MCP server name in `mcp_server.py` and `mcp_config.py`, the in-process tool server name in
  `claude_chat.py` (tool names become `mcp__seek__…`) and `CLAUDE_AGENT_SDK_CLIENT_APP`. Also any instruction or
  system-prompt text that names Mentor.
- Environment: `MENTOR_CLAUDE_CLI_PATH`, and the test-only `MENTOR_RETRIEVAL_*` / `MENTOR_DEVICE_*` / `MENTOR_VERIFY_*`.
- Web: `<title>`, user-facing copy, a wordmark or favicon from `docs/brand/`, and FastAPI's `title`. Then rebuild the
  served bundle.

- [ ] Rename all of the above. No compatibility aliases: no friend has installed Mentor, so there is nothing to keep
  working under the old name.
- [ ] Update README, CONTEXT.md and the live docs to Seek. Leave ADRs, closed specs, closed tickets, recorded baselines
  (`docs/baselines/*.json`) and HANDOFF history as written, because they record what was true then. Add one line to
  HANDOFF recording the rename.
- [ ] Use the logo in the web UI (a favicon from `seek-mark.svg`, plus the wordmark wherever the rail or header shows
  the product name). Check it in light, dark and at 390px.
- [ ] Write Drew's one-time migration as documented manual steps, not code. Stop and uninstall `mentor.service` and
  its timer; move `~/.config/mentor` → `~/.config/seek` and `~/.local/share/mentor` → `~/.local/share/seek`, renaming
  `mentor.db` → `seek.db`; reinstall the tool as `seek`; `seek install-service`; re-enter the Anthropic key in Settings
  (the old keychain item can then be deleted); re-register MCP clients under `seek`. Run them, and check that Channels,
  Conversations and search all survive.
- [ ] Leave the frozen baseline snapshot where it is (`~/.local/share/mentor-baselines`). Only the variable names
  pointing at it change.

**Verification:** pytest, mypy and the web typecheck pass. The bundle is rebuilt and the browser smoke tests are
green. `git grep -i mentor` turns up only the historical records listed above. Drew's migrated installation is
active, with its data intact.

**Publication, after this lands (the release action in ticket 10, decided 2026-10-10):** keep the full history, but
first rewrite it with `git filter-repo` to redact `remote.example.com`, `myteam.cloudflareaccess.com` and the
Access AUD in `.scratch/mentor-v1/issues/18-…`. Push only `main`; never the `refs/t3/checkpoints` refs, which hold a
committed `.mypy_cache`. HANDOFF and `.scratch/` stay public. Because the rewrite changes every hash, finish or
rebase the open worktrees first, then check that `git log -p main | grep -E 'drewcoffin|ariviom\.cloudflare'` comes
back empty before pushing.
