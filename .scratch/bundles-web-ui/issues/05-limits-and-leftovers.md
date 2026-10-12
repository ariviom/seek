# 05: Limits and leftovers

**What to build:** The edges of export and import behave. A file larger than Seek accepts is refused before I send it. A file the proxy in front of Seek refuses fails with a sentence telling me to import at `localhost` or with `seek import`. An upload I walk away from is discarded, and one that has fully arrived finishes without me. A Bundle I built and never collected is deleted, and whatever a crash left in the temporary directory is cleared at the next start. Through the published host, all of it sits behind Cloudflare Access like everything else. See Spec 0006 §Import (the cap, abandoned uploads), §Export (the expiry), §Temporary files, §Web UI: Import (the fallback sentence), §Security, and §Testing Decisions.

**Blocked by:** 04 (Import waits for Syncs and for another import).

**Status:** ready-for-agent

- [ ] An upload is capped at 2 GB, a constant the app factory takes as a parameter, as it takes its other test-tunable values.
- [ ] A declared length over the cap is refused at once, without reading the body, ahead of the checks ticket 04 added. A body that passes the cap undeclared is refused and what was written is deleted. Both say: "The file is larger than 2 GB, the most the web UI imports; import it with `seek import`."
- [ ] The dialog refuses a file over the cap when it is chosen, with the same sentence, before anything is sent. The page holds the same number; the server's is the one that counts.
- [ ] An import failure that carries no sentence of Seek's (the response isn't Seek's JSON, or the request fails outright) shows: "The file didn't reach Seek. A proxy in front of it may refuse a file this large; import it at `localhost` on the machine Seek runs on, or with `seek import`." The page does not guess a proxy's limit in advance.
- [ ] An upload the browser abandons is discarded: its directory is removed and the hold of the one import is given up.
- [ ] Once the whole file has arrived, the import runs to its end whether or not the browser is still there, and its entry appears on open pages.
- [ ] A built Bundle nobody collects is deleted ten minutes after it was built, with the expiry taken by the app factory as a parameter.
- [ ] At start, before it serves, the server removes whatever in the temporary directory has not been modified in the last hour, and leaves what is fresher, so a second server started by mistake on the same data directory can't delete the first one's upload in flight.
- [ ] Through a published host with Access configured, the build, download, and import routes need a token like any other route, and work under a forwarded prefix with one.
- [ ] HTTP tests cover: a body over a small cap, both declared and undeclared, with the Library unchanged and the temporary directory empty; a built Bundle gone after a shortened expiry; and, of two leftovers planted before the app starts, the one last modified over an hour ago gone and the fresh one kept.
- [ ] Two tests on a really served app, with a client that drops its connection, cover an upload abandoned partway (nothing stored, a later import accepted) and an import whose file had arrived (it completes and the entry is listed).
- [ ] Tests in the remote-access tests' pattern cover the three routes without a token and with one under a forwarded prefix.
- [ ] A browser test, with the upload route answered as a proxy would (a 413 with an HTML body), covers the "didn't reach Seek" sentence.
