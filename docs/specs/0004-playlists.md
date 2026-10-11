# Spec 0004 — Playlists

Status: ready-for-agent
New glossary terms: Library, Playlist, Playlist filter (CONTEXT.md). New decision: ADR 0006 (a Playlist is its own
scope over Videos; Videos stay credited to their Channels), which supersedes the playlist half of
`docs/product/desktop-mvp.md` §3. Shaped by a grilling session on 2026-10-10.

## Problem Statement

The Library only knows Channels. When I've curated a YouTube playlist from many creators (the best ten videos on
sharpening, say), I can't consult it as a unit. To get those videos into Seek I'd have to add every creator as a
Channel, which pulls in hundreds of unrelated uploads, clutters the Library, and still leaves me without a scope that
means "just these videos". The Channel's existing playlist filter doesn't help: it only keeps that Channel's own
uploads.

## Solution

A **Playlist** is a new kind of Library entry, added by pasting a YouTube playlist URL. Public and unlisted playlists work as they are; a private one works when
Seek is signed in to the owner's YouTube account through its existing cookie settings. Seek syncs
the playlist's Videos, whoever uploaded them, and keeps them in step with YouTube on the same check schedule as
Channels. A Playlist is a scope of its own: I can search it, chat with it, and point my own agent at it over MCP.
Every Video is still credited to the creator who made it, with their name and avatar, but creators I haven't added
stay out of the Library and out of every picker. A Video I've put in a Playlist is searchable even if a Channel's
filters would leave it out, and it's deleted once nothing in the Library includes it any more.

## User Stories

### Adding and managing a Playlist
1. As a learner, I want to add a Playlist by pasting its YouTube URL, so that I can consult a curated set of videos from many creators.
2. As a learner, I want the URL as copied from the address bar or a share link to work, so that I don't have to dig out the playlist id.
3. As a learner, I want to see the playlist's title and how many videos it holds before I confirm, so that I know I pasted the right one.
4. As a learner, I want the Playlist named after its YouTube title by default and renameable, so that it reads the way I think of it.
5. As a learner, I want a clear message when the URL isn't a playlist, or the playlist doesn't exist or is private, telling me how to give Seek access, so that I know how to fix it.
6. As a learner, I want my private playlists to work once Seek has my YouTube cookies, so that I don't have to make my curation unlisted.
7. As a learner, I want the Add dialog to answer promptly even while a Sync is running, so that adding a Playlist never waits on ingestion.
8. As a learner, I want adding the same playlist twice, or giving two Playlists the same name, to be refused with a message, so that I don't get duplicates and names stay unambiguous.
9. As a learner, I want Playlists in the Library beside Channels and Groups, so that everything I consult is in one place.
10. As a learner, I want a Playlist's page to list its Videos in playlist order with each creator's avatar and name, so that I can see whose work it holds.
11. As a learner, I want each Video's pipeline status and any exclusion reason on the Playlist page, so that I know what's searchable and why not.
12. As a learner, I want to start a Playlist's first Sync myself, as with a Channel, so that adding one never starts a long download unasked.
13. As a learner, I want to sync a Playlist on demand and retry failed Videos, so that I can recover from a bad run.
14. As a learner, I want a Playlist checked for changes every 6 hours, daily, weekly, or never, daily by default, so that it follows the playlist on YouTube without my attention.
15. As a learner, I want the Playlist page to say when the next check is due, so that I know how current it is.
16. As a learner, I want Videos added to the playlist on YouTube to be added to the Playlist at the next check, so that my curation in YouTube is the source of truth.
17. As a learner, I want Videos removed from the playlist on YouTube to be removed from the Playlist at the next check, but never because a listing came back short or failed, so that a YouTube hiccup can't delete what I've indexed.
18. As a learner, I want to pause a Playlist, so that it drops out of search, chats, and checks without losing what's indexed.
19. As a learner, I want to delete a Playlist, so that I can drop curation I no longer want.
20. As a learner, I want "Sync all" and the Syncs list to include Playlists, so that I can see and run all ingestion in one place.
21. As a learner, I want a Playlist's Syncs to show live progress, stage counts, and errors like a Channel's, so that nothing about ingestion is special-cased.

