# Seek — Domain Glossary

The ubiquitous language for this project. Terms only; no implementation detail.

## Terms

**Channel**
A YouTube channel. The unit of ingestion, filtering, search scope, and citation. Identified by a name you give it, defaulting to its display name.

**Group**
A named set of Channels you consult together on a discipline (e.g. "woodworking"). A Channel may belong to many Groups.

**Video**
One YouTube video on a Channel. Carries its publish date, which is used to judge how current its advice is.

**Transcript**
The spoken text of a Video, as timestamped lines. Each Transcript records its source (YouTube captions today; other sources possible later).

**Segment**
A timestamped slice of a Transcript. The unit of retrieval and citation. A Segment always knows its Video, its start time, and the precise time of any matched line within it.

**Citation**
A link back to a Video at a specific timestamp, attached to a Segment so advice can be verified against the original footage.

**Sync**
A run of the ingestion pipeline for one Channel. Discovers new Videos and advances every unfinished Video through its pipeline stages. Re-running a Sync resumes where the last one stopped. Syncs run one at a time.

**Pipeline stage**
Where a Video sits in ingestion: discovered, transcript fetched, segmented, embedded, done, or failed with a reason. Failed Videos can be retried. A Video can also be excluded with a reason (too short, or outside the Channel's filters); excluded Videos are not processed and are not failures.

**Conversation**
A saved chat thread scoped to exactly one Group or one Channel; a Channel alone works like a group of one. It may
also keep read-only access to a selected local project, the public web, or both. Resumable.

## Relationships

- Group ⟷ Channel: many-to-many
- Channel → Video: one-to-many
- Video → Transcript: one-to-one
- Transcript → Segment: one-to-many
- Group → Conversation: one-to-many
- Channel → Conversation: one-to-many
- Channel → Sync: one-to-many (over time)

## Decisions reflected in the language

- A Group is a set of Channels. Excluding a Channel from syncs, search, and chats is done on the Channel (pause it), not per Group.
- A deleted Group or Channel leaves its Conversations readable but not continuable.
- "Seek" is the product's name and nothing else.
- Shorts and very short Videos are excluded from ingestion by default.
- The tool has one user. Identity, when accessed remotely, is established outside the tool.
- Newer Videos are preferred over older ones when they address the same question; every result exposes its publish date.
