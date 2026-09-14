# 01 — Channel model: backend

**What to build:** Collapse Mentor into Channel across the Python package per ADR 0003 and spec 0002 §Domain. After this ticket the schema, store, API, MCP tools, prompts, and CLI speak of Channels and Groups only, and a Conversation can be scoped to one Channel. The web UI is touched only where a build would otherwise break (ticket 02 does the web rename); serve the v1 bundle as is.

**Blocked by:** nothing

**Status:** done

Schema
- [x] `db.py`: `MIGRATIONS` entries are `str | Callable[[sqlite3.Connection], None]`; `migrate()` runs a callable with `PRAGMA foreign_keys = OFF` before `BEGIN`, `PRAGMA foreign_key_check` before `COMMIT`, foreign keys on again after. Failures stay `RuntimeError` so `status_command._read_store` and `sync_command._run_here` keep their handling.
- [x] Migration 9 as the callable in spec 0002 §Domain: `channels` (AUTOINCREMENT, no owner, filters kept, same ids), `groups`, `group_channels`, `conversations` (`group_id`, `channel_id`, `scope_kind`, `scope_name`); copy data; drop `conversations`, `channels`, `mentor_group_members`, `mentor_groups`, `mentors`; rename new tables; recreate indexes. Comment why AUTOINCREMENT, per the file's convention.

Store
- [x] `channels.py` replaces `mentors.py` (spec §Domain); `rename_channel` updates `scope_name` of Channel-scoped chats and publishes `events.syncs()`.
- [x] `groups.py`: `Group.channels`, members by channel id, `group_summaries` and `channel_summaries`.
- [x] A `Scope` type used by `conversations` (`create_conversation(scope, model)`, read-only check on the scope's id column, `_citations` restricted to the scope, `list_conversations(group_id | channel_id)`), `search._scope_channels`, `sources.expand`/`get_video`, `chat`, and `mcp_server`.
- [x] `syncs.Sync` drops `mentor_name`; `SearchResult`, `Expansion`, `Citation` drop `mentor_name` and gain `channel_id`; stored citation JSON follows.

API, MCP, chat, CLI
- [x] `channels_api.py` replaces `mentors_api.py` (routes and 409s in spec §Domain); `groups_api` members take `channel_ids`; `chat_api`: `POST /channels/{id}/conversations`, `scope` on Conversation, summary, and detail, `GET /conversations` by either filter (both → 422); `search_api` takes `channels`.
- [x] `mcp_server.py`: `list_channels`; `search(channels=…)`; `expand`/`get_video` with `channel_id`; the bound server exposes `list_channels` always and `list_groups` for a Group scope only; `INSTRUCTIONS`, a Channel-scope `GROUP_INSTRUCTIONS` variant, `GROUNDED_ADVISOR`, every description, and the `sql` table list.
- [x] `chat.system_prompt(scope, names)`; `claude_chat`, `sync_worker` names only.
- [x] `sync_command` (`--channel` resolves against `GET /channels` or `channels.list_channels`), `status_command` (`mentor list`: Channels then Groups), `cli` output.

Tests
- [x] Rename `harness.py` (`woodworkers` builds Channels and a Group), `conftest.py`, and every test that mentions Mentor; `tests/test_smoke.py` wording updated so it stays green against the v1 UI with the renamed API.
- [x] New: migration 9 on a populated schema-8 database (built by running migrations 1–8 and inserting a Mentor with two Channels in a Group, plus a Conversation with messages) and on a fresh database; `POST /channels/{id}/conversations` and its 409s; Channel-scoped chat where `search`, `expand`, `get_video`, and saved Citations see only that Channel; `list_channels`; `scope` on all three shapes; `rename_channel` updating `scope_name`; `mentor sync --channel` by channel name.
- [x] `uv run pytest -q`, `uv run mypy`, `pnpm --dir web run typecheck` green (the last needs `api.ts` types adjusted to the new field names; no UI change beyond that).

Notes
- Split from a larger ticket on review: this is the backend half; ticket 02 renames the web UI and docs. Both leave `main` working.
- After fast-forwarding `main`, reinstall; migration 9 runs on the (empty) installed knowledge base.
