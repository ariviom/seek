from datetime import date

import httpx
import pytest
from harness import (
    Json,
    add_channel,
    add_playlist,
    fake_channel,
    fake_video,
    fetched,
    list_videos,
    row_counts,
    said,
    sync,
    sync_playlist,
)

from seek.config import Config
from seek.fakes import FakePlaylist, FakeTranscriptSource
from seek.ports import VideoUnavailable


async def found(client: httpx.AsyncClient, **scope: object) -> set[str]:
    """The YouTube ids of the Videos a search for sharpening finds in the scope."""
    response = await client.post("/api/search", json={"query": "sharpen on a fine stone", **scope})
    assert response.status_code == 200, response.text
    return {result["youtube_video_id"] for result in response.json()}


async def set_filters(client: httpx.AsyncClient, channel: Json, **filters: object) -> None:
    unset = {"published_after": None, "published_before": None, "playlist_id": None, "most_recent": None}
    response = await client.patch(f"/api/channels/{channel['id']}", json={"filters": unset | filters})
    assert response.status_code == 200, response.text


def stages(videos: dict[str, Json]) -> dict[str, str]:
    return {title: v["stage"] for title, v in videos.items()}


@pytest.mark.parametrize(
    ("filters", "reason"),
    [
        ({"published_after": "2024-01-01"}, "Published before 2024-01-01, outside the Channel's filters"),
        ({"playlist_id": "PL-recent"}, "Not in playlist PL-recent, outside the Channel's filters"),
    ],
)
async def test_a_video_a_playlist_includes_is_searchable_though_its_channels_filters_exclude_it(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, filters: Json, reason: str
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-new", "Chisels", published_on=date(2025, 2, 1), cues=said("Sharpen the chisel on a fine stone")),
        fake_video("v-old", "Saws", published_on=date(2020, 1, 1), cues=said("Sharpen the saw on a fine stone")),
        fake_video("v-older", "Irons", published_on=date(2019, 1, 1), cues=said("Sharpen the iron on a fine stone")),
    ]
    transcripts.playlists["PL-recent"] = FakePlaylist("Recent", [("UC-wright", "v-new")])
    transcripts.playlists["PL-picks"] = FakePlaylist("Picks", [("UC-wright", "v-old")])
    wright = await add_channel(client, "@woodbywright")
    await set_filters(client, wright, **filters)
    await sync(client, wright)
    filtered = await list_videos(client, wright["id"])

    picks = await add_playlist(client, "PL-picks")
    await sync_playlist(client, picks)
    included = await list_videos(client, wright["id"])
    # The Channel's own Sync judges the Video again, and leaves it be.
    await sync(client, wright)

    assert stages(filtered) == {"Chisels": "done", "Saws": "excluded", "Irons": "excluded"}
    assert filtered["Saws"]["reason"] == reason
    assert stages(included) == {"Chisels": "done", "Saws": "done", "Irons": "excluded"}
    assert included["Saws"]["reason"] is None
    assert stages(await list_videos(client, wright["id"])) == stages(included)
    assert await found(client) == {"v-new", "v-old"}
    assert await found(client, playlist=picks["id"]) == {"v-old"}
    assert fetched(transcripts).count("v-old") == 1 and "v-older" not in fetched(transcripts)


