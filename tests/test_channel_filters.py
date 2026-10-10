from datetime import date

import httpx
from harness import (
    WRIGHT_AVATAR,
    Json,
    add_channel,
    fake_channel,
    fake_video,
    fetched,
    list_videos,
    query,
    row_counts,
    start_sync,
    wait_for_syncs,
)

from seek.config import Config
from seek.fakes import FakeTranscriptSource

NO_FILTERS: Json = {"published_after": None, "published_before": None, "playlist_id": None, "most_recent": None}


async def set_filters(client: httpx.AsyncClient, channel_id: int, **filters: object) -> Json:
    response = await client.patch(f"/api/channels/{channel_id}", json={"filters": NO_FILTERS | filters})
    assert response.status_code == 200, response.text
    channel: Json = response.json()
    return channel


async def sync(client: httpx.AsyncClient, channel_id: int) -> Json:
    await start_sync(client, channel_id)
    latest, *_ = await wait_for_syncs(client)
    return latest


def stages(videos: dict[str, Json]) -> dict[str, str]:
    return {title: v["stage"] for title, v in videos.items()}


async def test_channel_filters_are_editable_without_touching_indexed(client: httpx.AsyncClient) -> None:
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]

    await client.patch(f"/api/channels/{channel_id}", json={"indexed": False})
    filtered = await set_filters(
        client, channel_id, published_after="2023-01-01", published_before="2024-12-31", playlist_id="PL-joinery_1", most_recent=25
    )
    [listed] = (await client.get("/api/channels")).json()
    reindexed = await client.patch(f"/api/channels/{channel_id}", json={"indexed": True})
    cleared = await set_filters(client, channel_id)

    assert filtered == {
        "id": channel_id,
        "youtube_channel_id": "UC-wright",
        "name": "Wood By Wright",
        "indexed": False,
        "indexed_videos": 0,
        "failed_videos": 0,
        "excluded_videos": 0,
        "last_synced_at": None,
        "avatar_url": WRIGHT_AVATAR,
        "filters": {
            "published_after": "2023-01-01",
            "published_before": "2024-12-31",
            "playlist_id": "PL-joinery_1",
            "most_recent": 25,
        },
    }
    assert listed == filtered
    assert reindexed.json() == filtered | {"indexed": True}
    assert cleared == filtered | {"indexed": True, "filters": NO_FILTERS}


async def test_invalid_channel_filters_are_rejected(client: httpx.AsyncClient) -> None:
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]
    invalid: list[Json] = [
        {"published_after": "2024-06-01", "published_before": "2024-01-01"},
        {"published_after": "last spring"},
        {"most_recent": 0},
        {"most_recent": "10"},
        {"playlist_id": "https://www.youtube.com/playlist?listing=PL1"},
        {"playlist_id": ""},
    ]

    responses = [
        await client.patch(f"/api/channels/{channel_id}", json={"filters": NO_FILTERS | filters}) for filters in invalid
    ]
    unknown = await client.patch("/api/channels/999", json={"filters": NO_FILTERS})

    assert [r.status_code for r in responses] == [422] * len(invalid)
    assert unknown.status_code == 404
    [listed] = (await client.get("/api/channels")).json()
    assert listed["filters"] == NO_FILTERS
    # A playlist URL from the address bar gives its id.
    from_url = await set_filters(client, channel_id, playlist_id="https://www.youtube.com/playlist?list=PL1&si=x")
    assert from_url["filters"]["playlist_id"] == "PL1"


async def test_date_filters_exclude_videos_published_outside_the_range(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-2025", "Newest", published_on=date(2025, 2, 1)),
        fake_video("v-last-day", "Last day", published_on=date(2024, 12, 31)),
        fake_video("v-first-day", "First day", published_on=date(2023, 1, 1)),
        fake_video("v-2022", "Oldest", published_on=date(2022, 5, 5)),
        # Its date is only known once its details are fetched.
        fake_video("v-undated", "Undated old", published_on=date(2021, 1, 1), date_listed=False),
    ]
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]
    await set_filters(client, channel_id, published_after="2023-01-01", published_before="2024-12-31")

    finished = await sync(client, channel_id)
    videos = await list_videos(client, channel_id)

    assert finished["status"] == "done"
    assert stages(videos) == {
        "Newest": "excluded",
        "Last day": "done",
        "First day": "done",
        "Oldest": "excluded",
        "Undated old": "excluded",
    }
    assert "2024-12-31" in videos["Newest"]["reason"]
    assert "2023-01-01" in videos["Oldest"]["reason"]
    assert "2023-01-01" in videos["Undated old"]["reason"]
    assert videos["Undated old"]["failure_stage"] is None
    assert sorted(fetched(transcripts)) == ["v-first-day", "v-last-day", "v-undated"]


async def test_a_playlist_filter_keeps_only_the_channels_videos_in_that_playlist(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-dovetails", "Dovetails"),
        fake_video("v-vlog", "Shop vlog"),
        fake_video("v-mortise", "Mortise and tenon"),
    ]
    transcripts.playlists["PL-joinery"] = ["v-mortise", "v-someone-elses", "v-dovetails"]
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]

    await set_filters(client, channel_id, playlist_id="PL-joinery")
    finished = await sync(client, channel_id)
    videos = await list_videos(client, channel_id)
    await set_filters(client, channel_id, playlist_id="PL-missing")
    missing = await sync(client, channel_id)

    assert finished["status"] == "done"
    assert stages(videos) == {"Dovetails": "done", "Shop vlog": "excluded", "Mortise and tenon": "done"}
    assert "PL-joinery" in videos["Shop vlog"]["reason"]
    assert sorted(fetched(transcripts)) == ["v-dovetails", "v-mortise"]
    assert [r["youtube_video_id"] for r in query(config, "SELECT youtube_video_id FROM videos ORDER BY id")] == [
        "v-dovetails",
        "v-vlog",
        "v-mortise",
    ]
    assert missing["status"] == "failed"
    assert "PL-missing" in missing["error"]
    assert stages(await list_videos(client, channel_id)) == stages(videos)


