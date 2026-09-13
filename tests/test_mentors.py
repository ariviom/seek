from pathlib import Path
from typing import Any

import httpx
from harness import running

from mentor.app import create_app
from mentor.config import Config
from mentor.youtube import YouTubeTranscriptSource

type Json = dict[str, Any]


async def add_mentor(client: httpx.AsyncClient, name: str, channel: str) -> Json:
    response = await client.post("/api/mentors", json={"name": name, "channel": channel})
    assert response.status_code == 201, response.text
    mentor: Json = response.json()
    return mentor


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
    app = create_app(config, YouTubeTranscriptSource(), static_dir=tmp_path / "no-bundle")

    async with running(app) as client:
        response = await client.post("/api/channels/resolve", json={"channel": "@woodbywright"})

    assert response.status_code == 503
    assert response.json()["detail"]


async def test_mentor_names_must_be_unique_and_non_blank(client: httpx.AsyncClient) -> None:
    await add_mentor(client, "Wood By Wright", "@woodbywright")

    duplicate = await client.post("/api/mentors", json={"name": "Wood By Wright", "channel": "@rexkrueger"})
    blank = await client.post("/api/mentors", json={"name": "   ", "channel": "@rexkrueger"})

    assert duplicate.status_code == 409
    assert blank.status_code == 422
    assert len((await client.get("/api/mentors")).json()) == 1
