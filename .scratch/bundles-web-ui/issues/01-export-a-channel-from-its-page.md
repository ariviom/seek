# 01: Export a Channel from its page

**What to build:** On a Channel's page I press Export, confirm in a dialog that tells me what I'm about to share, and my browser downloads the Channel's Bundle as `<name>.seek`, on whichever device I'm using. Nothing of it stays on the server. This is the tracer bullet: it brings in the build and download routes and the temporary directory that the later tickets reuse. See Spec 0006 §Routes, §Export, §Temporary files, §Web UI: Export, §Security.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The Channel page has an Export button with the actions that concern the entry as a whole (Rename, Pause, Remove), and none in the Library's rows.
- [ ] Export is disabled when the Channel has no indexed Videos, with the tooltip "No indexed Videos to export yet." The tooltip shows although the control is disabled.
- [ ] Pressing Export opens a dialog titled "Export <name>" with the count of indexed Videos, the line that the file contains the creators' full Transcripts, and, for a Channel with a Playlist filter, the line that the filter is left out. It has Cancel and one Export button, not styled as destructive.
- [ ] Export becomes "Building…" and is disabled until the build answers. The download then starts through a link carrying the `download` attribute, as a relative URL, and the dialog closes. An error from the link is a failed download, never a navigation away from the app.
- [ ] A refusal shows in the dialog as an alert and leaves it open. The build keeps its own busy and error state, apart from the page's shared runner of changes.
- [ ] Building a Channel's Bundle is one request that answers with the report (name, Videos, Segments, size, whether a Playlist filter was left out) and the id the built Bundle is collected under. It calls the existing export function in a worker thread; there is no second implementation.
- [ ] The Channel is found by the id in the URL; one outside the Library, or an id that isn't there, is not found. The export function is given the Channel's YouTube id, so a Channel that shares its name with another exports.
- [ ] A Paused Channel exports, and so does one whose Sync is running.
- [ ] The user-facing refusal the Bundle functions raise maps to a status with its sentence as `detail`. An entry with no indexed Videos is refused with the command's sentence, counted again by the server when it builds.
- [ ] Collecting a built Bundle sends it as `application/octet-stream` with its length and as an attachment. It is served once: the file is deleted when the response ends, whether or not it was sent whole, and a second request is not found.
- [ ] The id is long and from the operating system's random source.
- [ ] The file name is the Channel's name sanitised as the spec lays out (separators, the characters Windows forbids, and control characters replaced; dots and spaces trimmed; cut to 100 characters; `bundle` when nothing is left) plus `.seek`. The header is built by hand and carries it in the UTF-8 form and as an ASCII fallback.
- [ ] Bundles being built live in one directory inside the data directory, readable by the user alone, each in a fresh, unguessably named directory that is removed whole after the download's response ends and when a build fails.
- [ ] HTTP tests cover: a build and its download (the report's counts, the headers), names that need sanitising (a slash, a quote, an emoji, nothing but dots), served once, a Paused Channel, a Channel mid-Sync held by a `Gate`, a Channel sharing its name, a Playlist filter reported as left out, no indexed Videos, an id that isn't there, and the temporary directory empty after each.
- [ ] A browser test covers the dialog's count and Transcripts line, "Building…", a download whose suggested name is `<name>.seek`, and Export disabled with its tooltip on a Channel with nothing indexed.