async def test_a_channel_sync_ingests_a_video_a_playlist_includes_whatever_its_date_window(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    # Its date is only known once its details are fetched, and the Playlist's Sync could not fetch them.
    old = fake_video(
        "v-old",
        "Saws",
        published_on=date(2020, 1, 1),
        date_listed=False,
        cues=said("Sharpen the saw on a fine stone"),
        failure=VideoUnavailable("Premieres in 3 days", permanent=False),
    )
    fake_channel(transcripts, "UC-wright").videos.append(old)
    transcripts.playlists["PL-picks"] = FakePlaylist("Picks", [("UC-wright", "v-old")])
    wright = await add_channel(client, "@woodbywright")
    await set_filters(client, wright, published_after="2024-01-01")
    picks = await add_playlist(client, "PL-picks")
    await sync_playlist(client, picks)
    failed = await list_videos(client, wright["id"])

    old.failure = None
    await sync(client, wright)

    assert stages(failed) == {"Saws": "failed"}
    [saws] = (await list_videos(client, wright["id"])).values()
    assert (saws["stage"], saws["reason"], saws["published_on"]) == ("done", None, "2020-01-01")
    assert await found(client, channels=[wright["id"]]) == {"v-old"}


async def test_a_video_a_playlist_includes_takes_none_of_its_channels_most_recent_places(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    # The videos tab lists newest first.
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-1", "Newest", cues=said("Sharpen the chisel on a fine stone")),
        fake_video("v-2", "Second", cues=said("Sharpen the saw on a fine stone")),
        fake_video("v-3", "Third", cues=said("Sharpen the iron on a fine stone")),
        fake_video("v-4", "Oldest", cues=said("Sharpen the axe on a fine stone")),
    ]
    transcripts.playlists["PL-picks"] = FakePlaylist("Picks", [("UC-wright", "v-1"), ("UC-wright", "v-4")])
    wright = await add_channel(client, "@woodbywright")
    await set_filters(client, wright, most_recent=1)
    await sync(client, wright)
    newest_only = await list_videos(client, wright["id"])

    picks = await add_playlist(client, "PL-picks")
    await sync_playlist(client, picks)
    with_picks = stages(await list_videos(client, wright["id"]))
    await sync(client, wright)

    assert stages(newest_only) == {"Newest": "done", "Second": "excluded", "Third": "excluded", "Oldest": "excluded"}
    assert "1 most recent" in newest_only["Oldest"]["reason"]
    # The Playlist lifts the oldest's exclusion at once; the place the newest gives up is filled at the Channel's
    # next Sync, by its newest Video that no Playlist includes.
    assert with_picks == {"Newest": "done", "Second": "excluded", "Third": "excluded", "Oldest": "done"}
    assert stages(await list_videos(client, wright["id"])) == {
        "Newest": "done",
        "Second": "done",
        "Third": "excluded",
        "Oldest": "done",
    }
    assert await found(client) == {"v-1", "v-2", "v-4"}


async def test_a_video_that_leaves_its_last_playlist_goes_back_under_its_library_channels_date_window(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, config: Config
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-mid", "Irons", published_on=date(2024, 6, 1), cues=said("Sharpen the iron on a fine stone")),
        fake_video("v-old", "Saws", published_on=date(2020, 1, 1), cues=said("Sharpen the saw on a fine stone")),
    ]
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-knives", "Knives", cues=said("Sharpen the knife on a fine stone"))
    )
    transcripts.playlists["PL-picks"] = FakePlaylist(
        "Picks", [("UC-wright", "v-old"), ("UC-wright", "v-mid"), ("UC-rex", "v-knives")]
    )
    transcripts.playlists["PL-saws"] = FakePlaylist("Saws", [("UC-wright", "v-old"), ("UC-rex", "v-knives")])
    wright = await add_channel(client, "@woodbywright")
    await set_filters(client, wright, published_after="2024-01-01")
    picks, saws = await add_playlist(client, "PL-picks"), await add_playlist(client, "PL-saws")
    await sync_playlist(client, picks)
    await sync_playlist(client, saws)
    both = stages(await list_videos(client, wright["id"]))

    # Both of the Channel's Videos leave Picks, but Saws still includes the old one.
    transcripts.playlists["PL-picks"].entries[:] = [("UC-rex", "v-knives")]
    await sync_playlist(client, picks)
    in_saws = stages(await list_videos(client, wright["id"])), await found(client)
    transcripts.playlists["PL-saws"].entries.remove(("UC-wright", "v-old"))
    await sync_playlist(client, saws)

    assert both == {"Irons": "done", "Saws": "done"}
    assert in_saws == ({"Irons": "done", "Saws": "done"}, {"v-mid", "v-old", "v-knives"})
    videos = await list_videos(client, wright["id"])
    assert {title: (v["stage"], v["reason"]) for title, v in videos.items()} == {
        "Irons": ("done", None),
        "Saws": ("excluded", "Published before 2024-01-01, outside the Channel's filters"),
    }
    assert await found(client) == {"v-mid", "v-knives"}
    # Excluded as a Channel's Sync would: out of the search indexes, its Transcript kept.
    assert row_counts(config) == {
        "videos": 3,
        "transcripts": 3,
        "segments": 2,
        "segments_fts_docsize": 2,
        "segment_vectors": 2,
    }


async def test_a_video_that_leaves_its_last_playlist_meets_its_channels_most_recent_count_at_the_channels_next_sync(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-1", "Newest", cues=said("Sharpen the chisel on a fine stone")),
        fake_video("v-2", "Oldest", cues=said("Sharpen the saw on a fine stone")),
    ]
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-knives", "Knives", cues=said("Sharpen the knife on a fine stone"))
    )
    transcripts.playlists["PL-picks"] = FakePlaylist("Picks", [("UC-wright", "v-2"), ("UC-rex", "v-knives")])
    wright = await add_channel(client, "@woodbywright")
    await set_filters(client, wright, most_recent=1)
    picks = await add_playlist(client, "PL-picks")
    await sync_playlist(client, picks)
    await sync(client, wright)
    included = stages(await list_videos(client, wright["id"]))

    transcripts.playlists["PL-picks"].entries.remove(("UC-wright", "v-2"))
    await sync_playlist(client, picks)
    left = stages(await list_videos(client, wright["id"]))
    await sync(client, wright)

    assert included == {"Newest": "done", "Oldest": "done"}
    # Which Videos are the most recent takes the Channel's listing, so that rule waits for the Channel's Sync.
    assert left == {"Newest": "done", "Oldest": "done"}
    videos = await list_videos(client, wright["id"])
    assert stages(videos) == {"Newest": "done", "Oldest": "excluded"}
    assert "1 most recent" in videos["Oldest"]["reason"]


async def test_a_video_under_the_minimum_length_stays_excluded_though_a_playlist_includes_it(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-tip", "Quick tip", listed_duration=90, duration=90),
        # Its length is only known once its details are fetched.
        fake_video("v-minute", "Glue-up in a minute", listed_duration=None, duration=60),
    ]
    transcripts.playlists["PL-picks"] = FakePlaylist("Picks", [("UC-wright", "v-tip"), ("UC-wright", "v-minute")])
    wright = await add_channel(client, "@woodbywright")
    picks = await add_playlist(client, "PL-picks")
    await sync_playlist(client, picks)
    after_playlist = await list_videos(client, wright["id"])

    await sync(client, wright)

    short = "Shorter than the 120 second minimum"
    for videos in (after_playlist, await list_videos(client, wright["id"])):
        assert {title: (v["stage"], v["reason"]) for title, v in videos.items()} == {
            "Quick tip": ("excluded", short),
            "Glue-up in a minute": ("excluded", short),
        }
    assert fetched(transcripts) == ["v-minute"]
