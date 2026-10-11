import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from harness import (
    Json,
    add_channel,
    add_group,
    done_message,
    new_group_conversation,
    send,
    start_channel_conversation,
    start_conversation,
    stream_events,
    take_out_of_library,
    woodworkers,
)

from seek.config import Config
from seek.fakes import FakeChatEngine, FakeTranscriptSource
from seek.ports import ChatDone, ChatEvent, ChatFailed, ChatRequest, PastMessage, TextDelta


async def get_conversation(client: httpx.AsyncClient, conversation_id: int) -> Json:
    response = await client.get(f"/api/conversations/{conversation_id}")
    assert response.status_code == 200, response.text
    conversation: Json = response.json()
    return conversation


async def list_conversations(client: httpx.AsyncClient, **params: int) -> list[Json]:
    response = await client.get("/api/conversations", params=params)
    assert response.status_code == 200, response.text
    listed: list[Json] = response.json()
    return listed


async def test_conversations_are_listed_newest_first_by_scope_and_reopen_with_their_messages(
    client: httpx.AsyncClient, engine: FakeChatEngine
) -> None:
    wright = await add_channel(client, "@woodbywright")
    rex = await add_channel(client, "@rexkrueger")
    woodworking = await add_group(client, "Woodworking", wright)
    leather = await add_group(client, "Leatherwork", rex)
    older = await start_conversation(client, woodworking["id"], model="opus")
    newer = await start_conversation(client, leather["id"])
    with_rex = await start_channel_conversation(client, rex["id"])
    unused = await start_conversation(client, woodworking["id"])
    await send(client, older["id"], "How do I   flatten a workbench top that has cupped badly over the winter in my damp garage?")
    await send(client, newer["id"], "Which thread for a sheath?")
    await send(client, with_rex["id"], "Which awl?")
    engine.script = [TextDelta("Hand plane it."), ChatDone("session-1")]
    await send(client, older["id"], "With what?")

    everything = await list_conversations(client)
    in_woodworking = await list_conversations(client, group_id=woodworking["id"])
    with_rex_only = await list_conversations(client, channel_id=rex["id"])
    both = await client.get("/api/conversations", params={"group_id": woodworking["id"], "channel_id": rex["id"]})
    reopened = await get_conversation(client, older["id"])

    # The most recently active first; a Conversation with no messages yet last.
    assert [(c["id"], c["title"], c["message_count"]) for c in everything] == [
        (older["id"], "How do I flatten a workbench top that has cupped badly over the winter in my da…", 4),
        (with_rex["id"], "Which awl?", 2),
        (newer["id"], "Which thread for a sheath?", 2),
        (unused["id"], "New Conversation", 0),
    ]
    assert [c["id"] for c in in_woodworking] == [older["id"], unused["id"]]
    assert [c["id"] for c in with_rex_only] == [with_rex["id"]]
    assert both.status_code == 422
    assert everything[0] | {"created_at": "", "last_message_at": ""} == {
        "id": older["id"],
        "scope": {"kind": "group", "id": woodworking["id"], "name": "Woodworking"},
        "model": "opus",
        "context": {"workspace": None, "web_access": False},
        "created_at": "",
        "title": "How do I flatten a workbench top that has cupped badly over the winter in my da…",
        "message_count": 4,
        "last_message_at": "",
        # This engine reports no usage, so the total is zero and says it is incomplete rather than exact.
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "complete": False},
    }
    assert everything[1]["scope"] == {"kind": "channel", "id": rex["id"], "name": "Rex Krueger"}
    assert [(m["role"], m["content"]) for m in reopened["messages"]] == [
        ("user", "How do I   flatten a workbench top that has cupped badly over the winter in my damp garage?"),
        ("assistant", "Nothing to say."),
        ("user", "With what?"),
        ("assistant", "Hand plane it."),
    ]
    assert (reopened["scope"], reopened["model"]) == (
        {"kind": "group", "id": woodworking["id"], "name": "Woodworking"},
        "opus",
    )
    assert (await client.get("/api/conversations/999")).status_code == 404


