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
