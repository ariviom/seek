import sqlite3
from pathlib import Path

import httpx
import pytest
from harness import add_mentor, running

from mentor.app import create_app
from mentor.config import Config
from mentor.fakes import FakeEmbedder, FakeTranscriptSource

async def test_resolving_a_channel_proposes_its_display_name_as_the_mentor_name(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/api/channels/resolve", json={"channel": "https://www.youtube.com/@woodbywright"})

    assert response.status_code == 200
    assert response.json() == {"youtube_channel_id": "UC-wright", "name": "Wood By Wright"}


async def test_resolving_an_unknown_channel_is_a_validation_error(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/channels/resolve", json={"channel": "@nobody-here"})

    assert response.status_code == 422
    assert "@nobody-here" in response.json()["detail"]


async def test_creating_a_mentor_from_a_proposal_lists_it_with_its_indexed_channel(
    client: httpx.AsyncClient,
) -> None:
    proposal = (await client.post("/api/channels/resolve", json={"channel": "@woodbywright"})).json()

    created = await add_mentor(client, proposal["name"], proposal["youtube_channel_id"])
    listed = (await client.get("/api/mentors")).json()

    assert created["name"] == "Wood By Wright"
    assert [(c["youtube_channel_id"], c["name"], c["indexed"]) for c in created["channels"]] == [
        ("UC-wright", "Wood By Wright", True)
    ]
    assert listed == [created]


async def test_renaming_a_mentor(client: httpx.AsyncClient) -> None:
    mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")

    response = await client.patch(f"/api/mentors/{mentor['id']}", json={"name": "  Rob Wright  "})

    assert response.status_code == 200
    assert response.json()["name"] == "Rob Wright"
    assert [m["name"] for m in (await client.get("/api/mentors")).json()] == ["Rob Wright"]


async def test_attaching_a_second_channel_makes_one_mentor_with_both(client: httpx.AsyncClient) -> None:
    mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")

    response = await client.post(f"/api/mentors/{mentor['id']}/channels", json={"channel": "@wrightvlogs"})

    assert response.status_code == 201
    [listed] = (await client.get("/api/mentors")).json()
    assert [c["name"] for c in listed["channels"]] == ["Wood By Wright", "Wright Vlogs"]


async def test_a_channel_cannot_belong_to_two_mentors(client: httpx.AsyncClient) -> None:
    await add_mentor(client, "Wood By Wright", "@woodbywright")
    rex = await add_mentor(client, "Rex Krueger", "@rexkrueger")

    attach = await client.post(f"/api/mentors/{rex['id']}/channels", json={"channel": "@woodbywright"})
    create = await client.post("/api/mentors", json={"name": "Someone Else", "channel": "UC-wright"})

    assert attach.status_code == 409
    assert "Wood By Wright" in attach.json()["detail"]
    assert create.status_code == 409
    assert [m["name"] for m in (await client.get("/api/mentors")).json()] == ["Rex Krueger", "Wood By Wright"]


async def test_marking_a_channel_not_indexed_keeps_it_on_the_mentor(client: httpx.AsyncClient) -> None:
    mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
    vlog = (await client.post(f"/api/mentors/{mentor['id']}/channels", json={"channel": "@wrightvlogs"})).json()

    response = await client.patch(f"/api/channels/{vlog['id']}", json={"indexed": False})

    assert response.status_code == 200
    [listed] = (await client.get("/api/mentors")).json()
    assert [(c["name"], c["indexed"]) for c in listed["channels"]] == [
        ("Wood By Wright", True),
        ("Wright Vlogs", False),
    ]


async def test_detaching_a_channel_but_never_the_last_one(client: httpx.AsyncClient) -> None:
    mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
    vlog = (await client.post(f"/api/mentors/{mentor['id']}/channels", json={"channel": "@wrightvlogs"})).json()
    main_channel_id = mentor["channels"][0]["id"]

    detach = await client.delete(f"/api/channels/{vlog['id']}")
    detach_last = await client.delete(f"/api/channels/{main_channel_id}")

    assert detach.status_code == 204
    assert detach_last.status_code == 409
    [listed] = (await client.get("/api/mentors")).json()
    assert [c["name"] for c in listed["channels"]] == ["Wood By Wright"]


async def test_deleting_a_mentor_frees_its_channels(client: httpx.AsyncClient) -> None:
    mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")

    response = await client.delete(f"/api/mentors/{mentor['id']}")

    assert response.status_code == 204
    assert (await client.get("/api/mentors")).json() == []
    await add_mentor(client, "Rob Wright", "@woodbywright")


async def test_unknown_mentors_and_channels_are_not_found(client: httpx.AsyncClient) -> None:
    responses = [
        await client.patch("/api/mentors/999", json={"name": "Nobody"}),
        await client.delete("/api/mentors/999"),
        await client.post("/api/mentors/999/channels", json={"channel": "@rexkrueger"}),
        await client.patch("/api/channels/999", json={"indexed": False}),
        await client.delete("/api/channels/999"),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404, 404, 404]


async def test_an_unavailable_youtube_source_is_reported_as_service_unavailable(
    config: Config, tmp_path: Path
) -> None:
    source = FakeTranscriptSource(unavailable="YouTube is rate limiting requests")
    app = create_app(config, source, FakeEmbedder(), static_dir=tmp_path / "no-bundle")

    async with running(app) as client:
        response = await client.post("/api/channels/resolve", json={"channel": "@woodbywright"})

    assert response.status_code == 503
    assert response.json()["detail"] == "YouTube is rate limiting requests"


async def test_unresolvable_channels_are_rejected_when_creating_or_attaching(client: httpx.AsyncClient) -> None:
    mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")

    create = await client.post("/api/mentors", json={"name": "Nobody", "channel": "@nobody-here"})
    attach = await client.post(f"/api/mentors/{mentor['id']}/channels", json={"channel": "@nobody-here"})
    too_long = await client.post("/api/channels/resolve", json={"channel": "@" + "x" * 600})
    blank = await client.post("/api/channels/resolve", json={"channel": "  "})

    assert [create.status_code, attach.status_code, too_long.status_code, blank.status_code] == [422, 422, 422, 422]
    assert [m["name"] for m in (await client.get("/api/mentors")).json()] == ["Wood By Wright"]


async def test_reattaching_a_mentors_own_channel_says_it_is_already_attached(client: httpx.AsyncClient) -> None:
    mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")

    response = await client.post(f"/api/mentors/{mentor['id']}/channels", json={"channel": "@woodbywright"})

    assert response.status_code == 409
    assert "already attached" in response.json()["detail"]


async def test_a_channel_can_be_indexed_again_and_only_takes_a_real_boolean(client: httpx.AsyncClient) -> None:
    mentor = await add_mentor(client, "Wood By Wright", "@woodbywright")
    channel_id = mentor["channels"][0]["id"]

    await client.patch(f"/api/channels/{channel_id}", json={"indexed": False})
    reindexed = await client.patch(f"/api/channels/{channel_id}", json={"indexed": True})
    loose = await client.patch(f"/api/channels/{channel_id}", json={"indexed": "no"})

    assert reindexed.status_code == 200
    assert reindexed.json() == {
        "id": channel_id,
        "youtube_channel_id": "UC-wright",
        "name": "Wood By Wright",
        "indexed": True,
        "filters": {"published_after": None, "published_before": None, "playlist_id": None, "most_recent": None},
    }
    assert loose.status_code == 422


async def test_mentor_names_must_be_unique_ignoring_case_and_non_blank(client: httpx.AsyncClient) -> None:
    await add_mentor(client, "Wood By Wright", "@woodbywright")
    rex = await add_mentor(client, "Rex Krueger", "@rexkrueger")

    duplicate = await client.post("/api/mentors", json={"name": "wood by wright", "channel": "@wrightvlogs"})
    blank = await client.post("/api/mentors", json={"name": "   ", "channel": "@wrightvlogs"})
    rename_duplicate = await client.patch(f"/api/mentors/{rex['id']}", json={"name": "WOOD BY WRIGHT"})
    rename_blank = await client.patch(f"/api/mentors/{rex['id']}", json={"name": ""})

    assert [duplicate.status_code, blank.status_code] == [409, 422]
    assert [rename_duplicate.status_code, rename_blank.status_code] == [409, 422]
    assert [m["name"] for m in (await client.get("/api/mentors")).json()] == ["Rex Krueger", "Wood By Wright"]


async def test_server_refuses_a_knowledge_base_from_a_newer_mentor(config: Config, tmp_path: Path) -> None:
    config.data_dir.mkdir(parents=True)
    conn = sqlite3.connect(config.database_path)
    conn.execute("PRAGMA user_version = 999")
    conn.close()
    app = create_app(config, FakeTranscriptSource(), FakeEmbedder(), static_dir=tmp_path / "no-bundle")

    with pytest.raises(RuntimeError, match="newer"):
        async with running(app):
            pass
