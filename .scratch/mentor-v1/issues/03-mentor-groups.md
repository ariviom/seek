# 03 — Mentor Groups

**What to build:** From the web UI, create a named Mentor Group, rename it, delete it, and set its member Mentors. A Mentor can belong to several Groups. Membership is always by Mentor, never by Channel. (Stories 5–6.)

**Blocked by:** 02 — Mentors and Channels

**Status:** done

- [x] Group create, rename, delete, set members via API and UI
- [x] Group names are unique
- [x] A Mentor in several Groups appears in each; deleting a Mentor removes it from every Group
- [x] API tests cover many-to-many membership and the uniqueness error

Done note: `PUT /api/groups/{id}/members` replaces the member set (repeats collapse; any unknown Mentor id is a 404 and nothing changes). `GET /api/groups` lists Groups with member Mentors. Group names are unique ignoring ASCII case, like Mentor names. `mentor_groups.id` is AUTOINCREMENT, so a deleted Group's id is never reused. Mentors and Mentor Groups keep separate busy locks in the UI; the Groups section reloads when a Mentor is added, renamed, or deleted and discards out-of-order reloads.
