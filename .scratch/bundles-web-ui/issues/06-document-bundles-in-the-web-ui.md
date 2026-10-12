# 06: Document Bundles in the web UI

**What to build:** Someone reading the README learns that a Channel or Playlist is shared from the web UI first, and from the command line second, and what to do when a proxy refuses a large Bundle. The next agent reading HANDOFF finds the routes and the temporary directory in the conventions. ADR 0007 says that import now also runs inside the server. See Spec 0006 §Docs.

**Blocked by:** 02 (Export a Playlist from its page), 05 (Limits and leftovers).

**Status:** ready-for-agent

- [ ] The README's "Sharing a Channel or Playlist" leads with the web UI: Export on the entry's page, and import in the Add Channel and Add Playlist dialogs, either kind in either. The two commands stay, after it.
- [ ] It says a large Bundle may be refused by a proxy in front of Seek, and that such a file imports at `localhost` on the machine Seek runs on, or with `seek import`. It gives the 2 GB cap of the web UI. It does not state a proxy's limit as fact: Cloudflare's 100 MB is unverified.
- [ ] "Publishing through a reverse proxy" gets a line on the same.
- [ ] Wherever the README says a Channel or Playlist arrives only by the web UI's Add or by `seek import`, it now reads true.
- [ ] HANDOFF gets a dated update entry for Spec 0006, and its conventions name the Bundle routes, the temporary directory and when it is cleared, the one-import-at-a-time hold, and the two changes to the import function.
- [ ] ADR 0007 gains a dated note, not a successor: import also runs inside the server, on an uploaded file, in a worker thread, under the same lease, so the second writer is either the CLI's process or a thread of the server's. The untrusted file now also arrives over HTTP, and the note records the content-type requirement, the cap, and that it is never held in memory.
- [ ] CONTEXT.md is unchanged, and nothing written here uses "export" as a noun, "pack", or "archive" for a Bundle.
- [ ] Each sentence about behaviour is checked against the code as it landed, not against the spec, and anything of the spec the code no longer matches is brought in line and named in this ticket's comments.
