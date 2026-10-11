from pathlib import Path

import httpx
from harness import (
    WRIGHT_AVATAR,
    add_channel,
    add_playlist,
    fake_channel,
    fake_video,
    fetched,
    list_playlist_videos,
    list_videos,
    query,
    running,
    start_playlist_sync,
    start_sync,
    wait_for_syncs,
)

from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakePlaylist, FakeReranker, FakeTranscriptSource
from seek.ports import ChannelInfo, SourceUnavailable, VideoUnavailable

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PL-sharpening"


def sharpening(transcripts: FakeTranscriptSource) -> None:
    """The playlist PL-sharpening, "Sharpening": Wood By Wright's chisels, Rex Krueger's knives, then Wood By
    Wright's plane irons."""
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-chisels", "Sharpening chisels"),
        fake_video("v-irons", "Plane irons"),
    ]
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-knives", "Sharpening knives"))
    transcripts.playlists["PL-sharpening"] = FakePlaylist(
        "Sharpening", [("UC-wright", "v-chisels"), ("UC-rex", "v-knives"), ("UC-wright", "v-irons")]
    )


NO_COUNTS = {
    "discovered": 0,
    "transcript_fetched": 0,
    "segmented": 0,
    "embedded": 0,
    "done": 0,
    "failed": 0,
    "excluded": 0,
}