### Credit and creators
22. As a learner, I want every Video in a Playlist credited to the creator who made it, so that citations name the person speaking.
23. As a learner, I want creators I haven't added to show their avatar, falling back to initials, so that results look the same wherever they came from.
24. As a learner, I want creators I haven't added kept out of the Library list, so that a Playlist doesn't clutter it.
25. As a learner, I want creators I haven't added kept out of Search's channel picker, the new-chat scope menu, and the Conversations filter, so that I only pick from what I chose to add.
26. As a learner, I want a Video that's both in a Channel I added and in a Playlist to be stored and indexed once, so that sync time and disk aren't wasted.
27. As a learner, I want adding a creator through the usual Add Channel flow to bring them into the Library while keeping their already-indexed Videos, so that nothing is fetched twice.
28. As a learner, I want that newly added Channel's filters to govern the rest of its uploads, while its Videos in my Playlists stay searchable, so that the two kinds of choice don't fight.

### What's searchable
29. As a learner, I want a Video I put in a Playlist to be searchable even if a Channel I added would exclude it by date, playlist filter, or most-recent count, so that my explicit curation wins.
30. As a learner, I want very short Videos (under the minimum length) still skipped in a Playlist, so that transcripts with nothing in them don't dilute results.
31. As a learner, I want pausing a Channel to leave its Videos searchable through an Active Playlist that includes them, so that a pause only affects what I paused.
32. As a learner, I want pausing a Playlist to leave its creators' Library Channels searchable, so that the reverse holds too.
33. As a learner, I want "Everything" in Search to include Playlist Videos, so that a wide search covers everything I've curated.

### Removal
34. As a learner, I want a Video deleted once no Library Channel or Playlist includes it, so that the database holds only what I chose.
35. As a learner, I want deleting a Playlist to keep its Videos that a Library Channel or another Playlist still includes, so that deleting one thing never breaks another.
36. As a learner, I want deleting a Channel whose Videos a Playlist includes to keep those Videos, credited as before, so that my Playlist stays whole.
37. As a learner, I want a creator who no longer has any Video in the Library forgotten entirely, so that nothing invisible lingers.
38. As a learner, I want a deleted Playlist's Conversations to stay readable but not continuable, so that past answers aren't lost.
39. As a learner, I want a deleted Channel's Conversations to stay read-only even if I add that creator again, so that a new Channel doesn't quietly inherit old threads.

### Searching
40. As a learner, I want each Playlist as a Search scope chip beside the Groups, so that I can search just my curated videos.
41. As a learner, I want the results header to name the Playlist I searched, so that I know the scope at a glance.
42. As a learner, I want "Ask about this" on a result from a Playlist search to open a chat in that Playlist, so that the follow-up keeps the same scope.
43. As a learner, I want "Ask about this" on a result whose creator isn't in the Library, or is Paused, to open a chat in an Active Playlist that includes it, so that the button always works.

### Chatting
44. As a learner, I want to start a chat scoped to a Playlist, so that answers draw only on my curated videos.
45. As a learner, I want a Playlist's chats in their own folder in the Chats list and filterable by that Playlist, so that I can find them later.
46. As a learner, I want the chat told it's consulting a Playlist and which creators it holds, so that it frames answers correctly.
47. As a learner, I want a Playlist chat's Sources and Citations restricted to that Playlist's Videos, so that its footing is exactly what I curated.
48. As a learner, I want starting a chat in a paused or empty Playlist refused with a message, so that I don't ask into nothing.
49. As a learner, I want renaming a Playlist to rename it on its chats, so that the folder and chips stay current.

### From my own agent (MCP)
50. As an agent user, I want a `list_playlists` tool listing each Playlist with its creators and searchable Video count, so that my agent can choose a scope.
51. As an agent user, I want `search` to accept a Playlist by id or name, so that my agent can search a curated set.
52. As an agent user, I want a Playlist-scoped chat's tools bound to that Playlist, so that the model can't search outside it.
53. As an agent user, I want the `sql` tool's table list to describe Playlists, so that ad-hoc queries can use them.

### Upgrading
54. As a learner, I want the CLI's status and the doctor report to show Playlist Syncs, including failed ones, so that nothing ingests out of sight.
55. As a CLI user, I want to sync, reindex, and backfill frames for a Playlist by name or YouTube id, and have `--all` include Playlists, so that the CLI covers everything the web does for ingestion.
56. As a CLI user, I want `seek list` to show my Playlists, so that I can see the whole Library from the terminal.
57. As an existing user, I want my Channels, Groups, Videos, embeddings, and Conversations carried through the upgrade untouched, so that nothing is re-synced or re-embedded.