async def test_a_conversation_starts_with_a_channel_that_is_indexed_or_a_group_with_channels(
    client: httpx.AsyncClient,
) -> None:
    wright = await add_channel(client, "@woodbywright")
    vlog = await add_channel(client, "@wrightvlogs")
    await client.patch(f"/api/channels/{vlog['id']}", json={"indexed": False})
    empty = await add_group(client, "Empty")

    started = await start_channel_conversation(client, wright["id"], model="haiku")
    not_indexed = await client.post(f"/api/channels/{vlog['id']}/conversations", json={"model": None})
    empty_group = await client.post(f"/api/groups/{empty['id']}/conversations", json={"model": None})
    unknown = await client.post("/api/channels/999/conversations", json={"model": None})

    assert started | {"created_at": ""} == {
        "id": started["id"],
        "scope": {"kind": "channel", "id": wright["id"], "name": "Wood By Wright"},
        "model": "haiku",
        "context": {"workspace": None, "web_access": False},
        "created_at": "",
    }
    assert (not_indexed.status_code, not_indexed.json()) == (
        409,
        {"detail": "The Channel 'Wright Vlogs' is paused, so it can't answer"},
    )
    assert (empty_group.status_code, empty_group.json()) == (
        409,
        {"detail": "The Group 'Empty' has no Channels yet, so nothing can answer"},
    )
    assert unknown.status_code == 404


async def test_a_conversation_cannot_start_with_a_channel_outside_the_library(
    client: httpx.AsyncClient, config: Config
) -> None:
    wright = await add_channel(client, "@woodbywright")
    take_out_of_library(config, wright)

    refused = await client.post(f"/api/channels/{wright['id']}/conversations", json={"model": None})

    assert (refused.status_code, refused.json()) == (404, {"detail": f"Channel {wright['id']} not found"})
    assert (await client.get("/api/conversations")).json() == []


