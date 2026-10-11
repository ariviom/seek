# 04: Playlists in the Library

**What to build:** In the web app, the Library has a Playlists tab beside Channels and Groups. I can paste a URL, see its title and video count, and add it. The Playlist's page lists its Videos in playlist order, with each creator's avatar (or initials) and name, their pipeline status and any exclusion reason, plus Sync and retry buttons. Creators outside the Library get avatars anywhere the app shows a Channel. See Spec 0004 §Web UI.

**Blocked by:** 03 (Add and sync a Playlist over the API).

**Status:** ready-for-agent

- [ ] The Library has a third tab, Playlists, and the URL state carries `playlist` and the `playlists` tab.
- [ ] The Add Playlist dialog resolves the URL, shows the title and video count, and confirms. It shows the API's messages for a duplicate, a missing or private playlist, and a taken name.
- [ ] The Playlist page has a Videos table with a creator column, live Sync progress, and Sync and retry buttons. It reloads on video and videos events for that Playlist.
- [ ] The channel-avatar map also takes creators from `GET /playlists`.
- [ ] The Playwright smoke test adds a Playlist, syncs it, and sees its Videos with creators. Typecheck and build pass.