## Implementation Decisions

### Schema (one migration, callable rebuilds where a CHECK or NOT NULL changes)
- `channels` gains `in_library` (0/1, default 1). Every existing row is in the Library. A Channel outside the Library
  is created with no filters and `check_every_hours` NULL, is never synced or checked on its own, and is never a
  scope (see "Guarding Channels outside the Library").
- New `playlists`: AUTOINCREMENT id, `youtube_playlist_id` unique, `name` unique and case-insensitive (as Groups),
  `indexed` (Active/Paused), `check_every_hours` with the same allowed values and default as Channels (NULL means no
  checks).
- New `playlist_videos(playlist_id, video_id, position)`, primary key on the pair, WITHOUT ROWID, cascading from both
  sides, indexed on `video_id`.
- `syncs` is rebuilt so a Sync belongs to exactly one Channel or one Playlist: `channel_id` becomes nullable, a
  `playlist_id` is added (cascade), and a CHECK requires exactly one to be set. A partial unique index enforces one
  queued Sync per Playlist, mirroring the one per Channel. The rebuild recreates every existing `syncs` index.
- `conversations` is rebuilt: `scope_kind` admits `playlist`, and a `playlist_id` is added (`ON DELETE SET NULL`).
  The rebuild carries every current column (workspace, web access, title, Claude session).
- The `segment_vectors` vec0 table is rebuilt with a `video_id` metadata column in place of `channel_id`, copying the
  existing embeddings, so no Video is re-embedded. SQLite validates triggers on `RENAME`, and the embedding-model
  check returns early when the model is unchanged, so the migration must not create-then-rename. Verified order
  against sqlite-vec 0.1.9, inside the migration's transaction and only when the table exists:
  1. Copy `(segment_id, segments.video_id, embedding)` into a temporary table.
  2. Drop the `segment_vectors_delete` trigger, then drop `segment_vectors`.
  3. Create `segment_vectors` under its final name, with the dimension from `embedding_model`.
  4. Insert from the temporary table, then recreate the trigger.

  Don't rely on `legacy_alter_table`. The table's creation path uses the new shape for fresh databases.

### Sources port
- `list_playlist` returns the playlist's title and its entries in order. Each entry has the video id, title,
  duration, and the creator's YouTube channel id and name. Entries without a creator id (private or deleted videos,
  some renderers) are skipped. The Channel playlist filter keeps using only the ids.
- The yt-dlp adapter reads these fields from the flat playlist extraction; yt-dlp 2026.08.19 carries `channel_id`,
  `channel`, and `duration` on flat entries.
- A new `resolve_playlist` port method returns the id, title, and count of entries with a creator. It runs unpaced,
  as `resolve_channel` does, so the Add dialog never waits behind a Sync. It accepts a `list=` parameter from a
  watch, share, or playlist URL, as the playlist filter already does.
- **Private playlists:** these use the existing YouTube cookie settings (`youtube_cookie_file` or
  `youtube_cookies_from_browser`), which every yt-dlp call already sends, including `resolve_playlist` and
  `list_playlist`. A private playlist works when the cookies belong to its owner's account; no new auth mechanism is
  added.
- yt-dlp can't tell a private playlist it isn't allowed to see from a missing one, so both give one error: "This
  playlist doesn't exist or is private. For your own private playlist, configure `youtube_cookie_file` or
  `youtube_cookies_from_browser` signed in as you, or set it to unlisted." The real-yt-dlp check also confirms that a
  private playlist lists with the owner's cookies.
- `FakeTranscriptSource` playlists become entries of `(youtube channel id, video id)`, resolved against its
  `channels`, so `fetch_video` and `resolve_channel` stay the one source of truth. The fake can also stand in for a
  missing or private playlist. The existing playlist-filter test fixture is updated to the new shape.

### Playlist Sync
- A Playlist Sync lists the playlist, then:
  - It creates any creator Channel it doesn't know, outside the Library, with the entry's name and an avatar from
    resolving the channel. Avatar lookups go through the Sync pacing, so a playlist with many new creators doesn't
    burst requests. A failed avatar lookup leaves it on initials.
  - It records any Video it doesn't know, credited to that Channel.
  - It adds new memberships and updates positions.
  - It removes memberships only when the listing completed without error. A listing that comes back empty for a
    Playlist that has Videos fails the Sync with a message and removes nothing. Videos whose last membership was
    removed go through the keep rule below.
  - It advances every unfinished Video in the Playlist through the existing pipeline.
