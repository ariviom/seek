# 03: Import a Channel Bundle into a Library that already has some of it

**What to build:** Importing a Channel I already have, or whose Videos I partly have, never overwrites my own work and never replaces my settings. Videos I've finished indexing stay exactly as they are; ones I have but haven't finished are completed from the Bundle; my own rules decide what is left out. A second import of a newer Bundle is a cheap top-up, and import tells me what happened to every Video. See Spec 0005 §Import ("The entry", "Each Video", the report).

**Blocked by:** 01 (Share a Channel with someone who doesn't have it).

**Status:** ready-for-agent

- [ ] A Channel already in the Library keeps its name, filters, Pause state, check schedule, and avatar.
- [ ] A Channel known only outside the Library is brought into it under the Bundle's name, keeping its Videos, with the Bundle's date range and most-recent count applied after it is brought in.
- [ ] `--name NAME` names the entry when import creates it. When the entry already exists, import says it kept the existing name. An imported Channel may share a name with another, as one added in the web UI may.
- [ ] A Video already `done` is left untouched.
- [ ] A Video that is known but unfinished (discovered, mid-pipeline, or failed, including permanently) takes its details, Transcript, Segments, and vectors from the Bundle, has its failure cleared, and becomes `done`.
- [ ] A Video not yet known is judged by the recipient's minimum length and by the date range in force on the Channel after the entry step. One they exclude is not added.
- [ ] A Video already known is not judged again: one that is excluded stays excluded and untouched, including one excluded by a most-recent count or a Playlist filter.
- [ ] A known, unfinished Video that one of the recipient's Playlists includes is completed from the Bundle whatever the Channel's filters say.
- [ ] A Video credited here to a different Channel than the Bundle says keeps its credit, is left untouched, and is reported.
- [ ] Import prints any filters that arrived with a new Channel and one count per outcome, every Video in the Bundle falling in exactly one: added (became `done` from the Bundle, new or completed), already indexed, and left out, with a count per reason.
- [ ] Importing the same Bundle twice changes nothing the second time. Importing a larger Bundle of the same Channel adds only the new Videos.
- [ ] Tests cover each rule above through the import function and the app's surfaces, including a Bundle that produces all three counts.