async def test_a_conversation_keeps_its_read_only_project_and_web_context(
    client: httpx.AsyncClient, engine: FakeChatEngine, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    group = await add_group(client, "Woodworking", await add_channel(client, "@woodbywright"))

    conversation = await start_conversation(
        client, group["id"], workspace=str(project / ".." / "project"), web_access=True
    )
    await send(client, conversation["id"], "Apply their advice here.")
    reopened = await get_conversation(client, conversation["id"])

    assert conversation["context"] == reopened["context"] == {
        "workspace": str(project.resolve()),
        "web_access": True,
    }
    [request] = engine.requests
    assert (request.workspace, request.web_access) == (project.resolve(), True)
    assert str(project.resolve()) in request.system_prompt
    assert "public web pages" in request.system_prompt


async def test_a_project_context_must_be_an_existing_absolute_directory(client: httpx.AsyncClient) -> None:
    group = await add_group(client, "Woodworking", await add_channel(client, "@woodbywright"))

    relative = await client.post(
        f"/api/groups/{group['id']}/conversations", json={"workspace": "project", "web_access": False}
    )
    missing = await client.post(
        f"/api/groups/{group['id']}/conversations", json={"workspace": "/no/such/seek-project"}
    )

    assert relative.status_code == 422 and "absolute" in relative.json()["detail"]
    assert missing.status_code == 422 and "cannot be opened" in missing.json()["detail"]


async def test_conversations_and_their_citations_outlive_their_channel_and_group_as_read_only(
    client: httpx.AsyncClient, engine: FakeChatEngine, transcripts: FakeTranscriptSource
) -> None:
    group, wright, _ = await woodworkers(client, transcripts)
    with_group = await start_conversation(client, group["id"])
    with_channel = await start_channel_conversation(client, wright["id"])
    engine.script = [TextDelta("Hone it: https://www.youtube.com/watch?v=v-wright&t=5s"), ChatDone("session-1")]
    [cited] = done_message(await send(client, with_group["id"], "How fine a stone?"))["citations"]
    engine.script = [TextDelta("Hone it: https://www.youtube.com/watch?v=v-wright&t=5s"), ChatDone("session-2")]
    await send(client, with_channel["id"], "How fine a stone?")

    await client.delete(f"/api/channels/{wright['id']}")
    await client.delete(f"/api/groups/{group['id']}")

    reopened = await get_conversation(client, with_group["id"])
    listed = {c["id"]: c for c in await list_conversations(client)}
    assert reopened["messages"][1]["citations"] == [cited]
    assert (cited["channel_id"], cited["channel_name"], cited["video_title"]) == (
        wright["id"],
        "Paul Wright",
        "Sharpening chisels",
    )
    assert listed[with_group["id"]]["scope"] == {"kind": "group", "id": None, "name": "Woodworking"}
    assert listed[with_channel["id"]]["scope"] == {"kind": "channel", "id": None, "name": "Paul Wright"}
    orphaned = await send(client, with_group["id"], "More?")
    assert (orphaned.status_code, orphaned.json()) == (
        409,
        {"detail": "The Group 'Woodworking' was deleted, so this Conversation is read-only"},
    )
    orphaned = await send(client, with_channel["id"], "More?")
    assert (orphaned.status_code, orphaned.json()) == (
        409,
        {"detail": "The Channel 'Paul Wright' was deleted, so this Conversation is read-only"},
    )


async def test_a_group_conversation_stays_open_when_a_member_channel_goes(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    group, wright, rex = await woodworkers(client, transcripts)
    await client.put(f"/api/groups/{group['id']}/members", json={"channel_ids": [wright["id"], rex["id"]]})
    conversation = await start_conversation(client, group["id"])

    await client.delete(f"/api/channels/{wright['id']}")

    assert (await send(client, conversation["id"], "Which stone?")).status_code == 200


async def test_a_conversation_whose_session_is_lost_carries_on_by_replaying_its_messages(
    client: httpx.AsyncClient, engine: FakeChatEngine
) -> None:
    conversation = await new_group_conversation(client)
    await send(client, conversation["id"], "Which stone?")

    async def respond(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        if request.resume_session_id == "session-1":
            yield ChatFailed("No conversation found with session ID: session-1", session_lost=True)
        else:
            yield TextDelta("Then 8000 grit.")
            yield ChatDone("session-2")

    engine.respond = respond

    response = await send(client, conversation["id"], "And then?")
    await send(client, conversation["id"], "Thanks")

    # The retry is invisible: no error, just the answer.
    assert [e["type"] for e in stream_events(response)] == ["text", "done"]
    lost, replayed, resumed = engine.requests[1:]
    assert (lost.resume_session_id, replayed.resume_session_id, resumed.resume_session_id) == (
        "session-1",
        None,
        "session-2",
    )
    assert replayed.history == [PastMessage("user", "Which stone?"), PastMessage("assistant", "Nothing to say.")]


async def test_a_turn_after_a_failed_first_one_replays_the_unanswered_question(
    client: httpx.AsyncClient, engine: FakeChatEngine
) -> None:
    conversation = await new_group_conversation(client)
    engine.script = [ChatFailed("Claude Code is not logged in")]
    await send(client, conversation["id"], "Which stone?")
    engine.script = [TextDelta("A fine one."), ChatDone("session-1")]

    await send(client, conversation["id"], "Hello?")

    retry = engine.requests[1]
    assert (retry.resume_session_id, retry.history) == (None, [PastMessage("user", "Which stone?")])


async def test_a_pinned_model_wins_while_an_unpinned_conversation_follows_the_setting(
    client: httpx.AsyncClient, engine: FakeChatEngine
) -> None:
    """A pin is a deliberate one-off; everything else follows the current preference, mid-thread included."""
    unpinned = await new_group_conversation(client)
    haiku = await start_conversation(client, unpinned["scope"]["id"], model="haiku")

    await send(client, unpinned["id"], "One?")
    await send(client, haiku["id"], "Two?")
    assert (await client.patch("/api/settings", json={"model": "deep"})).status_code == 200
    await send(client, unpinned["id"], "Three?")
    await send(client, haiku["id"], "Four?")

    # fast and deep are Claude CLI aliases on this engine; the pin is passed through untouched.
    assert [r.model for r in engine.requests] == ["sonnet", "haiku", "opus", "haiku"]
    assert (unpinned["model"], haiku["model"]) == (None, "haiku")


async def test_a_conversation_can_be_renamed(client: httpx.AsyncClient) -> None:
    conversation = await new_group_conversation(client)
    await send(client, conversation["id"], "Which stone?")

    renamed = await client.patch(f"/api/conversations/{conversation['id']}", json={"title": "  Sharpening  "})
    [listed] = await list_conversations(client)
    blank = await client.patch(f"/api/conversations/{conversation['id']}", json={"title": "   "})
    unknown = await client.patch("/api/conversations/999", json={"title": "Glue"})

    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["title"], renamed.json()["message_count"]) == ("Sharpening", 2)
    assert listed["title"] == "Sharpening"
    assert blank.status_code == 422
    assert unknown.status_code == 404


async def wait_for_request(engine: FakeChatEngine) -> None:
    async with asyncio.timeout(5):
        while not engine.requests:
            await asyncio.sleep(0.01)


async def test_a_conversation_can_be_deleted_but_not_while_answering(
    client: httpx.AsyncClient, engine: FakeChatEngine
) -> None:
    conversation = await new_group_conversation(client)
    kept = await start_conversation(client, conversation["scope"]["id"])
    release = asyncio.Event()

    async def respond(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        await release.wait()
        yield ChatDone("session-1")

    engine.respond = respond
    answering = asyncio.create_task(send(client, conversation["id"], "Which stone?"))
    await wait_for_request(engine)
    while_answering = await client.delete(f"/api/conversations/{conversation['id']}")
    release.set()
    assert (await answering).status_code == 200

    deleted = await client.delete(f"/api/conversations/{conversation['id']}")
    again = await client.delete(f"/api/conversations/{conversation['id']}")

    assert (while_answering.status_code, while_answering.json()) == (
        409,
        {"detail": "This Conversation is still answering; stop it first"},
    )
    assert deleted.status_code == 204
    assert again.status_code == 404
    assert [c["id"] for c in await list_conversations(client)] == [kept["id"]]
    assert (await client.get(f"/api/conversations/{conversation['id']}")).status_code == 404


async def test_stopping_a_turn_keeps_the_question_without_an_answer(
    client: httpx.AsyncClient, engine: FakeChatEngine
) -> None:
    conversation = await new_group_conversation(client)
    never = asyncio.Event()

    async def respond(request: ChatRequest) -> AsyncIterator[ChatEvent]:
        yield TextDelta("Half an ans")
        await never.wait()
        yield ChatDone("session-1")

    engine.respond = respond
    answering = asyncio.create_task(send(client, conversation["id"], "Which stone?"))
    await wait_for_request(engine)
    stopped = await client.delete(f"/api/conversations/{conversation['id']}/turn")
    response = await answering
    not_answering = await client.delete(f"/api/conversations/{conversation['id']}/turn")
    engine.respond = None
    again = await send(client, conversation["id"], "Which stone, then?")

    assert stopped.status_code == 204
    assert stream_events(response)[-1] == {"type": "error", "message": "Stopped before the answer finished"}
    assert not_answering.status_code == 404
    assert again.status_code == 200
    reopened = await get_conversation(client, conversation["id"])
    assert [(m["role"], m["content"]) for m in reopened["messages"]] == [
        ("user", "Which stone?"),
        ("user", "Which stone, then?"),
        ("assistant", "Nothing to say."),
    ]
