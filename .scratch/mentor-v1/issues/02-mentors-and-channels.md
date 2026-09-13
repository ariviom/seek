# 02 — Mentors and Channels

**What to build:** From the web UI, paste a YouTube channel URL or handle and see the channel resolved with its display name proposed as the Mentor name, then confirm to create the Mentor. Rename a Mentor, attach more Channels to it, mark a Channel not indexed, detach a Channel, delete a Mentor. (Stories 1–4.)

**Blocked by:** 01 — Walking skeleton

**Status:** ready-for-agent

- [ ] Two-step create: a resolve call returns the proposal (channel id, display name); a create call persists the Mentor with its first Channel
- [ ] Attach, detach, toggle indexed, rename, delete work through the API and the UI
- [ ] YouTube channel id is unique; attaching a Channel already owned by another Mentor is rejected with a clear error
- [ ] Unresolvable URL or handle returns a clear validation error
- [ ] API tests with FakeTranscriptSource cover each story, setting state only through the public API

From ticket 01 review: `create_app` has no ports parameter yet; add it (required) with the first consumer and inject fakes via the harness.
