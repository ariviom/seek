# 02: Channels outside the Library

**What to build:** A behaviour-preserving prefactor. A Channel can exist outside the Library (Spec 0004 §Guarding Channels outside the Library), so later tickets can credit a Playlist's Videos to creators you haven't added. Today every Channel is in the Library, so nothing changes for the user, but every Channel path already refuses one that isn't.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] `channels` gains `in_library` (0/1, default 1), and every existing Channel is migrated as in the Library.
- [x] "Sync all" and the due-check query skip Channels outside the Library.
- [x] The per-Channel routes answer 404 for a Channel outside the Library: `GET /channels`, syncs, retry, `PATCH`, `DELETE`, videos, and conversations.
- [x] Setting Group members rejects a Channel outside the Library.
- [x] A new Conversation can't be scoped to a Channel outside the Library.
- [x] Search's chosen-channels scope reports a Channel outside the Library as not found.
- [x] MCP `list_channels` stays Library-only.
- [x] Tests seed an outside-the-Library Channel directly and assert each refusal through HTTP and MCP.

## Comments

**2026-10-10, implemented.**

What landed:
- Migration 20 adds `channels.in_library` (0/1, default 1, CHECK), so every existing Channel is in the Library.
- The Channel lookups require `in_library = 1`: `channels._get_channel`, `list_channels` and `delete_channel`; `syncs._require_channel` (start a Sync, retry failed, and `_enqueue`), `enqueue_all` and the `enqueue_due` query; `videos._require_channel` (`/videos`); `groups.set_members`; the answerable-scope check; and Search's chosen-channels check.
- `scope.VIDEO_IN_SCOPE` also requires `channels.in_library = 1`, which is the spec's "its Channel is in the Library and Active" half of searchable. Without it a Channel outside the Library would be searched under Everything and read by `expand` and `get_video`.
- Unscoped `groups.channel_summaries` (MCP `list_channels`) lists Library Channels only; a scoped listing is unchanged.
- `harness.take_out_of_library(config, channel)` writes `in_library = 0` directly, for tests until a Playlist can create such a Channel.

Verification: `uv run pytest -q` 596 passed (590 before, plus six), `uv run mypy` and `pnpm --dir web run typecheck` clean. No web change, so no build.

Behaviour: none for the user, since every Channel is in the Library. `test_checks`' seed gained an overdue Channel outside the Library with one finished Sync, so that test's "new Syncs" id cut-off moved from 6 to 7 and its per-Channel counts list that one seeded Sync.

For later tickets:
- `POST /videos/{id}/retry` answers 404 for a Video credited to a Channel outside the Library, because `_enqueue` requires a Library Channel. A Playlist's failed Video needs its own retry path in a later ticket.
- `_enqueue` and `syncs._select` are Channel-only; a Playlist Sync can't go through `_require_channel`.
- `channels.create_channel` still answers 409 "already added" for a YouTube channel that exists outside the Library, and `set_avatar` is unguarded on purpose (ticket 09 brings such a Channel into the Library).
- `GET /syncs` and `GET /conversations?channel_id=` don't look a Channel up, so they aren't guarded; ticket 09 nulls a Conversation's `channel_id` when its Channel leaves the Library.
- Ticket 05 widens `VIDEO_IN_SCOPE` with "or an Active Playlist includes it"; `storyboards.read_frames` / `missing` still test `channels.indexed` only, as ticket 01 noted, and `missing(conn, None)` (CLI backfill) doesn't look at `in_library`.
- The `sql` tool's table list doesn't describe `in_library` yet (spec §MCP; not in this ticket's criteria).
