from pathlib import Path

import httpx
from harness import (
    WRIGHT_AVATAR,
    add_channel,
    add_group,
    fake_channel,
    fake_video,
    running,
    start_channel_conversation,
    start_sync,
    wait_for_syncs,
)

from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from seek.ports import VideoUnavailable


async def listed_channels(client: httpx.AsyncClient) -> list[tuple[str, str, bool]]:
    response = await client.get("/api/channels")
    assert response.status_code == 200, response.text
    return [(c["youtube_channel_id"], c["name"], c["indexed"]) for c in response.json()]


async def test_resolving_a_channel_proposes_its_display_name(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/channels/resolve", json={"channel": "https://www.youtube.com/@woodbywright"})

    assert response.status_code == 200
    assert response.json() == {"youtube_channel_id": "UC-wright", "name": "Wood By Wright"}


async def test_resolving_an_unknown_channel_is_a_validation_error(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/channels/resolve", json={"channel": "@nobody-here"})

    assert response.status_code == 422
    assert "@nobody-here" in response.json()["detail"]


async def test_adding_a_channel_from_a_proposal_lists_it_indexed_under_its_display_name_or_the_given_one(
    client: httpx.AsyncClient,
) -> None:
    proposal = (await client.post("/api/channels/resolve", json={"channel": "@woodbywright"})).json()

    created = await add_channel(client, proposal["youtube_channel_id"])
    named = await add_channel(client, "@rexkrueger", "  Rex  ")

    assert (created["youtube_channel_id"], created["name"], created["indexed"]) == ("UC-wright", "Wood By Wright", True)
    assert named["name"] == "Rex"
    assert await listed_channels(client) == [("UC-rex", "Rex", True), ("UC-wright", "Wood By Wright", True)]
    assert (await client.get("/api/channels")).json() == [named, created]


async def test_renaming_a_channel_shows_in_its_groups_and_its_conversations(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")
    group = await add_group(client, "Woodworking", wright)
    conversation = await start_channel_conversation(client, wright["id"])

    response = await client.patch(f"/api/channels/{wright['id']}", json={"name": "  Rob Wright  "})

    assert response.status_code == 200
    assert response.json()["name"] == "Rob Wright"
    assert await listed_channels(client) == [("UC-wright", "Rob Wright", True)]
    [listed_group] = (await client.get("/api/groups")).json()
    assert (listed_group["id"], [c["name"] for c in listed_group["channels"]]) == (group["id"], ["Rob Wright"])
    reopened = (await client.get(f"/api/conversations/{conversation['id']}")).json()
    assert reopened["scope"] == {"kind": "channel", "id": wright["id"], "name": "Rob Wright"}


async def test_a_channel_cannot_be_added_twice(client: httpx.AsyncClient) -> None:
    await add_channel(client, "@woodbywright", "Paul Wright")

    again = await client.post("/api/channels", json={"channel": "UC-wright", "name": "Someone Else"})

    assert again.status_code == 409
    assert again.json()["detail"] == "The Channel 'Wood By Wright' is already added as 'Paul Wright'"
    assert await listed_channels(client) == [("UC-wright", "Paul Wright", True)]


async def test_marking_a_channel_not_indexed_keeps_it_listed(client: httpx.AsyncClient) -> None:
    await add_channel(client, "@woodbywright")
    vlog = await add_channel(client, "@wrightvlogs")

    response = await client.patch(f"/api/channels/{vlog['id']}", json={"indexed": False})

    assert response.status_code == 200
    assert await listed_channels(client) == [
        ("UC-wright", "Wood By Wright", True),
        ("UC-wright-vlog", "Wright Vlogs", False),
    ]


async def test_deleting_a_channel_frees_its_youtube_channel(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")

    response = await client.delete(f"/api/channels/{wright['id']}")
    listed = await listed_channels(client)
    readded = await add_channel(client, "@woodbywright", "Rob Wright")

    assert response.status_code == 204
    assert listed == []
    # Ids are never reused, so a queued Sync or a Conversation can't attach to the wrong Channel.
    assert readded["id"] != wright["id"]


async def test_unknown_channels_are_not_found(client: httpx.AsyncClient) -> None:
    responses = [
        await client.patch("/api/channels/999", json={"name": "Nobody"}),
        await client.patch("/api/channels/999", json={"indexed": False}),
        await client.delete("/api/channels/999"),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]


async def test_an_unavailable_youtube_source_is_reported_as_service_unavailable(
    config: Config, tmp_path: Path
) -> None:
    source = FakeTranscriptSource(unavailable="YouTube is rate limiting requests")
    app = create_app(config, source, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle")

    async with running(app) as client:
        response = await client.post("/api/channels/resolve", json={"channel": "@woodbywright"})

    assert response.status_code == 503
    assert response.json()["detail"] == "YouTube is rate limiting requests"


async def test_a_channel_keeps_the_avatar_youtube_offered_when_it_was_added(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    added = await add_channel(client, "@woodbywright")
    await add_channel(client, "@rexkrueger")

    listed = (await client.get("/api/channels")).json()

    assert added["avatar_url"] == WRIGHT_AVATAR
    # A Channel YouTube gave no avatar has none, and the UI draws its initials.
    assert [(c["name"], c["avatar_url"]) for c in listed] == [("Rex Krueger", None), ("Wood By Wright", WRIGHT_AVATAR)]
    assert [method for method, _ in transcripts.calls] == ["resolve_channel", "resolve_channel"]


async def test_unresolvable_channels_are_rejected(client: httpx.AsyncClient) -> None:
    await add_channel(client, "@woodbywright")

    create = await client.post("/api/channels", json={"channel": "@nobody-here"})
    too_long = await client.post("/api/channels/resolve", json={"channel": "@" + "x" * 600})
    blank = await client.post("/api/channels/resolve", json={"channel": "  "})

    assert [create.status_code, too_long.status_code, blank.status_code] == [422, 422, 422]
    assert await listed_channels(client) == [("UC-wright", "Wood By Wright", True)]


async def test_a_channel_can_be_indexed_again_and_only_takes_a_real_boolean(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")

    await client.patch(f"/api/channels/{wright['id']}", json={"indexed": False})
    reindexed = await client.patch(f"/api/channels/{wright['id']}", json={"indexed": True})
    loose = await client.patch(f"/api/channels/{wright['id']}", json={"indexed": "no"})

    assert reindexed.status_code == 200
    assert reindexed.json() == {
        "id": wright["id"],
        "youtube_channel_id": "UC-wright",
        "name": "Wood By Wright",
        "indexed": True,
        "filters": {"published_after": None, "published_before": None, "playlist_id": None, "most_recent": None},
        "check_every_hours": 24,
        "indexed_videos": 0,
        "failed_videos": 0,
        "excluded_videos": 0,
        "last_synced_at": None,
        "avatar_url": WRIGHT_AVATAR,
    }
    assert loose.status_code == 422


async def test_channel_names_must_be_non_blank_but_two_channels_may_share_one(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")

    blank = await client.post("/api/channels", json={"channel": "@rexkrueger", "name": "   "})
    rename_blank = await client.patch(f"/api/channels/{wright['id']}", json={"name": ""})
    same_name = await add_channel(client, "@rexkrueger", "wood by wright")

    assert [blank.status_code, rename_blank.status_code] == [422, 422]
    assert same_name["name"] == "wood by wright"
    assert await listed_channels(client) == [("UC-wright", "Wood By Wright", True), ("UC-rex", "wood by wright", True)]


async def test_channels_count_their_indexed_failed_and_excluded_videos_and_when_they_last_synced(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-ok", "Sharpening chisels"),
        fake_video("v-also", "Flattening a bench"),
        fake_video("v-members", "Members stream", failure=VideoUnavailable("Members-only video", permanent=True)),
        fake_video("v-tip", "Quick tip", listed_duration=60, duration=60),
    ]
    wright = await add_channel(client, "@woodbywright", "Paul Wright")
    await start_sync(client, wright["id"])
    [finished] = await wait_for_syncs(client)

    [channel] = (await client.get("/api/channels")).json()
    updated = (await client.patch(f"/api/channels/{wright['id']}", json={"indexed": True})).json()

    assert (channel["indexed_videos"], channel["failed_videos"], channel["excluded_videos"]) == (2, 1, 1)
    assert channel["last_synced_at"] == finished["finished_at"]
    assert updated == channel
