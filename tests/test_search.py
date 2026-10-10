from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from harness import (
    Json,
    add_channel,
    add_group,
    fake_channel,
    fake_video,
    running,
    said,
    start_sync,
    sync,
    wait_for_syncs,
)

from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from seek.ports import Chapter, Cue


async def search(client: httpx.AsyncClient, query: str, **scope: object) -> list[Json]:
    response = await client.post("/api/search", json={"query": query, **scope})
    assert response.status_code == 200, response.text
    results: list[Json] = response.json()
    return results


@pytest.mark.parametrize("reranker_unavailable", [False, True])
async def test_a_result_carries_its_channel_video_chapter_and_a_citation_to_the_matched_cue(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, reranker: FakeReranker, reranker_unavailable: bool
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video(
            "v-dovetails",
            "Hand-cut dovetails",
            published_on=date(2024, 5, 17),
            chapters=[Chapter(title="Intro", start=0, end=30), Chapter(title="Sawing", start=30, end=600)],
            cues=[
                Cue(start=0, end=30, text="Welcome back to the shop"),
                Cue(start=30, end=35, text="First knife the baseline all round"),
                Cue(start=35, end=41.5, text="Now the saw does the work"),
                Cue(start=41.5, end=48, text="Keep the kerf on the waste side of the line"),
            ],
        )
    )
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-sheath", "Leather sheath", cues=said("Stitch the sheath with waxed thread"))
    )
    wright = await add_channel(client, "@woodbywright", "Paul Wright")
    await sync(client, wright, await add_channel(client, "@rexkrueger"))
    if reranker_unavailable:
        reranker.unavailable = "Reranker scoring failed"

    results = await search(client, "which side of the line does the kerf go")

    assert results[0] == {
        "segment_id": results[0]["segment_id"],
        "text": (
            "First knife the baseline all round Now the saw does the work Keep the kerf on the waste side of the line"
        ),
        "start_seconds": 30.0,
        "matched_seconds": 41.5,
        "video_id": results[0]["video_id"],
        "youtube_video_id": "v-dovetails",
        "video_title": "Hand-cut dovetails",
        "published_on": "2024-05-17",
        "chapter_title": "Sawing",
        "channel_id": wright["id"],
        "channel_name": "Paul Wright",
        "score": results[0]["score"],
        "url": "https://www.youtube.com/watch?v=v-dovetails&t=41s",
    }
    assert isinstance(results[0]["segment_id"], int) and isinstance(results[0]["video_id"], int)
    if reranker_unavailable:
        assert all(result["score"] == 0 for result in results)
    else:
        assert 0 < results[0]["score"] <= 1
    assert sorted(r["youtube_video_id"] for r in results) == ["v-dovetails", "v-dovetails", "v-sheath"]
    assert [r["score"] for r in results] == sorted((r["score"] for r in results), reverse=True)


@pytest.mark.parametrize("reranker_unavailable", [False, True])
async def test_search_is_scoped_to_a_group_by_id_or_name_to_channels_or_to_everything(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, reranker: FakeReranker, reranker_unavailable: bool
) -> None:
    for youtube_id, video_id in [("UC-wright", "v-wright"), ("UC-rex", "v-rex")]:
        fake_channel(transcripts, youtube_id).videos.append(
            fake_video(video_id, video_id, cues=said("Sharpen the chisel on a fine stone"))
        )
    wright = await add_channel(client, "@woodbywright")
    rex = await add_channel(client, "@rexkrueger")
    await sync(client, wright, rex)
    # A Group can be named like another Group's id: a JSON number is an id, a string is a name.
    first = await add_group(client, "Joinery", wright)
    await add_group(client, str(first["id"]), rex)
    if reranker_unavailable:
        reranker.unavailable = "Reranker scoring failed"

    async def found(**scope: object) -> set[str]:
        return {r["youtube_video_id"] for r in await search(client, "sharpen a chisel", **scope)}

    assert await found() == {"v-wright", "v-rex"}
    assert await found(group=first["id"]) == {"v-wright"}
    assert await found(group="joinery") == {"v-wright"}
    assert await found(group=str(first["id"])) == {"v-rex"}
    assert await found(channels=[rex["id"]]) == {"v-rex"}
    assert await found(channels=[rex["id"], wright["id"]]) == {"v-wright", "v-rex"}
    empty = await add_group(client, "Empty")
    assert await found(group=empty["id"]) == set()


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"query": "chisel", "group": 1, "channels": [1]}, 422),
        ({"query": "chisel", "channels": []}, 422),
        ({"query": "   "}, 422),
        ({"query": "chisel", "limit": 0}, 422),
        ({"query": "chisel", "limit": 51}, 422),
        ({"query": "chisel", "prefer_recent": "always"}, 422),
        ({"query": "chisel", "group": 999}, 404),
        ({"query": "chisel", "group": "Nobody"}, 404),
        ({"query": "chisel", "channels": [999]}, 404),
    ],
)
async def test_invalid_searches_are_rejected(client: httpx.AsyncClient, body: Json, status: int) -> None:
    await add_channel(client, "@woodbywright")
    await add_group(client, "Joinery")

    response = await client.post("/api/search", json=body)

    assert response.status_code == status, response.text


