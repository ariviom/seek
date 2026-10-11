import httpx
from harness import Json, add_channel, add_group, take_out_of_library

from seek.config import Config


async def set_members(client: httpx.AsyncClient, group: Json, *channels: Json) -> httpx.Response:
    channel_ids = [c["id"] for c in channels]
    return await client.put(f"/api/groups/{group['id']}/members", json={"channel_ids": channel_ids})


async def memberships(client: httpx.AsyncClient) -> dict[str, list[str]]:
    groups = (await client.get("/api/groups")).json()
    return {g["name"]: [c["name"] for c in g["channels"]] for g in groups}


async def test_a_new_group_is_listed_with_no_channels(client: httpx.AsyncClient) -> None:
    created = await add_group(client, "  Woodworking  ")

    assert created == {"id": created["id"], "name": "Woodworking", "channels": []}
    assert (await client.get("/api/groups")).json() == [created]


async def test_setting_members_replaces_them(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")
    rex = await add_channel(client, "@rexkrueger")
    group = await add_group(client, "Woodworking")

    first = await set_members(client, group, wright, rex)
    second = await set_members(client, group, rex)

    assert first.status_code == 200
    assert [c["name"] for c in first.json()["channels"]] == ["Rex Krueger", "Wood By Wright"]
    assert second.json() == {
        "id": group["id"],
        "name": "Woodworking",
        "channels": [{"id": rex["id"], "name": "Rex Krueger"}],
    }
    assert await memberships(client) == {"Woodworking": ["Rex Krueger"]}


async def test_a_channel_can_belong_to_several_groups(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")
    rex = await add_channel(client, "@rexkrueger")
    woodworking = await add_group(client, "Woodworking")
    tools = await add_group(client, "Hand tools")

    await set_members(client, woodworking, wright, rex)
    await set_members(client, tools, rex)

    assert await memberships(client) == {
        "Hand tools": ["Rex Krueger"],
        "Woodworking": ["Rex Krueger", "Wood By Wright"],
    }


async def test_deleting_a_channel_removes_it_from_every_group(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")
    rex = await add_channel(client, "@rexkrueger")
    woodworking = await add_group(client, "Woodworking")
    tools = await add_group(client, "Hand tools")
    await set_members(client, woodworking, wright, rex)
    await set_members(client, tools, rex)

    await client.delete(f"/api/channels/{rex['id']}")

    assert await memberships(client) == {"Hand tools": [], "Woodworking": ["Wood By Wright"]}


async def test_renaming_a_channel_shows_in_its_groups(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")
    group = await add_group(client, "Woodworking")
    await set_members(client, group, wright)

    await client.patch(f"/api/channels/{wright['id']}", json={"name": "Rob Wright"})

    assert await memberships(client) == {"Woodworking": ["Rob Wright"]}


async def test_renaming_a_group_keeps_its_members(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")
    group = await add_group(client, "Woodworking")
    await set_members(client, group, wright)

    response = await client.patch(f"/api/groups/{group['id']}", json={"name": "Woodworkers"})

    assert response.status_code == 200
    assert response.json()["name"] == "Woodworkers"
    assert await memberships(client) == {"Woodworkers": ["Wood By Wright"]}


async def test_deleting_a_group_keeps_its_channels_and_their_other_groups(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")
    woodworking = await add_group(client, "Woodworking")
    tools = await add_group(client, "Hand tools")
    await set_members(client, woodworking, wright)
    await set_members(client, tools, wright)

    response = await client.delete(f"/api/groups/{tools['id']}")
    recreated = await add_group(client, "Hand tools")

    assert response.status_code == 204
    assert [c["name"] for c in (await client.get("/api/channels")).json()] == ["Wood By Wright"]
    assert recreated["id"] != tools["id"]
    assert await memberships(client) == {"Hand tools": [], "Woodworking": ["Wood By Wright"]}


async def test_a_group_can_be_emptied(client: httpx.AsyncClient) -> None:
    rex = await add_channel(client, "@rexkrueger")
    group = await add_group(client, "Woodworking")
    await set_members(client, group, rex)

    response = await set_members(client, group)

    assert response.status_code == 200
    assert await memberships(client) == {"Woodworking": []}


async def test_membership_survives_a_channel_no_longer_being_indexed(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")
    group = await add_group(client, "Woodworking")
    await set_members(client, group, wright)

    await client.patch(f"/api/channels/{wright['id']}", json={"indexed": False})

    assert await memberships(client) == {"Woodworking": ["Wood By Wright"]}


async def test_group_names_must_be_unique_ignoring_case_and_non_blank(client: httpx.AsyncClient) -> None:
    await add_group(client, "Woodworking")
    tools = await add_group(client, "Hand tools")

    duplicate = await client.post("/api/groups", json={"name": "WOODWORKING"})
    blank = await client.post("/api/groups", json={"name": "  "})
    rename_duplicate = await client.patch(f"/api/groups/{tools['id']}", json={"name": "woodworking"})
    rename_blank = await client.patch(f"/api/groups/{tools['id']}", json={"name": ""})
    rename_same = await client.patch(f"/api/groups/{tools['id']}", json={"name": "Hand Tools"})

    assert [duplicate.status_code, blank.status_code] == [409, 422]
    assert "Woodworking" in duplicate.json()["detail"]
    assert [rename_duplicate.status_code, rename_blank.status_code, rename_same.status_code] == [409, 422, 200]
    assert await memberships(client) == {"Hand Tools": [], "Woodworking": []}


async def test_a_group_may_share_a_name_with_a_channel(client: httpx.AsyncClient) -> None:
    await add_channel(client, "@rexkrueger")

    await add_group(client, "Rex Krueger")


async def test_repeated_channel_ids_count_once(client: httpx.AsyncClient) -> None:
    rex = await add_channel(client, "@rexkrueger")
    group = await add_group(client, "Woodworking")

    response = await set_members(client, group, rex, rex)

    assert response.status_code == 200
    assert await memberships(client) == {"Woodworking": ["Rex Krueger"]}


async def test_members_must_be_existing_channels_and_nothing_changes_otherwise(client: httpx.AsyncClient) -> None:
    rex = await add_channel(client, "@rexkrueger")
    wright = await add_channel(client, "@woodbywright")
    group = await add_group(client, "Woodworking")
    await set_members(client, group, rex)
    url = f"/api/groups/{group['id']}/members"

    unknown = await client.put(url, json={"channel_ids": [wright["id"], 999]})
    out_of_range = await client.put(url, json={"channel_ids": [2**70]})
    loose = [await client.put(url, json={"channel_ids": [value]}) for value in [str(wright["id"]), True, 1.5]]

    assert unknown.status_code == 404
    assert "999" in unknown.json()["detail"]
    assert out_of_range.status_code == 404
    assert [r.status_code for r in loose] == [422, 422, 422]
    assert await memberships(client) == {"Woodworking": ["Rex Krueger"]}


async def test_a_channel_outside_the_library_cannot_be_made_a_member(client: httpx.AsyncClient, config: Config) -> None:
    rex = await add_channel(client, "@rexkrueger")
    wright = await add_channel(client, "@woodbywright")
    group = await add_group(client, "Woodworking")
    await set_members(client, group, rex)
    take_out_of_library(config, wright)

    refused = await set_members(client, group, rex, wright)

    assert (refused.status_code, refused.json()) == (404, {"detail": f"Channel {wright['id']} not found"})
    assert await memberships(client) == {"Woodworking": ["Rex Krueger"]}


async def test_unknown_groups_are_not_found(client: httpx.AsyncClient) -> None:
    responses = [
        await client.patch("/api/groups/999", json={"name": "Nobody"}),
        await client.delete("/api/groups/999"),
        await client.put("/api/groups/999/members", json={"channel_ids": []}),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
