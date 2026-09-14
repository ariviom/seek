import asyncio
from collections.abc import AsyncIterator

import httpx
from harness import (
    Json,
    done_message,
    new_group_conversation,
    send,
    start_conversation,
    stream_events,
    woodworkers,
)

from mentor.fakes import FakeChatEngine, FakeTranscriptSource
from mentor.ports import ChatDone, ChatEvent, ChatFailed, ChatRequest, PastMessage, TextDelta


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


async def test_conversations_are_listed_newest_first_and_reopen_with_their_messages(
    client: httpx.AsyncClient, engine: FakeChatEngine
) -> None:
    woodworking = (await client.post("/api/groups", json={"name": "Woodworking"})).json()
    leather = (await client.post("/api/groups", json={"name": "Leatherwork"})).json()
    older = await start_conversation(client, woodworking["id"], model="opus")
    newer = await start_conversation(client, leather["id"])
    unused = await start_conversation(client, woodworking["id"])
    await send(client, older["id"], "How do I   flatten a workbench top that has cupped badly over the winter in my damp garage?")
    await send(client, newer["id"], "Which thread for a sheath?")
    engine.script = [TextDelta("Hand plane it."), ChatDone("session-1")]
    await send(client, older["id"], "With what?")

    everything = await list_conversations(client)
    in_woodworking = await list_conversations(client, group_id=woodworking["id"])
    reopened = await get_conversation(client, older["id"])

    # The most recently active first; a Conversation with no messages yet last.
    assert [(c["id"], c["title"], c["message_count"]) for c in everything] == [
        (older["id"], "How do I flatten a workbench top that has cupped badly over the winter in my da…", 4),
        (newer["id"], "Which thread for a sheath?", 2),
        (unused["id"], "New Conversation", 0),
    ]
    assert [c["id"] for c in in_woodworking] == [older["id"], unused["id"]]
    assert everything[0] | {"created_at": "", "last_message_at": ""} == {
        "id": older["id"],
        "group_id": woodworking["id"],
        "group_name": "Woodworking",
        "model": "opus",
        "created_at": "",
        "title": "How do I flatten a workbench top that has cupped badly over the winter in my da…",
        "message_count": 4,
        "last_message_at": "",
    }
    assert [(m["role"], m["content"]) for m in reopened["messages"]] == [
        ("user", "How do I   flatten a workbench top that has cupped badly over the winter in my damp garage?"),
        ("assistant", "Nothing to say."),
        ("user", "With what?"),
        ("assistant", "Hand plane it."),
    ]
    assert (reopened["group_name"], reopened["model"]) == ("Woodworking", "opus")
    assert (await client.get("/api/conversations/999")).status_code == 404


async def test_conversations_and_their_citations_outlive_their_mentors_and_group_as_read_only(
    client: httpx.AsyncClient, engine: FakeChatEngine, transcripts: FakeTranscriptSource
) -> None:
    group, wright, _ = await woodworkers(client, transcripts)
    conversation = await start_conversation(client, group["id"])
    engine.script = [TextDelta("Hone it: https://www.youtube.com/watch?v=v-wright&t=5s"), ChatDone("session-1")]
    [cited] = done_message(await send(client, conversation["id"], "How fine a stone?"))["citations"]

    await client.delete(f"/api/mentors/{wright['id']}")
    await client.delete(f"/api/groups/{group['id']}")

    reopened = await get_conversation(client, conversation["id"])
    [listed] = await list_conversations(client)
    assert reopened["messages"][1]["citations"] == [cited]
    assert cited["mentor_name"] == "Paul Wright" and cited["video_title"] == "Sharpening chisels"
    assert (listed["group_id"], listed["group_name"]) == (None, "Woodworking")
    assert (await send(client, conversation["id"], "More?")).status_code == 409


async def test_a_conversation_whose_session_is_lost_carries_on_by_replaying_its_messages(
    client: httpx.AsyncClient, engine: FakeChatEngine
) -> None:
    conversation = await start_conversation(client, (await client.post("/api/groups", json={"name": "W"})).json()["id"])
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
    conversation = await start_conversation(client, (await client.post("/api/groups", json={"name": "W"})).json()["id"])
    engine.script = [ChatFailed("Claude Code is not logged in")]
    await send(client, conversation["id"], "Which stone?")
    engine.script = [TextDelta("A fine one."), ChatDone("session-1")]

    await send(client, conversation["id"], "Hello?")

    retry = engine.requests[1]
    assert (retry.resume_session_id, retry.history) == (None, [PastMessage("user", "Which stone?")])


async def test_each_conversation_keeps_the_model_it_was_started_with(
    client: httpx.AsyncClient, engine: FakeChatEngine
) -> None:
    group = (await client.post("/api/groups", json={"name": "W"})).json()
    default = await start_conversation(client, group["id"])
    haiku = await start_conversation(client, group["id"], model="haiku")

    await send(client, default["id"], "One?")
    await send(client, haiku["id"], "Two?")

    assert [r.model for r in engine.requests] == [None, "haiku"]
    assert (default["model"], haiku["model"]) == (None, "haiku")


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
    kept = await start_conversation(client, conversation["group_id"])
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
