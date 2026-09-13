import httpx
from harness import Json, add_mentor


async def add_group(client: httpx.AsyncClient, name: str) -> Json:
    response = await client.post("/api/groups", json={"name": name})
    assert response.status_code == 201, response.text
    group: Json = response.json()
    return group


async def set_members(client: httpx.AsyncClient, group: Json, *mentors: Json) -> httpx.Response:
    mentor_ids = [m["id"] for m in mentors]
    return await client.put(f"/api/groups/{group['id']}/members", json={"mentor_ids": mentor_ids})


async def memberships(client: httpx.AsyncClient) -> dict[str, list[str]]:
    groups = (await client.get("/api/groups")).json()
    return {g["name"]: [m["name"] for m in g["mentors"]] for g in groups}


async def test_a_new_group_is_listed_with_no_mentors(client: httpx.AsyncClient) -> None:
    created = await add_group(client, "  Woodworking  ")

    assert created == {"id": created["id"], "name": "Woodworking", "mentors": []}
    assert (await client.get("/api/groups")).json() == [created]


async def test_setting_members_replaces_them(client: httpx.AsyncClient) -> None:
    wright = await add_mentor(client, "Wood By Wright", "@woodbywright")
    rex = await add_mentor(client, "Rex Krueger", "@rexkrueger")
    group = await add_group(client, "Woodworking")

    first = await set_members(client, group, wright, rex)
    second = await set_members(client, group, rex)

    assert first.status_code == 200
    assert [m["name"] for m in first.json()["mentors"]] == ["Rex Krueger", "Wood By Wright"]
    assert second.json() == {
        "id": group["id"],
        "name": "Woodworking",
        "mentors": [{"id": rex["id"], "name": "Rex Krueger"}],
    }
    assert await memberships(client) == {"Woodworking": ["Rex Krueger"]}


async def test_a_mentor_can_belong_to_several_groups(client: httpx.AsyncClient) -> None:
    wright = await add_mentor(client, "Wood By Wright", "@woodbywright")
    rex = await add_mentor(client, "Rex Krueger", "@rexkrueger")
    woodworking = await add_group(client, "Woodworking")
    tools = await add_group(client, "Hand tools")

    await set_members(client, woodworking, wright, rex)
    await set_members(client, tools, rex)

    assert await memberships(client) == {
        "Hand tools": ["Rex Krueger"],
        "Woodworking": ["Rex Krueger", "Wood By Wright"],
    }


async def test_deleting_a_mentor_removes_it_from_every_group(client: httpx.AsyncClient) -> None:
    wright = await add_mentor(client, "Wood By Wright", "@woodbywright")
    rex = await add_mentor(client, "Rex Krueger", "@rexkrueger")
    woodworking = await add_group(client, "Woodworking")
    tools = await add_group(client, "Hand tools")
    await set_members(client, woodworking, wright, rex)
    await set_members(client, tools, rex)

    await client.delete(f"/api/mentors/{rex['id']}")

    assert await memberships(client) == {"Hand tools": [], "Woodworking": ["Wood By Wright"]}


async def test_renaming_a_mentor_shows_in_its_groups(client: httpx.AsyncClient) -> None:
    wright = await add_mentor(client, "Wood By Wright", "@woodbywright")
    group = await add_group(client, "Woodworking")
    await set_members(client, group, wright)

    await client.patch(f"/api/mentors/{wright['id']}", json={"name": "Rob Wright"})

    assert await memberships(client) == {"Woodworking": ["Rob Wright"]}


async def test_renaming_a_group_keeps_its_members(client: httpx.AsyncClient) -> None:
    wright = await add_mentor(client, "Wood By Wright", "@woodbywright")
    group = await add_group(client, "Woodworking")
    await set_members(client, group, wright)

    response = await client.patch(f"/api/groups/{group['id']}", json={"name": "Woodworkers"})

    assert response.status_code == 200
    assert response.json()["name"] == "Woodworkers"
    assert await memberships(client) == {"Woodworkers": ["Wood By Wright"]}


async def test_deleting_a_group_keeps_its_mentors_and_their_other_groups(client: httpx.AsyncClient) -> None:
    wright = await add_mentor(client, "Wood By Wright", "@woodbywright")
    woodworking = await add_group(client, "Woodworking")
    tools = await add_group(client, "Hand tools")
    await set_members(client, woodworking, wright)
    await set_members(client, tools, wright)

    response = await client.delete(f"/api/groups/{tools['id']}")
    recreated = await add_group(client, "Hand tools")

    assert response.status_code == 204
    assert [m["name"] for m in (await client.get("/api/mentors")).json()] == ["Wood By Wright"]
    assert recreated["id"] != tools["id"]
    assert await memberships(client) == {"Hand tools": [], "Woodworking": ["Wood By Wright"]}


async def test_a_group_can_be_emptied(client: httpx.AsyncClient) -> None:
    rex = await add_mentor(client, "Rex Krueger", "@rexkrueger")
    group = await add_group(client, "Woodworking")
    await set_members(client, group, rex)

    response = await set_members(client, group)

    assert response.status_code == 200
    assert await memberships(client) == {"Woodworking": []}


async def test_membership_is_by_mentor_whatever_happens_to_its_channels(client: httpx.AsyncClient) -> None:
    wright = await add_mentor(client, "Wood By Wright", "@woodbywright")
    vlog = (await client.post(f"/api/mentors/{wright['id']}/channels", json={"channel": "@wrightvlogs"})).json()
    group = await add_group(client, "Woodworking")
    await set_members(client, group, wright)

    await client.patch(f"/api/channels/{wright['channels'][0]['id']}", json={"indexed": False})
    await client.delete(f"/api/channels/{vlog['id']}")

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


async def test_a_group_may_share_a_name_with_a_mentor(client: httpx.AsyncClient) -> None:
    await add_mentor(client, "Rex Krueger", "@rexkrueger")

    await add_group(client, "Rex Krueger")


async def test_repeated_mentor_ids_count_once(client: httpx.AsyncClient) -> None:
    rex = await add_mentor(client, "Rex Krueger", "@rexkrueger")
    group = await add_group(client, "Woodworking")

    response = await set_members(client, group, rex, rex)

    assert response.status_code == 200
    assert await memberships(client) == {"Woodworking": ["Rex Krueger"]}


async def test_members_must_be_existing_mentors_and_nothing_changes_otherwise(client: httpx.AsyncClient) -> None:
    rex = await add_mentor(client, "Rex Krueger", "@rexkrueger")
    wright = await add_mentor(client, "Wood By Wright", "@woodbywright")
    group = await add_group(client, "Woodworking")
    await set_members(client, group, rex)
    url = f"/api/groups/{group['id']}/members"

    unknown = await client.put(url, json={"mentor_ids": [wright["id"], 999]})
    out_of_range = await client.put(url, json={"mentor_ids": [2**70]})
    loose = [await client.put(url, json={"mentor_ids": [value]}) for value in [str(wright["id"]), True, 1.5]]

    assert unknown.status_code == 404
    assert "999" in unknown.json()["detail"]
    assert out_of_range.status_code == 404
    assert [r.status_code for r in loose] == [422, 422, 422]
    assert await memberships(client) == {"Woodworking": ["Rex Krueger"]}


async def test_unknown_groups_are_not_found(client: httpx.AsyncClient) -> None:
    responses = [
        await client.patch("/api/groups/999", json={"name": "Nobody"}),
        await client.delete("/api/groups/999"),
        await client.put("/api/groups/999/members", json={"mentor_ids": []}),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