- A Video shared with a Library Channel is one row. Whichever Sync reaches it first advances it, and Syncs still run
  one at a time.
- Queueing, leasing, claiming, events, retries, and stage counts are generalised from "a Channel" to "a Sync's
  source" (Channel or Playlist). The Sync shape keeps `channel_id` (now nullable) and adds `playlist_id` and
  `source_name`, to limit churn for consumers. The throttle message names the source.
- Lease recovery's "a newer one is queued" test matches on both columns,
  `(channel_id, playlist_id) IN (SELECT channel_id, playlist_id FROM syncs WHERE status = 'queued')`. Otherwise a
  crash during a Playlist Sync with a second one queued would requeue it into the unique index and stall every Sync.
- Retry-failed and reindex on a Playlist act on its Videos, including those shared with Library Channels. A shared
  Video may be re-embedded once per Sync that reindexes it, which is acceptable.
- **Consumers of the Sync shape:**
  - The CLI's sync listing and status, and the doctor's failed-Sync report (which joins Channels today), show
    Playlist Syncs by `source_name`.
  - The web sync status helpers follow the new fields.

### CLI
Playlists get the same CLI support as Channels. Like Channels, they are added in the web UI; the CLI has no add or
remove for either.
- `seek sync`, `seek reindex`, and `seek backfill-storyboards` gain `--playlist NAME_OR_ID`, accepting the Playlist's
  name or its YouTube playlist id. It is mutually exclusive with `--all` and `--channel`.
- `--all` covers Active Playlists as well as Active Channels; for `backfill-storyboards`, every Playlist.
- When the server is running, the request goes through it. Otherwise it runs in-process, as `--channel` does.
- `seek list` lists Playlists after Groups, with their Video counts, creators, and last Sync.
- `seek status` and `seek doctor` show Playlist Syncs.
- The README's CLI and cookie sections mention Playlists and private playlists.
- Checks: `enqueue_due` also selects Active Playlists, under the same `is_due` rule. A never-synced Playlist is not
  due, so the first Sync is the user's, as with Channels.

### Exclusion: inclusion wins
- Judging a Video's exclusion takes into account whether any Playlist includes it. The minimum-duration rule always
  applies. A Channel's date window, playlist filter, and most-recent count apply only when no Playlist includes the
  Video.
- Playlist-included Videos don't take a slot in a Channel's most-recent count. The Channel keeps its N newest own
  Videos, plus any Playlist-included ones.
- Two kinds of re-judging:
  - **Within a Sync, as today:** a Channel Sync re-judges its Channel's Videos with full information, counting
    Playlist memberships. A Playlist Sync judges the Videos it records or advances.
  - **Inline, from stored data:** run when a Video loses its last Playlist, whether by a Playlist Sync's removal,
    Playlist deletion, or anything else. If its Channel is in the Library, it is judged against the minimum length
    and the Channel's stored date window. The playlist-filter and most-recent rules, which need a listing, catch up
    at the Channel's next Sync. If its Channel isn't in the Library, the keep rule deletes it.
- Changing a Channel's filters still takes effect at its next Sync, as today.
- A Video newly excluded by re-judging loses its Segments, as today.

### The keep rule
- A Video is kept while its Channel is in the Library or any Playlist includes it. Otherwise it is deleted, with its
  Transcript, Segments, vectors, and storyboard.
- A Channel outside the Library that no longer credits any Video is deleted.
- **Deleting a Playlist** reads its Video ids first, because the memberships cascade, then deletes it and applies
  the keep rule (and inline re-judging) to those Videos.
- **Deleting a Library Channel** deletes it as today when no Playlist includes any of its Videos. Otherwise it is
  taken out of the Library:
  - `in_library` is set to 0 and its filters are cleared.
  - Its Group memberships and Syncs are removed.
  - Its Conversations get their `channel_id` set to NULL, so they stay read-only even if the creator is added again.
  - The keep rule is applied to its Videos. Ids are captured before any delete, and creators left with no Videos
    are forgotten last.
- **Adding a Channel** that already exists outside the Library brings it into the Library: `in_library` is set to 1,
  the given name and default filters apply, and `check_every_hours` is reset to the default. It is not a conflict.
  Its first Sync is the user's, as for any new Channel; that Sync discovers its other uploads and judges them by its
  filters.

