# 03 — Mentor Groups

**What to build:** From the web UI, create a named Mentor Group, rename it, delete it, and set its member Mentors. A Mentor can belong to several Groups. Membership is always by Mentor, never by Channel. (Stories 5–6.)

**Blocked by:** 02 — Mentors and Channels

**Status:** ready-for-agent

- [ ] Group create, rename, delete, set members via API and UI
- [ ] Group names are unique
- [ ] A Mentor in several Groups appears in each; deleting a Mentor removes it from every Group
- [ ] API tests cover many-to-many membership and the uniqueness error