async def test_not_indexed_channels_are_left_out_of_every_scope(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-main", "Main", cues=said("Flatten the board")))
    fake_channel(transcripts, "UC-wright-vlog").videos.append(
        fake_video("v-vlog", "Vlog", cues=said("Flatten the board at the cabin"))
    )
    wright = await add_channel(client, "@woodbywright")
    vlog = await add_channel(client, "@wrightvlogs")
    await sync(client, wright, vlog)
    group = await add_group(client, "Joinery", wright, vlog)

    before = await search(client, "flatten the board")
    await client.patch(f"/api/channels/{vlog['id']}", json={"indexed": False})

    assert {r["youtube_video_id"] for r in before} == {"v-main", "v-vlog"}
    for scope in ({}, {"group": group["id"]}, {"channels": [wright["id"], vlog["id"]]}):
        assert [r["youtube_video_id"] for r in await search(client, "flatten the board", **scope)] == ["v-main"]


async def test_newer_videos_win_near_ties_gently_by_default_and_strongly_when_asked(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    # Search measures age from the UTC date.
    today = datetime.now(UTC).date()
    words = [f"term{n}" for n in range(20)]

    def saying(count: int) -> list[Cue]:
        return said(" ".join(words[:count]))

    # The fake reranker's logit grows with the share of query words present: 20, 19, 15, and 10 of 20.
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-old-best", "Old", published_on=today - timedelta(days=5 * 365), cues=saying(20)),
        fake_video("v-new-close", "Close", published_on=today, cues=saying(19)),
        fake_video("v-new-fair", "Fair", published_on=today, cues=saying(15)),
        fake_video("v-new-weak", "Weak", published_on=today, cues=saying(10)),
    ]
    await sync(client, await add_channel(client, "@woodbywright"))

    async def order(**options: object) -> list[str]:
        return [r["youtube_video_id"] for r in await search(client, " ".join(words), **options)]

    assert await order(prefer_recent="off") == ["v-old-best", "v-new-close", "v-new-fair", "v-new-weak"]
    # Five years older loses only the near-tie.
    assert await order() == await order(prefer_recent="gentle") == ["v-new-close", "v-old-best", "v-new-fair", "v-new-weak"]
    # Strongly it loses to a fair match too, but never sinks below a clearly worse one.
    assert await order(prefer_recent="strong") == ["v-new-close", "v-new-fair", "v-old-best", "v-new-weak"]


async def test_exact_jargon_is_found_lexically_beyond_the_nearest_vectors(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video(f"v-technique-{n}", f"Technique {n}", cues=said("technique")) for n in range(60)
    ]
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-domino", "Loose tenons", cues=said("the domino joiner makes loose tenons quickly for many other jobs"))
    )
    await sync(client, await add_channel(client, "@woodbywright"))
    await sync(client, await add_channel(client, "@rexkrueger"))

    # Every "technique" Segment is nearer the query than the long one naming the tool.
    results = await search(client, "domino joiner technique")
    syntax = await client.post("/api/search", json={"query": 'C++ "domino" NEAR(joiner -technique*) OR'})

    assert results[0]["youtube_video_id"] == "v-domino"
    assert syntax.status_code == 200, syntax.text
    assert syntax.json()[0]["youtube_video_id"] == "v-domino"


async def test_a_segment_is_indexed_and_reranked_with_its_video_title_and_chapter(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, embedder: FakeEmbedder, reranker: FakeReranker
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video(
            "v-scraper",
            "Sharpening a card scraper",
            chapters=[Chapter(title="Burnishing", start=0, end=600)],
            cues=said("push the burnisher along the edge at a slight angle"),
        ),
        fake_video("v-plane", "Plane setup", cues=said("set the cap iron close to the edge")),
    ]
    await sync(client, await add_channel(client, "@woodbywright"))

    # Nothing spoken mentions a scraper: only the title does, and only the lexical index sees it.
    results = await search(client, "card scraper")

    assert [r["youtube_video_id"] for r in results] == ["v-scraper", "v-plane"]
    assert results[0]["text"] == "push the burnisher along the edge at a slight angle"
    passage = "Sharpening a card scraper — Burnishing\npush the burnisher along the edge at a slight angle"
    assert passage in embedder.passages
    assert "Plane setup\nset the cap iron close to the edge" in embedder.passages
    assert reranker.calls[0][1][0] == passage