### Guarding Channels outside the Library
Every Channel path requires `in_library = 1`:
- "Sync all" and the due-check query.
- The Channel lookup behind `POST /channels/{id}/syncs`, retry, `PATCH`, `DELETE`, `/videos`, and
  `/conversations`, which answer 404 for a Channel outside the Library.
- Group membership changes.
- The answerable-scope check for new Conversations.

### Scope resolves to Videos
- `ScopeKind` gains `playlist`. One predicate decides which Videos a scope covers. It replaces the Channel-level
  predicate in search, `expand`, `get_video`, Citations, and the per-scope Channel summaries:
  - A Video is **searchable** when it is done and not excluded, and either its Channel is in the Library and Active,
    or an Active Playlist includes it.
  - **Everything** covers every searchable Video.
  - A **Channel** scope covers that Library Channel's own Videos while it is Active.
  - A **Group** scope covers the Videos of its Active Channels.
  - A **Playlist** scope covers its Videos while the Playlist is Active, whether or not their creators are in the
    Library or Active.
  - **Chosen channels** accepts Library Channels only. An id outside the Library is reported as not found.
- Search resolves the scope to Video ids and filters the vector KNN and FTS with
  `video_id IN (SELECT value FROM json_each(?))`, binding one JSON array as Group membership changes do.
  sqlite-vec 0.1.9 pushes this into the KNN (verified), so a small scope still gets its k nearest.
- A Paused Playlist named in a search returns no results silently, as a Paused Channel in `channels` does today.
- The search request gains `playlist` (an id or a name, as `group` is). At most one of `group`, `channels`, or
  `playlist` may be given.
- Per-scope Channel summaries take their counts from the Video predicate, not from `channels.indexed`. For a
  Playlist, they list its creators, each counting their Videos that are both in the Playlist and searchable, so a
  Paused creator still shows its Playlist Videos.

### Conversations and chat
- `POST /playlists/{id}/conversations` creates a Playlist-scoped Conversation. A Paused or empty Playlist answers 409
  with a message. `GET /conversations?playlist_id=` filters by Playlist. Renaming a Playlist updates `scope_name`.
- A Conversation is read-only when its scope's id column is NULL. This covers deleted Playlists and Channels taken
  out of the Library, both of which were nulled above.
