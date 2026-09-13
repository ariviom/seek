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
