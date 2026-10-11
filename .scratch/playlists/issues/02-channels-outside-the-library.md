# 02: Channels outside the Library

**What to build:** A behaviour-preserving prefactor. A Channel can exist outside the Library (Spec 0004 §Guarding Channels outside the Library), so later tickets can credit a Playlist's Videos to creators you haven't added. Today every Channel is in the Library, so nothing changes for the user, but every Channel path already refuses one that isn't.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `channels` gains `in_library` (0/1, default 1), and every existing Channel is migrated as in the Library.
- [ ] "Sync all" and the due-check query skip Channels outside the Library.
- [ ] The per-Channel routes answer 404 for a Channel outside the Library: `GET /channels`, syncs, retry, `PATCH`, `DELETE`, videos, and conversations.
- [ ] Setting Group members rejects a Channel outside the Library.
- [ ] A new Conversation can't be scoped to a Channel outside the Library.
- [ ] Search's chosen-channels scope reports a Channel outside the Library as not found.
- [ ] MCP `list_channels` stays Library-only.
- [ ] Tests seed an outside-the-Library Channel directly and assert each refusal through HTTP and MCP.