- The system prompt names a Playlist scope as "the Playlist 'X' (Channels: …)".
- The bound MCP server gains a `playlist` entry with its own instructions and the tools `list_channels` (the
  Playlist's creators), `search`, `expand`, and `get_video`. The scope noun, the bound-tool names, and the
  "consulted" wording in the resource-advisor branch all cover `playlist`. Neither chat engine branches on scope
  kind, so nothing else changes there.

### MCP (unscoped)
- The new `list_playlists` tool returns each Active Playlist with its id, name, creators, and searchable Video count.
- `search` takes `playlist`.
- `list_channels` stays Library-only.
- The `sql` tool's table list describes `playlists`, `playlist_videos`, and `channels.in_library`.

### Web API
- `POST /playlists/resolve {playlist}` returns `{youtube_playlist_id, title, video_count}`, shaped like the Channel
  proposal; the count is of entries with a creator.
- `POST /playlists {playlist, name?}` returns 409 if the playlist is already added or the name is taken. A rename
  to a taken name also returns 409.
- `GET /playlists` returns each Playlist with its counts, `indexed`, `check_every_hours`, next check, and creators
  (`{id, name, avatar_url}`).
- `PATCH /playlists/{id}` takes `name`, `indexed`, and `check_every_hours`. `DELETE /playlists/{id}`.
- `GET /playlists/{id}/videos` lists Videos in playlist order with creator, status, and exclusion reason.
- `POST /playlists/{id}/syncs` and retry mirror the Channel routes.
- `GET /channels` stays Library-only.
- Every video and videos event carries the Video's `channel_id` and the ids of all Playlists that include it,
  whichever Sync caused it, so open Channel and Playlist pages both reload.

### Web UI
- **Library:** a third tab, Playlists, with a list, an Add Playlist dialog (resolve, preview, confirm), and a Playlist
  page. The page has rename, Pause, the check interval with next check, Sync and retry, delete, and a Videos table
  with a creator column.
- **URL state:** gains `playlist` and the `playlists` tab.
- **Avatars:** the channel-avatar map also takes creators from `GET /playlists`, so creators outside the Library get
  avatars in results, citations, and Playlist pages.
- **Search:** a chip for each Playlist after the Groups. The results header names the Playlist.
- **"Ask about this":** after a Playlist search, the chat opens in the searched Playlist. Otherwise it opens in the
  result's Channel when that Channel is in the Library and Active, else in the first Active Playlist (by name) that
  includes the Video. For that, search results carry the ids of the Active Playlists that include them.
- **Chats:** a folder per Playlist, Playlists in the new-chat scope menu, and a `playlist` kind in the scope chip,
  the Conversations filter, and the scope wording in the conversation header and the folder labels (both hardcode
  Group/Channel today).
- **Syncs:** the list and detail page name a Sync's source, whether Channel or Playlist.

### Docs
- README, HANDOFF, and the MCP instructions mention Playlists. The glossary and ADR 0006 are already written.

## Testing Decisions

- Tests exercise external behaviour through the app's own surfaces: HTTP, MCP, and the served UI. They assert what a
  user or agent sees (rows listed, results returned, status codes, messages), not table contents, except where
  deletion itself is the behaviour.
- **App with fakes over HTTP and MCP** (the `create_app` harness with the fake source, embedder, reranker, and chat
  engine, the harness helpers, and `mcp_client`). This is where nearly all behaviour is tested:
  - Add, resolve, the duplicate, private, and unknown errors, rename, Pause, and delete.
  - A Playlist Sync crediting Videos to creators, reusing a Video shared with a Library Channel, and following
    additions and removals on a re-sync.
  - Inclusion wins over a Library Channel's date filter and most-recent count, while the minimum duration still
    excludes. Inline re-judging puts a Video back under its Channel's date window when its last Playlist goes.
  - A failed or empty listing removes nothing.
  - Lease recovery with a Playlist Sync running and another queued.
  - Every Channel path refusing a Channel outside the Library, including "Sync all" and Group membership.
  - The keep rule on Playlist deletion, Channel deletion, and removal from the playlist, including forgetting a
    creator with no Videos left.
  - Bringing an outside creator into the Library and keeping their Videos.
  - Pause semantics in both directions.
  - Search scopes, including "Everything" and the chosen-channels rejection of outside creators.
  - Playlist Conversations: creation, the 409s, Citations restricted to the Playlist, read-only after deletion, and
    read-only after the creator is re-added.
  - The MCP tools `list_playlists`, `search(playlist=…)`, and the bound Playlist server's tools.
  - The CLI's `--playlist` targets, `--all` including Playlists, and `seek list` (prior art: the CLI lifecycle and
    sync-command tests).

  Prior art: the channels, groups, sync, channel-filter, search, conversations, chat, and MCP test modules.
- **Migration** (the existing migrations test pattern): migrate a populated pre-Playlist database through the app.
  The fixture's vectors must match the fake embedder's dimension, either by using a 4-d fake or a 64-d fixture.
  Check that:
  - Channels, Groups, Videos, Conversations (with all their columns), and Syncs survive.
  - The vector count and each segment's Video survive, and a search finds the migrated Segment.
  - A fresh database gets the new shape.

  The fixture's `segment_vectors` insert and its assertion change from `channel_id` to `video_id`.
- **Checks:** extend the pure `is_due` test and the app-level check test so Active Playlists are queued on the same
  schedule and Paused or never-synced ones are not.
- **Web:** the Playwright smoke test adds a Playlist, sees its page with creators and avatars or initials, picks it
  as a Search chip, uses "Ask about this", and starts a chat in it. Typecheck and build stay green.
- **Retrieval baseline:** rerun once after the vector rebuild. It should be unchanged, which confirms the `video_id`
  filter loses nothing.

## Out of Scope

- A way to set YouTube cookies from the web UI (they remain config-file settings).
- Adding or removing Playlists from the CLI (Channels have no CLI add either).
- Playlists curated inside Seek (hand-added video URLs), and single-video sources (still open in MVP §3).
- Playlists inside Groups, and Playlists in shareable recipes (MVP §4).
- An "Add this creator" shortcut on the Playlist page.
- Per-scope exclusion (a Video searchable in a Playlist but hidden in its Channel's scope).
- A user-set recency preference for chats.

## Further Notes

- Shorts have no dedicated rule. Channels avoid them by not listing the Shorts tab, but a playlist lists whatever it
  holds, so a Short in a Playlist is excluded only if it falls under the minimum length.