@pytest.mark.parametrize("reranker_unavailable", [False, True])
async def test_results_spread_across_videos_before_one_videos_overlapping_windows_fill_the_list(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, reranker: FakeReranker, reranker_unavailable: bool
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        # Five minutes of one passage: several overlapping Segments, all matching equally well.
        fake_video("v-long", "Long", cues=said(*["hone the chisel bevel"] * 60)),
        fake_video("v-other", "Other", cues=said("hone the chisel bevel")),
    ]
    await sync(client, await add_channel(client, "@woodbywright"))

    if reranker_unavailable:
        reranker.unavailable = "Reranker scoring failed"
    results = await search(client, "hone the chisel bevel")
    windows = [r["youtube_video_id"] for r in results]

    assert windows[:4] == ["v-long", "v-long", "v-long", "v-other"]
    # With every Video's best windows listed, the rest fill in rather than leaving the list short.
    assert 4 < len(windows) <= 10 and set(windows[4:]) == {"v-long"}


async def test_videos_still_in_the_pipeline_are_not_searchable(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, embedder: FakeEmbedder
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-done", "Done", cues=said("flatten the board")))
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-stuck", "Stuck", cues=said("flatten the board")))
    await sync(client, await add_channel(client, "@woodbywright"))
    rex = await add_channel(client, "@rexkrueger")
    embedder.unavailable = "CUDA out of memory"
    await start_sync(client, rex["id"])
    [stopped, _] = await wait_for_syncs(client)
    embedder.unavailable = None

    results = await search(client, "flatten the board")

    assert (stopped["status"], stopped["stage_counts"]["segmented"]) == ("failed", 1)
    assert [r["youtube_video_id"] for r in results] == ["v-done"]


class Synonyms(FakeEmbedder):
    """Embeds "hone" as "sharpen": a paraphrase the vector search finds and the lexical search can't."""

    def _embed(self, text: str) -> list[float]:
        return super()._embed(text.replace("hone", "sharpen"))


async def test_a_small_channel_in_a_large_corpus_still_gets_vector_hits_and_at_most_50_are_reranked(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    reranker = FakeReranker()
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video(f"v-wright-{n}", f"Wright {n}", cues=said(f"sharpen chisel bevel {n}")) for n in range(60)
    ]
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-rex", "Rex", cues=said("hone blade")))
    app = create_app(config, transcripts, Synonyms(), reranker, FakeChatEngine(), static_dir=tmp_path / "no-bundle")

    async with running(app) as client:
        wright = await add_channel(client, "@woodbywright")
        rex = await add_channel(client, "@rexkrueger")
        await sync(client, wright, rex)
        everything = await search(client, "sharpen chisel")
        just_rex = await search(client, "sharpen chisel", channels=[rex["id"]], limit=50)

    assert len(everything) == 10
    # Rex's Segment shares no words with the query and is further from it than any of Wright's 60.
    assert [r["youtube_video_id"] for r in just_rex] == ["v-rex"]
    assert [len(passages) for _, passages in reranker.calls] == [50, 1]


async def test_search_reports_an_unavailable_embedder(
    client: httpx.AsyncClient,
    transcripts: FakeTranscriptSource,
    embedder: FakeEmbedder,
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-one", "One"))
    await sync(client, await add_channel(client, "@woodbywright"))
    embedder.unavailable = "The model is still loading"

    response = await client.post("/api/search", json={"query": "welcome"})

    assert (response.status_code, response.json()) == (503, {"detail": "The model is still loading"})


async def test_search_returns_unscored_fused_results_when_the_reranker_is_unavailable(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, reranker: FakeReranker
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-exact", "Sharpen chisel", cues=said("Sharpen chisel")),
        fake_video("v-other", "Other", cues=said("Saw timber")),
    ]
    await sync(client, await add_channel(client, "@woodbywright"))
    reranker.unavailable = "The reranker is still loading"

    results = await search(client, "sharpen chisel", prefer_recent="strong", limit=2)

    assert [result["youtube_video_id"] for result in results] == ["v-exact", "v-other"]
    assert [result["score"] for result in results] == [0.0, 0.0]
