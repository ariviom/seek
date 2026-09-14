# 13 — Conversation management

**What to build:** Conversations are listed per Group, reopenable, and resumable, with a model picker per Conversation. They survive Mentor and Group removal. The UI clearly says when the Claude CLI is missing or not logged in. (Stories 8, 42–44.)

**Blocked by:** 12 — Web chat

**Status:** ready-for-agent

- [ ] List per Group, get with messages, resume via the stored Claude session id
- [ ] If the session can't be resumed (expired, cleaned up), the Conversation continues by replaying its history from the database
- [ ] Model picker per Conversation, defaulting to the CLI default
- [ ] Conversations and their citations still render after their Mentor or Group is deleted; a Conversation whose Group is gone is read-only
- [ ] Health reports the Claude CLI as present and authenticated using a named probe; the CLI path is configurable; the UI shows an actionable message when either check fails
- [ ] API tests cover each story

From ticket 03 review: deleting a Group hard-deletes its row and memberships, and its name is free for reuse. Group ids are AUTOINCREMENT and never reused. For read-only Conversations after Group deletion, give `conversations.group_id` `ON DELETE SET NULL` and copy the Group name onto the Conversation (decide when ticket 12 creates the table, since migrations are additive). The Group delete confirmation in `web/src/Groups.tsx` says "Its Mentors are kept" and should also mention Conversations.

From ticket 12 review:
- The ChatEngine port still can't say a session couldn't be resumed: `ChatFailed` has only a message and `ChatRequest` has no replay history. A stale `claude_session_id` makes the adapter fail every turn with "Claude Code failed: ..."; reshape the port for replay here.
- A failed turn saves the question but no answer and no session id, so a failed first turn leaves the next turn starting a fresh session without it, and the table holds consecutive user messages. Replay must handle both; consider saving failed answers with their error.
- `error_max_turns` (MAX_TURNS 30 in `claude_chat.py`) discards the partial answer.
- The chat uses the `claude` on PATH (`cli.py`), else fails with a "not found" message; make the path configurable and share it with the Health probe. The CLI inherits the server's environment, so an `ANTHROPIC_API_KEY` set there would bill the API rather than the subscription; check it in the probe.
- `conversations.group_name` is kept current by `groups.rename_group`, so a deleted Group's Conversations show its last name.
- No Conversation delete exists; if one is added, `conversations.record_answer` for a turn still running would hit the foreign key.
- The web chat creates its Conversation with the CLI default model (`api.createConversation(groupId, null)`); the picker belongs here. Switching the chat to another Group mid-answer unmounts it (the turn still finishes and saves server-side).