async def test_a_playlist_sync_ingests_each_video_credited_to_its_creator_who_stays_outside_the_library(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    sharpening(transcripts)
    playlist = await add_playlist(client, "PL-sharpening")

    queued = await start_playlist_sync(client, playlist["id"])
    [finished] = await wait_for_syncs(client)
    videos = await list_playlist_videos(client, playlist["id"])
    [listed] = (await client.get("/api/playlists")).json()

    assert (queued["status"], queued["channel_id"], queued["playlist_id"], queued["source_name"]) == (
        "queued",
        None,
        playlist["id"],
        "Sharpening",
    )
    assert (finished["id"], finished["status"], finished["error"]) == (queued["id"], "done", None)
    assert (finished["new_videos"], finished["completed_videos"], finished["remaining_videos"]) == (3, 3, 0)
    assert finished["stage_counts"] == NO_COUNTS | {"done": 3}
    # In the playlist's order, each under the creator who made it.
    assert [(v["youtube_video_id"], v["channel_name"], v["stage"], v["reason"]) for v in videos] == [
        ("v-chisels", "Wood By Wright", "done", None),
        ("v-knives", "Rex Krueger", "done", None),
        ("v-irons", "Wood By Wright", "done", None),
    ]
    assert (videos[0]["published_on"], videos[0]["duration_seconds"], videos[0]["transcript_source"]) == (
        "2025-03-01",
        600,
        "youtube_manual",
    )
    rex, wright = listed["creators"]
    assert listed["creators"] == [
        {"id": rex["id"], "name": "Rex Krueger", "avatar_url": None},
        {"id": wright["id"], "name": "Wood By Wright", "avatar_url": WRIGHT_AVATAR},
    ]
    assert [v["channel_id"] for v in videos] == [wright["id"], rex["id"], wright["id"]]
    assert (listed["indexed_videos"], listed["failed_videos"], listed["excluded_videos"]) == (3, 0, 0)
    assert listed["last_synced_at"] == finished["finished_at"]
    # The creators credit the Videos without joining the Library, and are never checked on their own.
    assert (await client.get("/api/channels")).json() == []
    assert (await client.get(f"/api/channels/{rex['id']}/videos")).status_code == 404
    # No surface shows a creator's check setting.
    creators = query(config, "SELECT name, check_every_hours FROM channels ORDER BY name")
    assert [tuple(row) for row in creators] == [("Rex Krueger", None), ("Wood By Wright", None)]
    # Each new creator's avatar is looked up once, at the Sync's pace.
    assert transcripts.paced_resolves == ["UC-wright", "UC-rex"]


async def test_a_playlist_sync_skips_videos_under_the_minimum_length_and_records_why_others_failed(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-rex").videos += [
        fake_video("v-tip", "Quick tip", listed_duration=90, duration=90),
        fake_video("v-unlisted-length", "Glue-up in a minute", listed_duration=None, duration=60),
        fake_video("v-members", "Members stream", failure=VideoUnavailable("Members-only Video", permanent=True)),
        fake_video("v-knives", "Sharpening knives"),
    ]
    transcripts.playlists["PL-rex"] = FakePlaylist(
        "Rex picks", [("UC-rex", "v-knives"), ("UC-rex", "v-tip"), ("UC-rex", "v-members"), ("UC-rex", "v-unlisted-length")]
    )
    playlist = await add_playlist(client, "PL-rex")

    await start_playlist_sync(client, playlist["id"])
    [finished] = await wait_for_syncs(client)
    videos = await list_playlist_videos(client, playlist["id"])
    [listed] = (await client.get("/api/playlists")).json()

    assert [(v["title"], v["stage"]) for v in videos] == [
        ("Sharpening knives", "done"),
        ("Quick tip", "excluded"),
        ("Members stream", "failed"),
        ("Glue-up in a minute", "excluded"),
    ]
    assert "120" in videos[1]["reason"] and "120" in videos[3]["reason"]
    assert (videos[2]["reason"], videos[2]["permanent_failure"]) == ("Members-only Video", True)
    assert "v-tip" not in fetched(transcripts)
    assert (finished["status"], finished["completed_videos"], finished["failed_videos"]) == ("done", 2, 1)
    assert finished["stage_counts"] == NO_COUNTS | {"done": 1, "failed": 1, "excluded": 2}
    assert (listed["indexed_videos"], listed["failed_videos"], listed["excluded_videos"]) == (1, 1, 2)


async def test_a_video_shared_with_a_library_channel_is_one_video_that_either_sync_can_advance(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)
    wright = await add_channel(client, "@woodbywright", "Paul Wright")
    playlist = await add_playlist(client, "PL-sharpening")

    # The Playlist reaches the chisels first; the Channel's own Sync then finds them done and fetches only the rest.
    await start_playlist_sync(client, playlist["id"])
    await wait_for_syncs(client)
    after_playlist = fetched(transcripts)
    await start_sync(client, wright["id"])
    channel_sync, _ = await wait_for_syncs(client)
    after_channel = fetched(transcripts)
    # And the other way about: a Video the Channel has already ingested is not fetched again for a Playlist.
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-saws", "Saw sharpening"))
    await start_sync(client, wright["id"])
    await wait_for_syncs(client)
    transcripts.playlists["PL-saws"] = FakePlaylist("Saws", [("UC-wright", "v-saws")])
    saws = await add_playlist(client, "PL-saws")
    await start_playlist_sync(client, saws["id"])
    saws_sync, *_ = await wait_for_syncs(client)

    assert sorted(after_playlist) == ["v-chisels", "v-irons", "v-knives"]
    assert after_channel == after_playlist
    assert (channel_sync["status"], channel_sync["new_videos"]) == ("done", 0)
    assert fetched(transcripts) == [*after_playlist, "v-saws"]
    assert (saws_sync["status"], saws_sync["new_videos"], saws_sync["stage_counts"]) == (
        "done",
        1,
        NO_COUNTS | {"done": 1},
    )
    channel_videos = await list_videos(client, wright["id"])
    assert {title: v["stage"] for title, v in channel_videos.items()} == {
        "Sharpening chisels": "done",
        "Plane irons": "done",
        "Saw sharpening": "done",
    }
    [saw] = await list_playlist_videos(client, saws["id"])
    assert (saw["id"], saw["channel_id"], saw["channel_name"]) == (
        channel_videos["Saw sharpening"]["id"],
        wright["id"],
        "Paul Wright",
    )
    # One Video each, whichever Sync reached it first: the first Playlist lists the Channel's own two.
    picks = await list_playlist_videos(client, playlist["id"])
    assert [v["id"] for v in picks if v["channel_id"] == wright["id"]] == [
        channel_videos["Sharpening chisels"]["id"],
        channel_videos["Plane irons"]["id"],
    ]
    # The Channel was known, so only Rex's avatar needed looking up, and it stays in the Library under its name.
    assert transcripts.paced_resolves == ["UC-rex"]
    assert [(c["name"], c["indexed_videos"]) for c in (await client.get("/api/channels")).json()] == [("Paul Wright", 3)]


class NoAvatarFor(FakeTranscriptSource):
    """Refuses to resolve one channel, as YouTube may while a Sync looks up its avatar."""

    refused: str = "UC-rex"

    def resolve_channel(self, url_or_handle: str, paced: bool = False) -> ChannelInfo:
        if url_or_handle == self.refused:
            self._call("resolve_channel", url_or_handle)
            raise SourceUnavailable("YouTube is rate limiting requests")
        return super().resolve_channel(url_or_handle, paced)


async def test_a_creator_whose_avatar_cant_be_looked_up_is_left_on_initials_and_the_sync_goes_on(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    source = NoAvatarFor(channels=transcripts.channels)
    fake_channel(source, "UC-rex").info = ChannelInfo("UC-rex", "Rex Krueger", avatar_url="https://yt3/rex=s176")
    sharpening(source)
    app = create_app(config, source, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")

    async with running(app) as client:
        playlist = await add_playlist(client, "PL-sharpening")
        await start_playlist_sync(client, playlist["id"])
        [finished] = await wait_for_syncs(client)
        [listed] = (await client.get("/api/playlists")).json()

    assert (finished["status"], finished["stage_counts"]["done"]) == ("done", 3)
    assert [(c["name"], c["avatar_url"]) for c in listed["creators"]] == [
        ("Rex Krueger", None),
        ("Wood By Wright", WRIGHT_AVATAR),
    ]


async def test_a_playlist_sync_that_youtube_keeps_refusing_stops_and_says_its_playlist_waits(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    refused = VideoUnavailable("YouTube is rate limiting requests", permanent=False, throttled=True)
    fake_channel(transcripts, "UC-rex").videos += [
        fake_video(f"v-{n}", f"Video {n}", failure=refused) for n in ("one", "two", "three", "four")
    ]
    transcripts.playlists["PL-rex"] = FakePlaylist(
        "Rex picks", [("UC-rex", f"v-{n}") for n in ("one", "two", "three", "four")]
    )
    playlist = await add_playlist(client, "PL-rex")

    await start_playlist_sync(client, playlist["id"])
    [stopped] = await wait_for_syncs(client)
    videos = await list_playlist_videos(client, playlist["id"])

    assert stopped["status"] == "failed"
    assert stopped["error"] == (
        "YouTube is rate limiting requests. 3 Videos in a row were refused, so the Sync stopped; the Playlist's "
        "remaining Videos wait for the next Sync"
    )
    assert [v["stage"] for v in videos] == ["failed", "failed", "failed", "discovered"]


async def test_a_reindex_sync_of_a_playlist_embeds_its_videos_again_without_fetching_them(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, embedder: FakeEmbedder
) -> None:
    sharpening(transcripts)
    playlist = await add_playlist(client, "PL-sharpening")
    await start_playlist_sync(client, playlist["id"])
    await wait_for_syncs(client)
    embedded, fetched_once = len(embedder.passages), fetched(transcripts)

    queued = await client.post(f"/api/playlists/{playlist['id']}/syncs", json={"reindex": True})
    reindexed, _ = await wait_for_syncs(client)

    assert queued.status_code == 202
    assert (reindexed["id"], reindexed["status"], reindexed["completed_videos"]) == (queued.json()["id"], "done", 3)
    assert embedded > 0 and len(embedder.passages) == 2 * embedded
    assert fetched(transcripts) == fetched_once


async def test_retry_failed_and_reindex_on_a_playlist_take_the_videos_it_shares_with_a_library_channel(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, embedder: FakeEmbedder
) -> None:
    sharpening(transcripts)
    chisels = fake_channel(transcripts, "UC-wright").videos[0]
    chisels.failure = VideoUnavailable("Members-only Video", permanent=True)
    wright = await add_channel(client, "@woodbywright")
    playlist = await add_playlist(client, "PL-sharpening")
    await start_sync(client, wright["id"])
    await start_playlist_sync(client, playlist["id"])
    await wait_for_syncs(client)
    failed = await list_videos(client, wright["id"])

    chisels.failure = None
    retry = await client.post(f"/api/playlists/{playlist['id']}/retry-failed")
    retried, *_ = await wait_for_syncs(client)
    after_retry = await list_videos(client, wright["id"])
    embedded, fetched_once = len(embedder.passages), fetched(transcripts)
    await client.post(f"/api/playlists/{playlist['id']}/syncs", json={"reindex": True})
    reindexed, *_ = await wait_for_syncs(client)

    assert (failed["Sharpening chisels"]["stage"], failed["Sharpening chisels"]["permanent_failure"]) == ("failed", True)
    assert retry.status_code == 202
    assert (retried["status"], retried["completed_videos"]) == ("done", 1)
    assert {title: v["stage"] for title, v in after_retry.items()} == {"Sharpening chisels": "done", "Plane irons": "done"}
    # Every Video here is in the Playlist, the Channel's two among them, so the reindex embeds them all again.
    assert (reindexed["status"], reindexed["completed_videos"]) == ("done", 3)
    assert embedded > 0 and len(embedder.passages) == 2 * embedded
    assert fetched(transcripts) == fetched_once
    assert {v["stage"] for v in (await list_videos(client, wright["id"])).values()} == {"done"}


async def test_syncing_or_listing_a_playlist_that_was_never_added_is_not_found(client: httpx.AsyncClient) -> None:
    responses = [
        await client.post("/api/playlists/999/syncs"),
        await client.post("/api/playlists/999/retry-failed"),
        await client.get("/api/playlists/999/videos"),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
    assert {r.json()["detail"] for r in responses} == {"Playlist 999 not found"}


async def test_a_playlist_is_resolved_from_its_url_and_added_under_its_youtube_title_without_starting_a_sync(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)

    proposal = await client.post("/api/playlists/resolve", json={"playlist": f"  {PLAYLIST_URL}  "})
    added = await add_playlist(client, "https://www.youtube.com/watch?v=v-knives&list=PL-sharpening")
    listed = await client.get("/api/playlists")

    assert proposal.status_code == 200, proposal.text
    assert proposal.json() == {"youtube_playlist_id": "PL-sharpening", "title": "Sharpening", "video_count": 3}
    assert added == {
        "id": added["id"],
        "youtube_playlist_id": "PL-sharpening",
        "name": "Sharpening",
        "indexed": True,
        "check_every_hours": 24,
        "indexed_videos": 0,
        "failed_videos": 0,
        "excluded_videos": 0,
        "last_synced_at": None,
        "next_check_at": None,
        "creators": [],
    }
    assert listed.json() == [added]
    # The first Sync is the user's to start, and nothing was ingested to add it.
    assert (await client.get("/api/syncs")).json() == []
    assert {method for method, _ in transcripts.calls} == {"resolve_playlist"}
    assert (await client.get("/api/channels")).json() == []


async def test_playlists_are_listed_by_name_and_a_given_name_replaces_the_youtube_title(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)
    transcripts.playlists["PL-joinery"] = FakePlaylist("Joinery", [])

    await add_playlist(client, "PL-sharpening", "  my edges  ")
    await add_playlist(client, "PL-joinery")

    assert [p["name"] for p in (await client.get("/api/playlists")).json()] == ["Joinery", "my edges"]


async def test_adding_a_playlist_twice_or_under_a_taken_name_is_refused(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)
    transcripts.playlists["PL-joinery"] = FakePlaylist("Joinery", [])
    await add_playlist(client, "PL-sharpening", "Edges")

    again = await client.post("/api/playlists", json={"playlist": PLAYLIST_URL, "name": "Another name"})
    same_name = await client.post("/api/playlists", json={"playlist": "PL-joinery", "name": "EDGES"})

    assert again.status_code == 409
    assert again.json()["detail"] == "The playlist 'Sharpening' is already added as 'Edges'"
    assert same_name.status_code == 409
    assert same_name.json()["detail"] == "A Playlist named 'Edges' already exists"
    assert [p["name"] for p in (await client.get("/api/playlists")).json()] == ["Edges"]


async def test_a_missing_or_private_playlist_is_refused_with_how_to_give_seek_access(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    resolved = await client.post("/api/playlists/resolve", json={"playlist": "PL-private"})
    added = await client.post("/api/playlists", json={"playlist": "PL-private"})
    blank = await client.post("/api/playlists/resolve", json={"playlist": "   "})
    transcripts.unavailable = "YouTube is rate limiting requests"
    unreachable = await client.post("/api/playlists/resolve", json={"playlist": "PL-private"})

    assert (resolved.status_code, added.status_code, blank.status_code) == (422, 422, 422)
    assert resolved.json() == added.json()
    assert "doesn't exist or is private" in resolved.json()["detail"]
    assert "youtube_cookies_from_browser" in resolved.json()["detail"]
    assert unreachable.status_code == 503
    assert (await client.get("/api/playlists")).json() == []


async def test_a_playlist_is_renamed_paused_and_given_a_check_interval_each_leaving_the_rest_unchanged(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)
    added = await add_playlist(client, "PL-sharpening")
    url = f"/api/playlists/{added['id']}"

    renamed = await client.patch(url, json={"name": "  My edges  "})
    weekly = await client.patch(url, json={"check_every_hours": 168})
    paused = await client.patch(url, json={"indexed": False})
    off = await client.patch(url, json={"check_every_hours": None})
    resumed = await client.patch(url, json={"indexed": True})

    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == added | {"name": "My edges"}
    assert weekly.json() == added | {"name": "My edges", "check_every_hours": 168}
    # Pausing keeps the interval; only null turns checks off.
    assert paused.json() == added | {"name": "My edges", "check_every_hours": 168, "indexed": False}
    assert off.json() == added | {"name": "My edges", "check_every_hours": None, "indexed": False}
    assert resumed.json() == added | {"name": "My edges", "check_every_hours": None}
    assert (await client.get("/api/playlists")).json() == [resumed.json()]


async def test_sync_all_covers_active_playlists_beside_the_librarys_channels_and_leaves_paused_ones(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)
    transcripts.playlists["PL-joinery"] = FakePlaylist("Joinery", [("UC-rex", "v-knives")])
    wright = await add_channel(client, "@woodbywright")
    active = await add_playlist(client, "PL-sharpening")
    paused = await add_playlist(client, "PL-joinery")
    await client.patch(f"/api/playlists/{paused['id']}", json={"indexed": False})

    response = await client.post("/api/syncs")
    finished = await wait_for_syncs(client)

    assert response.status_code == 202, response.text
    assert [(s["channel_id"], s["playlist_id"]) for s in response.json()] == [(wright["id"], None), (None, active["id"])]
    assert [(s["source_name"], s["status"]) for s in finished] == [("Sharpening", "done"), ("Wood By Wright", "done")]
    assert [len(await list_playlist_videos(client, p["id"])) for p in (active, paused)] == [3, 0]


async def test_a_playlist_cant_take_another_playlists_name_a_blank_one_or_an_odd_check_interval(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)
    transcripts.playlists["PL-joinery"] = FakePlaylist("Joinery", [])
    edges = await add_playlist(client, "PL-sharpening", "Edges")
    await add_playlist(client, "PL-joinery")
    url = f"/api/playlists/{edges['id']}"

    taken = await client.patch(url, json={"name": "joinery"})
    own_name = await client.patch(url, json={"name": "EDGES"})
    refused = [
        (await client.patch(url, json=body)).status_code
        for body in ({"name": "  "}, {"indexed": "no"}, {"check_every_hours": 12}, {"check_every_hours": 24.0})
    ]
    unknown = await client.patch("/api/playlists/999", json={"name": "Anything"})

    assert (taken.status_code, taken.json()) == (409, {"detail": "A Playlist named 'Joinery' already exists"})
    assert (own_name.status_code, own_name.json()["name"]) == (200, "EDGES")
    assert refused == [422] * 4
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "Playlist 999 not found"})
    assert [p["name"] for p in (await client.get("/api/playlists")).json()] == ["EDGES", "Joinery"]
