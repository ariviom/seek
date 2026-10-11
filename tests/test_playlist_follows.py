import httpx
from harness import (
    Json,
    add_playlist,
    fake_channel,
    fake_storyboard,
    fake_video,
    fetched,
    list_playlist_videos,
    list_videos,
    query,
    row_counts,
    said,
    sharpening_picks,
    start_playlist_sync,
    sync_playlist,
    wait_for_syncs,
)

from seek.config import Config
from seek.fakes import FakePlaylist, FakeTranscriptSource


async def found(client: httpx.AsyncClient, **scope: object) -> set[str]:
    """The YouTube ids of the Videos a search for sharpening finds in the scope."""
    response = await client.post("/api/search", json={"query": "sharpen on a fine stone", **scope})
    assert response.status_code == 200, response.text
    return {result["youtube_video_id"] for result in response.json()}


async def resync(client: httpx.AsyncClient, playlist: Json) -> Json:
    """Syncs the Playlist again; returns that Sync once nothing is queued or running."""
    await start_playlist_sync(client, playlist["id"])
    latest, *_ = await wait_for_syncs(client)
    return latest


async def test_a_listing_that_fails_fails_the_sync_and_removes_nothing(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    _, playlist = await sharpening_picks(client, transcripts)
    before = await list_playlist_videos(client, playlist["id"])

    transcripts.unavailable = "YouTube is rate limiting requests"
    unreachable = await resync(client, playlist)
    transcripts.unavailable = None
    # The playlist was made private, or deleted, on YouTube.
    del transcripts.playlists["PL-picks"]
    missing = await resync(client, playlist)

    assert (unreachable["status"], unreachable["error"]) == ("failed", "YouTube is rate limiting requests")
    assert missing["status"] == "failed"
    assert "doesn't exist or is private" in missing["error"]
    assert [v["youtube_video_id"] for v in before] == ["v-knives", "v-chisels"]
    assert await list_playlist_videos(client, playlist["id"]) == before
    assert await found(client, playlist=playlist["id"]) == {"v-knives", "v-chisels"}


async def test_a_listing_that_comes_back_empty_fails_the_sync_and_removes_nothing(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    _, playlist = await sharpening_picks(client, transcripts)
    before = await list_playlist_videos(client, playlist["id"])

    transcripts.playlists["PL-picks"].entries.clear()
    emptied = await resync(client, playlist)

    assert emptied["status"] == "failed"
    assert emptied["error"] == (
        "YouTube listed no Videos in this playlist, so nothing was removed. If the playlist really is empty now, "
        "delete the Playlist"
    )
    assert await list_playlist_videos(client, playlist["id"]) == before
    assert await found(client, playlist=playlist["id"]) == {"v-knives", "v-chisels"}


async def test_a_playlist_that_never_had_videos_syncs_an_empty_listing_without_complaint(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    transcripts.playlists["PL-later"] = FakePlaylist("Watch later", [])
    playlist = await add_playlist(client, "PL-later")

    synced = await resync(client, playlist)

    assert (synced["status"], synced["error"], synced["new_videos"]) == ("done", None, 0)
    assert await list_playlist_videos(client, playlist["id"]) == []


async def test_a_video_removed_from_the_playlist_stays_under_the_library_channel_that_credits_it(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    wright, playlist = await sharpening_picks(client, transcripts)

    transcripts.playlists["PL-picks"].entries.remove(("UC-wright", "v-chisels"))
    synced = await resync(client, playlist)

    assert (synced["status"], synced["new_videos"]) == ("done", 0)
    assert [v["youtube_video_id"] for v in await list_playlist_videos(client, playlist["id"])] == ["v-knives"]
    assert await found(client, playlist=playlist["id"]) == {"v-knives"}
    channel_videos = await list_videos(client, wright["id"])
    assert {title: v["stage"] for title, v in channel_videos.items()} == {"Chisels": "done", "Saws": "done"}
    assert await found(client, channels=[wright["id"]]) == {"v-chisels", "v-saws"}
    assert fetched(transcripts).count("v-chisels") == 1


async def test_a_video_removed_from_one_playlist_stays_while_another_playlist_includes_it(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    _, picks = await sharpening_picks(client, transcripts)
    transcripts.playlists["PL-knives"] = FakePlaylist("Knives", [("UC-rex", "v-knives")])
    knives = await add_playlist(client, "PL-knives")
    await sync_playlist(client, knives)

    transcripts.playlists["PL-picks"].entries.remove(("UC-rex", "v-knives"))
    synced = await resync(client, picks)

    assert synced["status"] == "done"
    assert [v["youtube_video_id"] for v in await list_playlist_videos(client, picks["id"])] == ["v-chisels"]
    # Rex Krueger is outside the Library, so only the other Playlist keeps his Video, and him.
    [kept] = await list_playlist_videos(client, knives["id"])
    assert (kept["youtube_video_id"], kept["channel_name"], kept["stage"]) == ("v-knives", "Rex Krueger", "done")
    assert await found(client, playlist=knives["id"]) == await found(client) - {"v-chisels", "v-saws"} == {"v-knives"}
    by_name = {p["name"]: p for p in (await client.get("/api/playlists")).json()}
    assert [c["name"] for c in by_name["Knives"]["creators"]] == ["Rex Krueger"]
    assert [c["name"] for c in by_name["Sharpening picks"]["creators"]] == ["Wood By Wright"]
    assert fetched(transcripts).count("v-knives") == 1


async def test_a_video_youtube_lists_without_its_creator_stays_until_the_playlist_stops_listing_it(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    _, playlist = await sharpening_picks(client, transcripts)
    entries = transcripts.playlists["PL-picks"].entries

    # Rex Krueger made the knives private: the playlist still lists them, now last, but not whose they are. It
    # also lists a video Seek never saw a creator for.
    entries[:] = [(None, "v-never-seen"), ("UC-wright", "v-chisels"), (None, "v-knives")]
    hidden = await resync(client, playlist)
    videos = await list_playlist_videos(client, playlist["id"])
    still_found = await found(client, playlist=playlist["id"])
    entries.remove((None, "v-knives"))
    gone = await resync(client, playlist)

    assert (hidden["status"], hidden["new_videos"]) == ("done", 0)
    assert [(v["youtube_video_id"], v["channel_name"], v["stage"]) for v in videos] == [
        ("v-chisels", "Wood By Wright", "done"),
        ("v-knives", "Rex Krueger", "done"),
    ]
    assert still_found == {"v-knives", "v-chisels"}
    assert fetched(transcripts).count("v-knives") == 1
    assert gone["status"] == "done"
    assert [v["youtube_video_id"] for v in await list_playlist_videos(client, playlist["id"])] == ["v-chisels"]
    assert await found(client) == {"v-chisels", "v-saws"}
    [listed] = (await client.get("/api/playlists")).json()
    assert [c["name"] for c in listed["creators"]] == ["Wood By Wright"]


async def test_a_playlist_whose_every_video_is_listed_without_its_creator_keeps_them_all(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-knives", "Knives", cues=said("Sharpen the knife on a fine stone"))
    )
    transcripts.playlists["PL-knives"] = FakePlaylist("Knives", [("UC-rex", "v-knives")])
    playlist = await add_playlist(client, "PL-knives")
    await sync_playlist(client, playlist)

    transcripts.playlists["PL-knives"].entries[:] = [(None, "v-knives")]
    synced = await resync(client, playlist)

    assert (synced["status"], synced["error"]) == ("done", None)
    assert [v["youtube_video_id"] for v in await list_playlist_videos(client, playlist["id"])] == ["v-knives"]
    assert await found(client, playlist=playlist["id"]) == {"v-knives"}


def stored(config: Config) -> dict[str, int]:
    """Rows per table of everything kept for a Video, and how many Channels there are, in the Library or not."""
    others = {table: query(config, f"SELECT count(*) FROM {table}")[0][0] for table in ("storyboards", "channels")}
    return row_counts(config) | others


async def test_a_video_that_leaves_its_last_playlist_is_deleted_and_a_creator_left_with_none_is_forgotten(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    _, playlist = await sharpening_picks(client, transcripts)
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-axes", "Axes", cues=said("Sharpen the axe on a fine stone"), storyboard=fake_storyboard())
    )
    entries = transcripts.playlists["PL-picks"].entries
    entries.append(("UC-rex", "v-axes"))
    await sync_playlist(client, playlist)
    everything = stored(config)

    # Rex Krueger is outside the Library, so nothing else keeps the axes; he still made the knives.
    entries.remove(("UC-rex", "v-axes"))
    without_axes = await resync(client, playlist)
    after_axes = stored(config), await found(client)
    entries.remove(("UC-rex", "v-knives"))
    without_rex = await resync(client, playlist)

    rows = ("videos", "transcripts", "segments", "segments_fts_docsize", "segment_vectors")
    assert everything == dict.fromkeys(rows, 4) | {"storyboards": 1, "channels": 2}
    assert (without_axes["status"], without_axes["stage_counts"]["done"]) == ("done", 2)
    assert after_axes == (
        dict.fromkeys(rows, 3) | {"storyboards": 0, "channels": 2},
        {"v-knives", "v-chisels", "v-saws"},
    )
    assert (without_rex["status"], without_rex["stage_counts"]["done"]) == ("done", 1)
    assert stored(config) == dict.fromkeys(rows, 2) | {"storyboards": 0, "channels": 1}
    assert await found(client) == {"v-chisels", "v-saws"}
    [listed] = (await client.get("/api/playlists")).json()
    assert [c["name"] for c in listed["creators"]] == ["Wood By Wright"]
    assert [v["youtube_video_id"] for v in await list_playlist_videos(client, playlist["id"])] == ["v-chisels"]
    assert [tuple(row) for row in query(config, "SELECT name, in_library FROM channels")] == [("Wood By Wright", 1)]


async def test_a_resync_adds_the_videos_added_to_the_playlist_and_follows_its_order(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    _, playlist = await sharpening_picks(client, transcripts)
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-axes", "Axes", cues=said("Sharpen the axe on a fine stone"))
    )

    # The knives went, the axes came, and the chisels moved to the top.
    transcripts.playlists["PL-picks"].entries[:] = [("UC-wright", "v-chisels"), ("UC-rex", "v-axes")]
    synced = await resync(client, playlist)

    assert (synced["status"], synced["new_videos"], synced["completed_videos"]) == ("done", 1, 1)
    videos = await list_playlist_videos(client, playlist["id"])
    assert [(v["youtube_video_id"], v["channel_name"], v["stage"]) for v in videos] == [
        ("v-chisels", "Wood By Wright", "done"),
        ("v-axes", "Rex Krueger", "done"),
    ]
    assert await found(client, playlist=playlist["id"]) == {"v-chisels", "v-axes"}
    assert fetched(transcripts)[-1:] == ["v-axes"] and fetched(transcripts).count("v-chisels") == 1
