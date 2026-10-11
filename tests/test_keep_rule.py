from datetime import date

import httpx
from harness import (
    Gate,
    Json,
    add_channel,
    add_group,
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
    start_sync,
    sync,
    sync_playlist,
    wait_for_syncs,
)

from seek.config import Config
from seek.fakes import FakeEmbedder, FakePlaylist, FakeTranscriptSource
from seek.ports import VideoUnavailable

ROWS = ("videos", "transcripts", "segments", "segments_fts_docsize", "segment_vectors")


async def found(client: httpx.AsyncClient, **scope: object) -> set[str]:
    """The YouTube ids of the Videos a search for sharpening finds in the scope."""
    response = await client.post("/api/search", json={"query": "sharpen on a fine stone", **scope})
    assert response.status_code == 200, response.text
    return {result["youtube_video_id"] for result in response.json()}


def stages(videos: dict[str, Json]) -> dict[str, str]:
    return {title: v["stage"] for title, v in videos.items()}


def stored(config: Config) -> dict[str, int]:
    """Rows per table of everything kept for a Video, and how many Channels there are, in the Library or not."""
    others = {table: query(config, f"SELECT count(*) FROM {table}")[0][0] for table in ("storyboards", "channels")}
    return row_counts(config) | others


async def set_filters(client: httpx.AsyncClient, channel: Json, **filters: object) -> None:
    unset = {"published_after": None, "published_before": None, "playlist_id": None, "most_recent": None}
    response = await client.patch(f"/api/channels/{channel['id']}", json={"filters": unset | filters})
    assert response.status_code == 200, response.text