async def test_most_recent_n_keeps_the_newest_eligible_videos_in_listing_order(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    # The videos tab lists newest first.
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-tip", "Quick tip", listed_duration=60, duration=60),
        fake_video("v-new", "Newest episode"),
        fake_video("v-mid", "Middle episode"),
        fake_video("v-old", "Old episode"),
    ]
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]
    await set_filters(client, channel_id, most_recent=2)

    finished = await sync(client, channel_id)
    videos = await list_videos(client, channel_id)

    assert finished["stage_counts"]["done"] == 2
    assert stages(videos) == {
        "Quick tip": "excluded",
        "Newest episode": "done",
        "Middle episode": "done",
        "Old episode": "excluded",
    }
    assert "120" in videos["Quick tip"]["reason"]
    assert "2 most recent" in videos["Old episode"]["reason"]
    assert fetched(transcripts) == ["v-new", "v-mid"]


async def test_every_sync_reapplies_the_current_filters_and_lifting_an_exclusion_loses_no_transcript(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    videos_tab = fake_channel(transcripts, "UC-wright").videos
    videos_tab += [fake_video("v-new", "New", published_on=date(2025, 1, 1)), fake_video("v-old", "Old", published_on=date(2020, 1, 1))]
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]

    await set_filters(client, channel_id, published_after="2024-01-01")
    narrow = await sync(client, channel_id)
    after_narrow = stages(await list_videos(client, channel_id))
    await set_filters(client, channel_id)
    widened = await sync(client, channel_id)
    after_widening = stages(await list_videos(client, channel_id))
    indexed_both = row_counts(config)
    await set_filters(client, channel_id, most_recent=1)
    narrowed_again = await sync(client, channel_id)
    after_narrowing = stages(await list_videos(client, channel_id))
    indexed_newest = row_counts(config)
    await set_filters(client, channel_id)
    await sync(client, channel_id)
    after_lifting = stages(await list_videos(client, channel_id))

    assert after_narrow == {"New": "done", "Old": "excluded"}
    assert (narrow["new_videos"], widened["new_videos"]) == (2, 0)
    assert after_widening == {"New": "done", "Old": "done"}
    assert fetched(transcripts) == ["v-new", "v-old"]
    assert indexed_both == {"videos": 2, "transcripts": 2, "segments": 2, "segments_fts_docsize": 2, "segment_vectors": 2}
    assert narrowed_again["stage_counts"]["excluded"] == 1
    assert after_narrowing == {"New": "done", "Old": "excluded"}
    # An excluded Video keeps its Transcript but leaves the search indexes.
    assert indexed_newest == {"videos": 2, "transcripts": 2, "segments": 1, "segments_fts_docsize": 1, "segment_vectors": 1}
    assert after_lifting == {"New": "done", "Old": "done"}
    assert fetched(transcripts) == ["v-new", "v-old"]
    assert row_counts(config) == indexed_both


async def test_most_recent_n_keeps_its_videos_when_a_listing_comes_back_short(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    videos_tab = fake_channel(transcripts, "UC-wright").videos
    videos_tab += [fake_video(f"v-{i}", f"Episode {4 - i}", published_on=date(2025 - i, 1, 1)) for i in range(4)]
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]
    await set_filters(client, channel_id, most_recent=2)
    await sync(client, channel_id)
    first = stages(await list_videos(client, channel_id))

    del videos_tab[1:]
    await sync(client, channel_id)
    videos_tab.clear()
    await sync(client, channel_id)

    assert first == {"Episode 4": "done", "Episode 3": "done", "Episode 2": "excluded", "Episode 1": "excluded"}
    assert stages(await list_videos(client, channel_id)) == first
    assert fetched(transcripts) == ["v-0", "v-1"]


async def test_most_recent_n_fills_up_in_one_sync_when_details_exclude_a_video_and_keeps_its_transcript(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video(f"v-{year}", f"From {year}", published_on=date(year, 1, 1), date_listed=False)
        for year in (2025, 2024, 2021, 2020)
    ]
    channel = await add_channel(client, "@woodbywright", "Wood By Wright")
    channel_id = channel["id"]

    await set_filters(client, channel_id, published_before="2022-06-01", most_recent=2)
    filtered = await sync(client, channel_id)
    after_filtered = stages(await list_videos(client, channel_id))
    transcripts_kept = row_counts(config)["transcripts"]
    await set_filters(client, channel_id, most_recent=2)
    await sync(client, channel_id)

    assert filtered["stage_counts"]["done"] == 2
    assert after_filtered == {"From 2025": "excluded", "From 2024": "excluded", "From 2021": "done", "From 2020": "done"}
    assert transcripts_kept == 4
    assert stages(await list_videos(client, channel_id)) == {
        "From 2025": "done",
        "From 2024": "done",
        "From 2021": "excluded",
        "From 2020": "excluded",
    }
    assert sorted(fetched(transcripts)) == ["v-2020", "v-2021", "v-2024", "v-2025"]
