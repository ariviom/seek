# Seek — Domain Glossary

The ubiquitous language for this project. Terms only; no implementation detail.

## Terms

**Library**
The Channels, Groups, and Playlists you have added.

**Channel**
A YouTube channel. Every Video is credited to one. A Channel in the Library is a unit of ingestion, filtering, and search scope; one outside the Library exists only to credit a Playlist's Videos to their creator. Identified by a name you give it, defaulting to its display name.

**Playlist filter**
A Channel's option to keep only its own Videos that appear in a given YouTube playlist.
_Avoid_: Playlist (that is a separate concept)

**Group**
A named set of Channels you consult together on a discipline (e.g. "woodworking"). A Channel may belong to many Groups.

**Playlist**
A YouTube playlist added to the Library, whose Videos may come from many Channels. Consulted on its own. Identified by a name you give it, defaulting to its YouTube title.
_Avoid_: Collection, list

**Video**
One YouTube video, credited to one Channel and possibly included in Playlists. Carries its publish date, which is used to judge how current its advice is.

**Transcript**
The spoken text of a Video, as timestamped lines. Each Transcript records its source (YouTube captions today; other sources possible later).

**Segment**
A timestamped slice of a Transcript. The unit of retrieval and citation. A Segment always knows its Video, its start time, and the precise time of any matched line within it.

**Citation**
A link back to a Video at a specific timestamp, attached to a Segment so advice can be verified against the original footage.

**Sync**
A run of the ingestion pipeline for one Channel or one Playlist. Discovers new Videos and advances every unfinished Video through its pipeline stages. Re-running a Sync resumes where the last one stopped. Syncs run one at a time.

**Pipeline stage**
Where a Video sits in ingestion: discovered, transcript fetched, segmented, embedded, done, or failed with a reason. Failed Videos can be retried. A Video can also be excluded with a reason (too short, or outside the Channel's filters); excluded Videos are not processed and are not failures.

**Bundle**
A `.seek` file holding one Channel's or one Playlist's indexed Videos, with their Transcripts and Segments, for handing to another Seek. Exported from one Library and imported into another.
_Avoid_: export (as a noun), pack, archive, backup

**Conversation**
A saved chat thread scoped to exactly one Group, one Channel, or one Playlist; a Channel alone works like a group of one. It may
also keep read-only access to a selected local project, the public web, or both. Resumable.

## Relationships

- Group ⟷ Channel: many-to-many
- Channel → Video: one-to-many (credit)
- Playlist ⟷ Video: many-to-many
- Video → Transcript: one-to-one
- Transcript → Segment: one-to-many
- Group → Conversation: one-to-many
- Channel → Conversation: one-to-many
- Playlist → Conversation: one-to-many
- Channel → Sync: one-to-many (over time)
- Playlist → Sync: one-to-many (over time)

## Decisions reflected in the language

- A Group is a set of Channels. Excluding a Channel from syncs, search, and chats is done on the Channel (pause it), not per Group.
- A Group holds Channels only; a Playlist is consulted on its own.
- A Playlist comes from a YouTube playlist (a private one needs Seek signed in as its owner) and follows it: Videos added there are added, Videos removed there are removed.
- A Video is searchable if a Library Channel's filters admit it or any Playlist includes it; inclusion wins over a Channel's filters. Videos under the minimum length stay excluded either way.
- A Video is kept only while a Library Channel or a Playlist includes it.
- Pausing affects only what was paused: a paused Channel's Videos stay searchable through an Active Playlist that includes them, and the reverse.
- A Channel outside the Library is never a scope: it is not offered in pickers and is not a Conversation's scope. Adding it through the usual flow brings it into the Library, keeping its indexed Videos.
- Deleting a Channel whose Videos a Playlist includes takes it out of the Library; those Videos stay.
- A deleted Group, Channel, or Playlist leaves its Conversations readable but not continuable.
- An imported Bundle becomes an ordinary Channel or Playlist in the Library, and never replaces a Video that has finished indexing there.
- "Seek" is the product's name and nothing else.
- Shorts and very short Videos are excluded from ingestion by default.
- The tool has one user. Identity, when accessed remotely, is established outside the tool.
- Newer Videos are preferred over older ones when they address the same question; every result exposes its publish date.