async def test_deleting_a_playlist_keeps_the_videos_a_library_channel_credits(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    wright, playlist = await sharpening_picks(client, transcripts)

    deleted = await client.delete(f"/api/playlists/{playlist['id']}")

    assert deleted.status_code == 204
    assert (await client.get("/api/playlists")).json() == []
    assert stages(await list_videos(client, wright["id"])) == {"Chisels": "done", "Saws": "done"}
    assert await found(client, channels=[wright["id"]]) == {"v-chisels", "v-saws"}
    assert fetched(transcripts).count("v-chisels") == 1


async def test_deleting_a_playlist_keeps_the_videos_another_playlist_includes_and_their_creator(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    _, picks = await sharpening_picks(client, transcripts)
    transcripts.playlists["PL-knives"] = FakePlaylist("Knives", [("UC-rex", "v-knives")])
    knives = await add_playlist(client, "PL-knives")
    await sync_playlist(client, knives)

    deleted = await client.delete(f"/api/playlists/{picks['id']}")

    assert deleted.status_code == 204
    # Rex Krueger is outside the Library, so only the other Playlist keeps his Video, and him.
    [kept] = await list_playlist_videos(client, knives["id"])
    assert (kept["youtube_video_id"], kept["channel_name"], kept["stage"]) == ("v-knives", "Rex Krueger", "done")
    assert await found(client, playlist=knives["id"]) == {"v-knives"}
    [listed] = (await client.get("/api/playlists")).json()
    assert (listed["name"], [c["name"] for c in listed["creators"]]) == ("Knives", ["Rex Krueger"])
    assert fetched(transcripts).count("v-knives") == 1


async def test_deleting_a_channel_keeps_the_videos_a_playlist_includes_credited_as_before(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    wright, playlist = await sharpening_picks(client, transcripts)

    deleted = await client.delete(f"/api/channels/{wright['id']}")

    assert deleted.status_code == 204
    assert (await client.get("/api/channels")).json() == []
    videos = await list_playlist_videos(client, playlist["id"])
    assert [(v["youtube_video_id"], v["channel_name"], v["stage"]) for v in videos] == [
        ("v-knives", "Rex Krueger", "done"),
        ("v-chisels", "Wood By Wright", "done"),
    ]
    assert await found(client, playlist=playlist["id"]) == {"v-knives", "v-chisels"}
    [listed] = (await client.get("/api/playlists")).json()
    assert [(c["id"], c["name"]) for c in listed["creators"]][-1] == (wright["id"], "Wood By Wright")
    assert fetched(transcripts).count("v-chisels") == 1


async def test_deleting_a_playlist_deletes_the_videos_nothing_else_includes_and_forgets_their_creator(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    _, playlist = await sharpening_picks(client, transcripts)
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-axes", "Axes", cues=said("Sharpen the axe on a fine stone"), storyboard=fake_storyboard())
    )
    transcripts.playlists["PL-picks"].entries.append(("UC-rex", "v-axes"))
    await sync_playlist(client, playlist)
    everything = stored(config), await found(client)

    deleted = await client.delete(f"/api/playlists/{playlist['id']}")
    again = await client.delete(f"/api/playlists/{playlist['id']}")

    assert everything == (
        dict.fromkeys(ROWS, 4) | {"storyboards": 1, "channels": 2},
        {"v-knives", "v-axes", "v-chisels", "v-saws"},
    )
    assert (deleted.status_code, again.status_code) == (204, 404)
    # Rex Krueger is outside the Library, so nothing else kept his Videos, and then nothing kept him.
    assert stored(config) == dict.fromkeys(ROWS, 2) | {"storyboards": 0, "channels": 1}
    assert await found(client) == {"v-chisels", "v-saws"}
    assert [tuple(row) for row in query(config, "SELECT name, in_library FROM channels")] == [("Wood By Wright", 1)]
    # The Playlist's Syncs went with it.
    assert [s["source_name"] for s in (await client.get("/api/syncs")).json()] == ["Wood By Wright"]


async def test_deleting_a_playlist_puts_its_videos_back_under_their_library_channels_date_window(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-mid", "Irons", published_on=date(2024, 6, 1), cues=said("Sharpen the iron on a fine stone")),
        fake_video("v-old", "Saws", published_on=date(2020, 1, 1), cues=said("Sharpen the saw on a fine stone")),
    ]
    transcripts.playlists["PL-picks"] = FakePlaylist("Picks", [("UC-wright", "v-old")])
    wright = await add_channel(client, "@woodbywright")
    await set_filters(client, wright, published_after="2024-01-01")
    await sync(client, wright)
    playlist = await add_playlist(client, "PL-picks")
    await sync_playlist(client, playlist)
    included = stages(await list_videos(client, wright["id"])), await found(client)

    await client.delete(f"/api/playlists/{playlist['id']}")

    assert included == ({"Irons": "done", "Saws": "done"}, {"v-mid", "v-old"})
    videos = await list_videos(client, wright["id"])
    assert {title: (v["stage"], v["reason"]) for title, v in videos.items()} == {
        "Irons": ("done", None),
        "Saws": ("excluded", "Published before 2024-01-01, outside the Channel's filters"),
    }
    assert await found(client) == {"v-mid"}
    # Excluded as a Channel's Sync would: out of the search indexes, its Transcript kept.
    assert row_counts(config) == dict.fromkeys(ROWS, 1) | {"videos": 2, "transcripts": 2}


async def test_a_deleted_channel_a_playlist_draws_on_leaves_the_library_with_only_the_videos_playlists_include(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    wright, playlist = await sharpening_picks(client, transcripts)
    await add_group(client, "Woodworking", wright)
    await set_filters(client, wright, published_after="2020-01-01", most_recent=50)
    before = stored(config)
    url = f"/api/channels/{wright['id']}"

    deleted = await client.delete(url)
    refused = [
        await client.delete(url),
        await client.patch(url, json={"name": "Paul Wright"}),
        await client.get(f"{url}/videos"),
        await client.post(f"{url}/syncs"),
        await client.post(f"{url}/conversations", json={"model": None}),
    ]

    assert before == dict.fromkeys(ROWS, 3) | {"storyboards": 0, "channels": 2}
    assert deleted.status_code == 204
    assert [r.status_code for r in refused] == [404, 404, 404, 404, 404]
    # The saws were in no Playlist; the chisels are in one, so they and their creator stay.
    assert stored(config) == dict.fromkeys(ROWS, 2) | {"storyboards": 0, "channels": 2}
    assert await found(client) == {"v-knives", "v-chisels"}
    [group] = (await client.get("/api/groups")).json()
    assert group["channels"] == []
    assert [s["source_name"] for s in (await client.get("/api/syncs")).json()] == ["Sharpening picks"]
    filters = "published_after, published_before, playlist_id, most_recent"
    left = query(config, f"SELECT name, in_library, {filters} FROM channels WHERE id = ?", (wright["id"],))
    assert [tuple(row) for row in left] == [("Wood By Wright", 0, None, None, None, None)]


async def test_a_deleted_channel_no_playlist_draws_on_goes_with_everything_ingested_from_it(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    wright, playlist = await sharpening_picks(client, transcripts)
    # The Playlist stops including the chisels, so nothing of Wood By Wright's is in a Playlist.
    transcripts.playlists["PL-picks"].entries.remove(("UC-wright", "v-chisels"))
    await sync_playlist(client, playlist)

    deleted = await client.delete(f"/api/channels/{wright['id']}")

    assert deleted.status_code == 204
    assert stored(config) == dict.fromkeys(ROWS, 1) | {"storyboards": 0, "channels": 1}
    assert [tuple(row) for row in query(config, "SELECT name, in_library FROM channels")] == [("Rex Krueger", 0)]
    assert [v["youtube_video_id"] for v in await list_playlist_videos(client, playlist["id"])] == ["v-knives"]
    assert await found(client) == {"v-knives"}


NO_FILTERS = {"published_after": None, "published_before": None, "playlist_id": None, "most_recent": None}


async def test_adding_a_creator_from_outside_the_library_brings_that_channel_in_with_its_indexed_videos(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    _, playlist = await sharpening_picks(client, transcripts)
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-axes", "Axes", cues=said("Sharpen the axe on a fine stone"))
    )
    [creator] = [c for c in (await client.get("/api/playlists")).json()[0]["creators"] if c["name"] == "Rex Krueger"]
    syncs_before = (await client.get("/api/syncs")).json()

    added = await client.post("/api/channels", json={"channel": "@rexkrueger", "name": "Rex"})
    again = await client.post("/api/channels", json={"channel": "@rexkrueger", "name": "Rex again"})
    rex = added.json()
    brought_in = stages(await list_videos(client, rex["id"])), await found(client, channels=[rex["id"]])
    not_synced = (await client.get("/api/syncs")).json()
    await sync(client, rex)

    assert added.status_code == 201
    assert (rex["id"], rex["name"], rex["indexed"], rex["filters"], rex["check_every_hours"]) == (
        creator["id"],
        "Rex",
        True,
        NO_FILTERS,
        24,
    )
    assert rex["indexed_videos"] == 1
    assert (again.status_code, again.json()["detail"]) == (409, "The Channel 'Rex Krueger' is already added as 'Rex'")
    assert [c["name"] for c in (await client.get("/api/channels")).json()] == ["Rex", "Wood By Wright"]
    # The knives are his already; the first Sync, which finds the rest of his uploads, is the user's to start.
    assert brought_in == ({"Knives": "done"}, {"v-knives"})
    assert not_synced == syncs_before
    assert stages(await list_videos(client, rex["id"])) == {"Knives": "done", "Axes": "done"}
    assert fetched(transcripts).count("v-knives") == 1
    videos = await list_playlist_videos(client, playlist["id"])
    assert [(v["youtube_video_id"], v["channel_name"]) for v in videos] == [
        ("v-knives", "Rex"),
        ("v-chisels", "Wood By Wright"),
    ]


async def test_a_playlist_deleted_while_its_sync_runs_takes_the_sync_and_the_videos_nothing_else_includes(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    gate = Gate()
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone")),
        fake_video("v-saws", "Saws", cues=said("Sharpen the saw with a fine file")),
    ]
    fake_channel(transcripts, "UC-rex").videos += [
        fake_video("v-knives", "Knives", before_fetch=gate),
        fake_video("v-axes", "Axes"),
    ]
    transcripts.playlists["PL-picks"] = FakePlaylist(
        "Sharpening picks", [("UC-wright", "v-chisels"), ("UC-rex", "v-knives"), ("UC-rex", "v-axes")]
    )
    wright = await add_channel(client, "@woodbywright")
    await sync(client, wright)
    playlist = await add_playlist(client, "PL-picks")

    await start_playlist_sync(client, playlist["id"])
    await gate.wait_entered()
    behind = await start_sync(client, wright["id"])
    deleted = await client.delete(f"/api/playlists/{playlist['id']}")
    gate.released.set()
    finished = await wait_for_syncs(client)

    assert deleted.status_code == 204
    # The Playlist's Sync went with it, mid-fetch, and the Sync queued behind it ran.
    assert [(s["source_name"], s["status"]) for s in finished] == [("Wood By Wright", "done")] * 2
    assert finished[0]["id"] == behind["id"]
    assert "v-axes" not in fetched(transcripts)
    assert stored(config) == dict.fromkeys(ROWS, 2) | {"storyboards": 0, "channels": 1}
    assert stages(await list_videos(client, wright["id"])) == {"Chisels": "done", "Saws": "done"}
    assert await found(client) == {"v-chisels", "v-saws"}


async def test_a_channel_taken_out_of_the_library_while_its_sync_runs_loses_the_sync_and_keeps_the_playlists_videos(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    gate = Gate()
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone")),
        fake_video("v-saws", "Saws", before_fetch=gate),
        fake_video("v-planes", "Planes"),
    ]
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-knives", "Knives", cues=said("Sharpen the knife on a fine stone"))
    )
    transcripts.playlists["PL-picks"] = FakePlaylist(
        "Sharpening picks", [("UC-rex", "v-knives"), ("UC-wright", "v-chisels")]
    )
    wright = await add_channel(client, "@woodbywright")
    playlist = await add_playlist(client, "PL-picks")
    await sync_playlist(client, playlist)

    await start_sync(client, wright["id"])
    await gate.wait_entered()
    behind = await start_playlist_sync(client, playlist["id"])
    deleted = await client.delete(f"/api/channels/{wright['id']}")
    gate.released.set()
    finished = await wait_for_syncs(client)

    assert deleted.status_code == 204
    # The Channel's Sync went as it left the Library, mid-fetch, and the Sync queued behind it ran.
    assert [(s["source_name"], s["status"]) for s in finished] == [("Sharpening picks", "done")] * 2
    assert finished[0]["id"] == behind["id"]
    assert "v-planes" not in fetched(transcripts)
    # The saws and the planes were in no Playlist; the chisels are, so they and their creator stay.
    assert stored(config) == dict.fromkeys(ROWS, 2) | {"storyboards": 0, "channels": 2}
    videos = await list_playlist_videos(client, playlist["id"])
    assert [(v["youtube_video_id"], v["channel_name"], v["stage"]) for v in videos] == [
        ("v-knives", "Rex Krueger", "done"),
        ("v-chisels", "Wood By Wright", "done"),
    ]
    assert await found(client) == {"v-knives", "v-chisels"}


async def test_a_channel_deleted_while_a_playlists_sync_fetches_its_video_leaves_that_sync_to_finish_it(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    gate = Gate()
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone"), before_fetch=gate)
    )
    transcripts.playlists["PL-picks"] = FakePlaylist("Sharpening picks", [("UC-wright", "v-chisels")])
    wright = await add_channel(client, "@woodbywright")
    playlist = await add_playlist(client, "PL-picks")

    await start_playlist_sync(client, playlist["id"])
    await gate.wait_entered()
    deleted = await client.delete(f"/api/channels/{wright['id']}")
    gate.released.set()
    [finished] = await wait_for_syncs(client)

    assert deleted.status_code == 204
    assert (finished["source_name"], finished["status"]) == ("Sharpening picks", "done")
    assert finished["completed_videos"] == 1
    assert (await client.get("/api/channels")).json() == []
    [video] = await list_playlist_videos(client, playlist["id"])
    assert (video["youtube_video_id"], video["channel_name"], video["stage"]) == ("v-chisels", "Wood By Wright", "done")
    assert await found(client) == {"v-chisels"}


async def test_a_playlist_deleted_while_a_channels_sync_fetches_its_video_leaves_the_video_to_the_channels_filters(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    gate = Gate()
    old = fake_video(
        "v-old",
        "Saws",
        published_on=date(2020, 1, 1),
        cues=said("Sharpen the saw on a fine stone"),
        failure=VideoUnavailable("YouTube refused the captions", permanent=False),
    )
    fake_channel(transcripts, "UC-wright").videos += [
        old,
        fake_video("v-mid", "Irons", published_on=date(2024, 6, 1), cues=said("Sharpen the iron on a fine stone")),
    ]
    transcripts.playlists["PL-picks"] = FakePlaylist("Picks", [("UC-wright", "v-old")])
    wright = await add_channel(client, "@woodbywright")
    await set_filters(client, wright, published_after="2024-01-01")
    playlist = await add_playlist(client, "PL-picks")
    # The Playlist includes the saws but could not fetch them, so the Channel's Sync is the one to try again.
    await sync_playlist(client, playlist)
    old.failure, old.before_fetch = None, gate

    await start_sync(client, wright["id"])
    await gate.wait_entered()
    deleted = await client.delete(f"/api/playlists/{playlist['id']}")
    gate.released.set()
    [finished] = await wait_for_syncs(client)

    assert deleted.status_code == 204
    assert (finished["source_name"], finished["status"]) == ("Wood By Wright", "done")
    videos = await list_videos(client, wright["id"])
    assert {title: (v["stage"], v["reason"]) for title, v in videos.items()} == {
        "Irons": ("done", None),
        "Saws": ("excluded", "Published before 2024-01-01, outside the Channel's filters"),
    }
    assert await found(client) == {"v-mid"}


async def test_a_playlist_deleted_while_a_channels_sync_has_its_video_part_way_leaves_the_video_excluded_not_done(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, embedder: FakeEmbedder
) -> None:
    gate = Gate()
    mid = fake_video(
        "v-mid",
        "Irons",
        published_on=date(2024, 6, 1),
        cues=said("Sharpen the iron on a fine stone"),
        failure=VideoUnavailable("YouTube refused the captions", permanent=False),
    )
    fake_channel(transcripts, "UC-wright").videos += [
        mid,
        fake_video("v-old", "Saws", published_on=date(2020, 1, 1), cues=said("Sharpen the saw on a fine stone")),
    ]
    transcripts.playlists["PL-picks"] = FakePlaylist("Picks", [("UC-wright", "v-old")])
    wright = await add_channel(client, "@woodbywright")
    await set_filters(client, wright, published_after="2024-01-01")
    # The Channel's Sync could not fetch the irons, so its next one takes them up first, ahead of the saws.
    await sync(client, wright)
    playlist = await add_playlist(client, "PL-picks")
    # The Playlist's Sync cut the saws into Segments and stopped short of embedding them.
    embedder.unavailable = "The GPU is out of memory"
    await start_playlist_sync(client, playlist["id"])
    await wait_for_syncs(client)
    embedder.unavailable = None
    mid.failure, mid.before_fetch = None, gate

    await start_sync(client, wright["id"])
    await gate.wait_entered()
    saws_part_way = stages(await list_videos(client, wright["id"]))["Saws"]
    deleted = await client.delete(f"/api/playlists/{playlist['id']}")
    gate.released.set()
    finished, *_ = await wait_for_syncs(client)
    left = await list_videos(client, wright["id"])
    # Widening the filters lifts the exclusion, and the Channel's next Sync is what indexes the saws.
    await set_filters(client, wright)
    await sync(client, wright)

    assert saws_part_way == "segmented"
    assert deleted.status_code == 204
    assert (finished["source_name"], finished["status"]) == ("Wood By Wright", "done")
    assert {title: (v["stage"], v["reason"]) for title, v in left.items()} == {
        "Irons": ("done", None),
        "Saws": ("excluded", "Published before 2024-01-01, outside the Channel's filters"),
    }
    assert stages(await list_videos(client, wright["id"])) == {"Irons": "done", "Saws": "done"}
    assert await found(client) == {"v-mid", "v-old"}
