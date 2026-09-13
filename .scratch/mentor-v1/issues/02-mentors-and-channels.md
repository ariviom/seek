# 02 — Mentors and Channels

**What to build:** From the web UI, paste a YouTube channel URL or handle and see the channel resolved with its display name proposed as the Mentor name, then confirm to create the Mentor. Rename a Mentor, attach more Channels to it, mark a Channel not indexed, detach a Channel, delete a Mentor. (Stories 1–4.)

**Blocked by:** 01 — Walking skeleton

**Status:** done

- [x] Two-step create: a resolve call returns the proposal (channel id, display name); a create call persists the Mentor with its first Channel
- [x] Attach, detach, toggle indexed, rename, delete work through the API and the UI
- [x] YouTube channel id is unique; attaching a Channel already owned by another Mentor is rejected with a clear error
- [x] Unresolvable URL or handle returns a clear validation error
- [x] API tests with FakeTranscriptSource cover each story, setting state only through the public API

From ticket 01 review: `create_app` has no ports parameter yet; add it (required) with the first consumer and inject fakes via the harness.

Done note: `create_app` takes each port as its own argument (`transcripts` today) rather than a Ports bundle, because `serve` has no real embedder, reranker, or chat engine yet. `mentor serve` wires a placeholder YouTube source that answers 503 until ticket 08, so Mentors can only be added via tests or a fake-backed server until then.
