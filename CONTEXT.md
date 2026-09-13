# Mentor — Domain Glossary

The ubiquitous language for this project. Terms only; no implementation detail.

## Terms

**Mentor**
A creator (a person or brand) whose teaching you want advice from. Owns one or more Channels. Identified by a name you give it.

**Channel**
A YouTube channel. Belongs to exactly one Mentor. The unit at which content is ingested and filtered.

**Mentor Group**
A named set of Mentors you consult together on a discipline (e.g. "woodworking"). A Mentor may belong to many Groups. Group membership is by Mentor, never by Channel.

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
Where a Video sits in ingestion: discovered, transcript fetched, segmented, embedded, done, or failed with a reason. Failed Videos can be retried.

**Conversation**
A saved chat thread with one Mentor Group. Resumable.

## Relationships

- Mentor Group ⟷ Mentor: many-to-many
- Mentor → Channel: one-to-many
- Channel → Video: one-to-many
- Video → Transcript: one-to-one
- Transcript → Segment: one-to-many
- Mentor Group → Conversation: one-to-many
- Channel → Sync: one-to-many (over time)

## Decisions reflected in the language

- A Group is a set of Mentors, not Channels. Excluding a Channel is done at the Mentor level (mark it not indexed), not per Group.
- Shorts and very short Videos are excluded from ingestion by default.
- The tool has one user. Identity, when accessed remotely, is established outside the tool.
- Newer Videos are preferred over older ones when they address the same question; every result exposes its publish date.
