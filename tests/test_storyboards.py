"""Frames of a cited moment: the geometry ingestion keeps, the arithmetic that finds a tile, the endpoint that
serves one, and the backfill for Videos ingested before any of it existed."""

from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from harness import (
    Json,
    add_channel,
    fake_channel,
    fake_storyboard,
    fake_video,
    list_videos,
    mcp_client,
    query,
    running,
    said,
    sync,
)

from mentor import db, storyboards, syncs
from mentor.app import create_app
from mentor.backfill_command import SYNC_RUNNING, BackfillReport, backfill_storyboards
from mentor.config import Config
from mentor.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource
from mentor.ports import Storyboard, VideoUnavailable
from mentor.storyboards import Frame, Moment, frames_at
from mentor.storyboards_api import MAX_MOMENTS
from mentor.sync_command import SyncCommandError

# Every field a search result has carried since before frames existed; a signed sheet URL is not among them.
SEARCH_RESULT_FIELDS = {
    "segment_id",
    "text",
    "start_seconds",
    "matched_seconds",
    "video_id",
    "youtube_video_id",
    "video_title",
    "published_on",
    "chapter_title",
    "channel_id",
    "channel_name",
    "score",
    "url",
}

# A tile every ten seconds, nine to a sheet, two sheets: eighteen frames over three minutes of video.
TEN_SECOND_TILES = fake_storyboard(fps=0.1, fragment_count=2)
SHEET_0 = "https://i.ytimg.com/sb/v/storyboard3_L3/M0.jpg?sqp=signed&sigh=signed"
SHEET_1 = "https://i.ytimg.com/sb/v/storyboard3_L3/M1.jpg?sqp=signed&sigh=signed"

type Served = tuple[httpx.AsyncClient, FastAPI]


@pytest.fixture
async def served(
    config: Config, transcripts: FakeTranscriptSource, embedder: FakeEmbedder, reranker: FakeReranker, tmp_path: Path
) -> AsyncIterator[Served]:
    app = create_app(config, transcripts, embedder, reranker, FakeChatEngine(), static_dir=tmp_path / "no-bundle")
    async with running(app) as client:
        yield client, app


async def wright_with_frames(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource, storyboard: Storyboard = TEN_SECOND_TILES
) -> tuple[Json, Json, Json]:
    """A synced Channel with one Video whose extraction offered a storyboard, and one whose didn't."""
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video(
            "v-bench", "Flattening a bench", cues=said("Plane across the grain", "Then along it"), storyboard=storyboard
        ),
        fake_video("v-vlog", "A week in the shop", cues=said("Plane across the yard")),
    ]
    channel = await add_channel(client, "@woodbywright", "Paul Wright")
    await sync(client, channel)
    listed = await list_videos(client, channel["id"])
    return channel, listed["Flattening a bench"], listed["A week in the shop"]


@pytest.mark.parametrize(
    ("duration", "moment", "expected"),
    [
        # The first frame: the cited moment's own tile leads, then one tile per storyboard interval.
        (180, Moment(1, 0.0, 3), [(0.0, SHEET_0, 0, 0), (10.0, SHEET_0, 1, 0), (20.0, SHEET_0, 2, 0)]),
        # A moment inside a tile takes that tile, not the next one, and the grid fills by rows.
        (180, Moment(1, 35.5, 2), [(30.0, SHEET_0, 0, 1), (40.0, SHEET_0, 1, 1)]),
        # The last fragment: tile 9 is the first cell of the second sheet.
        (180, Moment(1, 95.0, 2), [(90.0, SHEET_1, 0, 0), (100.0, SHEET_1, 1, 0)]),
        # A span running past the sheets gives the frames that exist rather than blank tiles.
        (180, Moment(1, 170.0, 5), [(170.0, SHEET_1, 2, 2)]),
        # A span running past the end of the Video stops there, though the sheets hold more tiles.
        (100, Moment(1, 85.0, 4), [(80.0, SHEET_0, 2, 2), (90.0, SHEET_1, 0, 0)]),
        # A moment past the end of the Video has no frames at all.
        (100, Moment(1, 240.0, 5), []),
        # An unknown length leaves the sheets to decide.
        (None, Moment(1, 170.0, 2), [(170.0, SHEET_1, 2, 2)]),
    ],
)
def test_the_tile_a_moment_falls_in_and_the_tiles_after_it(
    duration: int | None, moment: Moment, expected: list[tuple[float, str, int, int]]
) -> None:
    frames = frames_at(TEN_SECOND_TILES, duration, moment)

    assert frames == [Frame(seconds=s, url=url, column=column, row=row) for s, url, column, row in expected]


def test_a_video_shorter_than_one_tile_still_has_its_first_frame() -> None:
    assert frames_at(TEN_SECOND_TILES, 4, Moment(1, 0.0, 3)) == [Frame(0.0, SHEET_0, 0, 0)]


@pytest.mark.parametrize("length", [78.6, 79.0, 300.4, 1463.0])
@pytest.mark.parametrize("tiles", [17, 60, 143])
def test_no_frame_lands_past_the_tiles_a_real_storyboard_painted(length: float, tiles: int) -> None:
    """YouTube's fps is a tile count over the Video's real length, and the length stored beside it is rounded, so
    their product lands either side of a whole number. One tile too many is an unpainted cell of a sheet that
    loaded perfectly well, which no failed-image check can catch."""
    # Sheets with room to spare, so only the Video's length can decide where the tiles stop.
    storyboard = replace(fake_storyboard(columns=5, rows=5, fragment_count=tiles // 25 + 1), fps=tiles / length)
    duration = round(length)

    # Asked from past the end, and from the last tile the storyboard really painted, for more than can exist.
    assert frames_at(storyboard, duration, Moment(1, length + 120, 5)) == []
    last = frames_at(storyboard, duration, Moment(1, (tiles - 1) / storyboard.fps, 5))

    # The last tile is the last frame there is; the tile after it was never painted.
    assert [round(frame.seconds * storyboard.fps) for frame in last][-1:] == [tiles - 1]


async def test_ingestion_stores_the_geometry_its_own_extraction_offered(
    served: Served, transcripts: FakeTranscriptSource, config: Config
) -> None:
    client, _ = served

    _, with_frames, without = await wright_with_frames(
        client, transcripts, fake_storyboard(columns=5, rows=5, width=160, height=90)
    )

    stored = query(config, "SELECT * FROM storyboards")
    assert [row["video_id"] for row in stored] == [with_frames["id"]]
    assert (stored[0]["columns"], stored[0]["rows"], stored[0]["width"], stored[0]["height"]) == (5, 5, 160, 90)
    assert stored[0]["url_template"].endswith("M{index}.jpg?sqp=signed&sigh=signed")
    assert (stored[0]["fragment_count"], stored[0]["fps"]) == (2, 0.1)
    assert stored[0]["fetched_at"].endswith("+00:00")
    # It cost no extra call: one fetch per Video, as before.
    assert [argument for method, argument in transcripts.calls if method == "fetch_video"] == ["v-bench", "v-vlog"]
    # A Video whose storyboard is absent ingests and searches exactly as it did.
    assert without["stage"] == "done"
    found = (await client.post("/api/search", json={"query": "plane across"})).json()
    assert {result["youtube_video_id"] for result in found} == {"v-bench", "v-vlog"}


async def test_frames_are_served_from_their_own_endpoint_for_the_videos_that_have_geometry(
    served: Served, transcripts: FakeTranscriptSource
) -> None:
    client, _ = served
    _, with_frames, without = await wright_with_frames(client, transcripts)

    response = await client.post(
        "/api/frames",
        json={
            "moments": [
                {"video_id": with_frames["id"], "seconds": 15.0, "count": 3},
                {"video_id": without["id"], "seconds": 0.0, "count": 3},
                {"video_id": 999999, "seconds": 0.0, "count": 3},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "columns": 3,
            "rows": 3,
            "video_id": with_frames["id"],
            "seconds": 15.0,
            "frames": [
                {"seconds": 10.0, "url": SHEET_0, "column": 1, "row": 0},
                {"seconds": 20.0, "url": SHEET_0, "column": 2, "row": 0},
                {"seconds": 30.0, "url": SHEET_0, "column": 0, "row": 1},
            ],
        }
    ]


async def test_one_video_asked_about_twice_gets_an_answer_for_each_moment(
    served: Served, transcripts: FakeTranscriptSource
) -> None:
    """Search groups consecutive results, so a Video can lead two runs and each wants its own frames."""
    client, _ = served
    _, with_frames, _ = await wright_with_frames(client, transcripts)

    answered = (
        await client.post(
            "/api/frames",
            json={
                "moments": [
                    {"video_id": with_frames["id"], "seconds": 0.0, "count": 1},
                    {"video_id": with_frames["id"], "seconds": 95.0, "count": 1},
                ]
            },
        )
    ).json()

    assert [(video["seconds"], video["frames"][0]["url"]) for video in answered] == [(0.0, SHEET_0), (95.0, SHEET_1)]


@pytest.mark.parametrize(
    "moments",
    [
        [],
        [{"video_id": 1, "seconds": 0.0, "count": 6}],
        [{"video_id": 1, "seconds": 0.0, "count": 0}],
        [{"video_id": 1, "seconds": -1.0, "count": 3}],
        [{"video_id": "1", "seconds": 0.0, "count": 3}],
        [{"video_id": 1, "seconds": 0.0}],
    ],
)
async def test_the_frames_endpoint_refuses_a_request_it_cannot_answer(served: Served, moments: list[Json]) -> None:
    client, _ = served

    assert (await client.post("/api/frames", json={"moments": moments})).status_code == 422


async def test_frames_leave_out_a_channel_that_is_not_indexed(
    served: Served, transcripts: FakeTranscriptSource
) -> None:
    client, _ = served
    channel, with_frames, _ = await wright_with_frames(client, transcripts)
    moments = {"moments": [{"video_id": with_frames["id"], "seconds": 0.0, "count": 3}]}
    assert (await client.post("/api/frames", json=moments)).json() != []

    await client.patch(f"/api/channels/{channel['id']}", json={"indexed": False})

    assert (await client.post("/api/frames", json=moments)).json() == []


async def test_a_stored_storyboard_changes_nothing_a_model_is_handed(
    served: Served, transcripts: FakeTranscriptSource
) -> None:
    client, app = served
    _, with_frames, _ = await wright_with_frames(client, transcripts)
    arguments: Json = {"query": "plane across the grain", "limit": 5}

    api = (await client.post("/api/search", json=arguments)).json()
    async with mcp_client(app) as mcp:
        searched = await mcp.call_tool("search", arguments)
        described = await mcp.call_tool("get_video", {"video_id": with_frames["id"]})

    # The same fields as before frames existed, and no sheet URL anywhere in what a model reads.
    assert api != []
    assert [set(result) for result in api] == [SEARCH_RESULT_FIELDS for _ in api]
    assert searched.structured_content == {"result": api}
    for result in (searched, described):
        text = f"{result.content}{result.structured_content}"
        assert "i.ytimg.com" not in text and "sigh=" not in text and "storyboard" not in text


def test_a_storyboard_no_longer_offered_is_cleared_and_a_video_gone_stores_nothing(config: Config) -> None:
    """A stored template's signature expires, so a Video re-fetched without a storyboard must lose the one it had:
    the tile it would paint loads as nothing and reports no error. A Video deleted meanwhile just stores nothing."""
    db.initialize(config.database_path, "fake-embedder", 4)
    conn = db.connect(config.database_path)
    try:
        conn.executescript(
            """
            INSERT INTO channels (id, youtube_channel_id, name) VALUES (1, 'UC-wright', 'Paul Wright');
            INSERT INTO videos (id, channel_id, youtube_video_id, title, pipeline_stage, discovered_at)
                VALUES (1, 1, 'v-bench', 'Bench', 'done', '2026-01-01T00:00:00+00:00');
            """
        )
        with db.transaction(conn):
            storyboards.record(conn, 1, fake_storyboard())
        assert conn.execute("SELECT count(*) FROM storyboards").fetchone()[0] == 1

        with db.transaction(conn):
            storyboards.record(conn, 1, None)
        with db.transaction(conn):
            storyboards.record(conn, 99, fake_storyboard())

        assert conn.execute("SELECT count(*) FROM storyboards").fetchone()[0] == 0
    finally:
        conn.close()


async def test_the_frames_endpoint_answers_as_many_moments_as_one_request_may_carry(
    served: Served, transcripts: FakeTranscriptSource
) -> None:
    """The web client asks in batches of this size, so a chat citing more Videos loses at most one batch."""
    client, _ = served
    _, with_frames, _ = await wright_with_frames(client, transcripts)
    moment = {"video_id": with_frames["id"], "seconds": 0.0, "count": 1}

    full = await client.post("/api/frames", json={"moments": [moment] * MAX_MOMENTS})
    over = await client.post("/api/frames", json={"moments": [moment] * (MAX_MOMENTS + 1)})

    assert (full.status_code, over.status_code) == (200, 422)


async def test_a_moment_that_is_not_a_number_of_seconds_is_refused(served: Served) -> None:
    client, _ = served

    response = await client.post(
        "/api/frames",
        content=b'{"moments": [{"video_id": 1, "seconds": Infinity, "count": 3}]}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422


async def test_the_backfill_warns_while_a_sync_is_queued_or_running(
    served: Served, transcripts: FakeTranscriptSource, config: Config
) -> None:
    """Both reach YouTube from one address, and a refusal the two bring on counts against the Sync."""
    client, _ = served
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-bench", "Bench", cues=said("Plane it")))
    channel = await add_channel(client, "@woodbywright", "Paul Wright")
    await sync(client, channel)
    await database_sync_queued(config, channel["id"])
    lines: list[str] = []

    backfill_storyboards(config, None, transcripts, lines.append)

    assert [line for line in lines if line.startswith("warning:")] == [SYNC_RUNNING]


async def test_a_video_deleted_while_the_backfill_runs_does_not_stop_it(
    served: Served, transcripts: FakeTranscriptSource, config: Config
) -> None:
    client, _ = served
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-gone", "Gone", cues=said("Plane it")))
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-saw", "Saw files", cues=said("File the teeth")))
    wright = await add_channel(client, "@woodbywright", "Paul Wright")
    rex = await add_channel(client, "@rexkrueger")
    await sync(client, wright, rex)
    _now_offers_storyboards(transcripts)
    # The Channel goes while the backfill is between Videos, as a deletion in the web UI would take it.
    fake_channel(transcripts, "UC-wright").videos[0].before_fetch = _deleting(config, wright["id"])

    report = backfill_storyboards(config, None, transcripts)

    # The Video that went stored nothing and failed nothing; the other Channel's Video still got its frames.
    assert (report.stored, report.failed, report.remaining, report.stopped) == (1, 0, 0, None)
    assert [row["youtube_video_id"] for row in query(
        config, "SELECT youtube_video_id FROM videos v JOIN storyboards s ON s.video_id = v.id"
    )] == ["v-saw"]
    assert (rex["id"], wright["id"]) != (None, None)


async def test_the_backfill_stores_what_is_missing_and_resumes_where_it_stopped(
    served: Served, transcripts: FakeTranscriptSource, config: Config
) -> None:
    client, _ = served
    # Ingested before storyboards were kept: both Videos are done with nothing stored.
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-bench", "Flattening a bench", cues=said("Plane across the grain"))
    )
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-saw", "Saw files", cues=said("File the teeth")))
    wright = await add_channel(client, "@woodbywright", "Paul Wright")
    rex = await add_channel(client, "@rexkrueger")
    await sync(client, wright, rex)
    assert query(config, "SELECT * FROM storyboards") == []
    _now_offers_storyboards(transcripts)
    lines: list[str] = []

    one_channel = backfill_storyboards(config, "Paul Wright", transcripts, lines.append)
    everything = backfill_storyboards(config, None, transcripts, lines.append)

    assert one_channel == BackfillReport(stored=1, absent=0, failed=0, remaining=0)
    # Resumption: the Video the first run stored is never fetched again, so only the other one is.
    assert everything == BackfillReport(stored=1, absent=0, failed=0, remaining=0)
    assert [argument for method, argument in transcripts.calls if method == "fetch_storyboard"] == ["v-bench", "v-saw"]
    assert {row["video_id"] for row in query(config, "SELECT video_id FROM storyboards")} == {
        row["id"] for row in query(config, "SELECT id FROM videos")
    }
    assert [line.split(":")[0] for line in lines] == ["v-bench", "v-saw"]
    # With nothing left to do it asks YouTube for nothing at all.
    assert backfill_storyboards(config, None, transcripts) == BackfillReport(0, 0, 0, 0)


async def test_the_backfill_reports_a_video_offering_no_storyboard_without_failing_it(
    served: Served, transcripts: FakeTranscriptSource, config: Config
) -> None:
    client, _ = served
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-bench", "Bench", cues=said("Plane it")))
    await sync(client, await add_channel(client, "@woodbywright", "Paul Wright"))

    report = backfill_storyboards(config, None, transcripts)

    assert report == BackfillReport(stored=0, absent=1, failed=0, remaining=0)
    assert query(config, "SELECT * FROM storyboards") == []


async def test_the_backfill_stops_when_the_source_refuses_and_keeps_what_it_stored(
    served: Served, transcripts: FakeTranscriptSource, config: Config
) -> None:
    client, _ = served
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-one", "One", cues=said("one")),
        fake_video("v-two", "Two", cues=said("two")),
        fake_video("v-three", "Three", cues=said("three")),
        fake_video("v-four", "Four", cues=said("four")),
    ]
    await sync(client, await add_channel(client, "@woodbywright", "Paul Wright"))
    _now_offers_storyboards(transcripts)
    videos = fake_channel(transcripts, "UC-wright").videos
    # The second Video can't be read on its own; the third makes the source refuse outright.
    videos[1].failure = VideoUnavailable("Members-only Video", permanent=True)
    videos[2].before_fetch = _refusing(transcripts)

    report = backfill_storyboards(config, None, transcripts)

    assert (report.stored, report.absent, report.failed, report.remaining) == (1, 0, 1, 2)
    assert report.stopped is not None and "not having it" in report.stopped
    assert [row["youtube_video_id"] for row in query(config, "SELECT youtube_video_id FROM videos v"
                                                    " JOIN storyboards s ON s.video_id = v.id")] == ["v-one"]


def test_the_backfill_offers_only_videos_something_could_cite(config: Config) -> None:
    db.initialize(config.database_path, "fake-embedder", 4)
    conn = db.connect(config.database_path)
    try:
        conn.executescript(
            """
            INSERT INTO channels (id, youtube_channel_id, name) VALUES (1, 'UC-wright', 'Paul Wright'),
                                                                      (2, 'UC-rex', 'Rex Krueger');
            INSERT INTO videos (id, channel_id, youtube_video_id, title, pipeline_stage, discovered_at)
                VALUES (1, 1, 'v-done', 'Done', 'done', '2026-01-01T00:00:00+00:00'),
                       (2, 1, 'v-embedded', 'Still going', 'embedded', '2026-01-01T00:00:00+00:00'),
                       (3, 1, 'v-new', 'New', 'discovered', '2026-01-01T00:00:00+00:00'),
                       (4, 2, 'v-rex', 'Rex', 'done', '2026-01-01T00:00:00+00:00');
            """
        )
        # Only a done Video is searchable, so only a done Video's frames could ever be shown.
        assert storyboards.missing(conn, None) == [(1, "v-done"), (4, "v-rex")]
        assert storyboards.missing(conn, 2) == [(4, "v-rex")]
        # A Channel that is not indexed is left out of search, expand and frames alike: no call is spent on it.
        conn.execute("UPDATE channels SET indexed = 0 WHERE id = 2")
        assert storyboards.missing(conn, None) == [(1, "v-done")]
        assert storyboards.missing(conn, 2) == []
    finally:
        conn.close()


async def test_the_backfill_names_an_unknown_channel_rather_than_fetching_every_one(
    served: Served, transcripts: FakeTranscriptSource, config: Config
) -> None:
    with pytest.raises(SyncCommandError, match="No Channel named"):
        backfill_storyboards(config, "Nobody", transcripts)

    assert [method for method, _ in transcripts.calls if method == "fetch_storyboard"] == []


def test_the_backfill_refuses_a_knowledge_base_from_a_newer_mentor(
    config: Config, transcripts: FakeTranscriptSource
) -> None:
    config.data_dir.mkdir(parents=True)
    conn = db.connect(config.database_path)
    conn.execute("PRAGMA user_version = 999")
    conn.close()

    with pytest.raises(SyncCommandError, match="newer"):
        backfill_storyboards(config, None, transcripts)


async def test_deleting_a_video_takes_its_storyboard_with_it(
    served: Served, transcripts: FakeTranscriptSource, config: Config
) -> None:
    client, _ = served
    channel, _, _ = await wright_with_frames(client, transcripts)
    assert query(config, "SELECT * FROM storyboards") != []

    assert (await client.delete(f"/api/channels/{channel['id']}")).status_code == 204

    assert query(config, "SELECT * FROM storyboards") == []


def _now_offers_storyboards(transcripts: FakeTranscriptSource) -> None:
    """As if YouTube had been asked again: every Video's extraction now carries a storyboard."""
    for channel in transcripts.channels:
        for video in channel.all_videos:
            video.details = replace(video.details, storyboard=fake_storyboard())


def _refusing(transcripts: FakeTranscriptSource) -> Callable[[], None]:
    def refuse() -> None:
        transcripts.unavailable = "YouTube is not having it"

    return refuse


async def database_sync_queued(config: Config, channel_id: int) -> None:
    """A queued Sync in the knowledge base, as another process would have left one."""
    conn = db.connect(config.database_path)
    try:
        syncs.enqueue(conn, channel_id)
    finally:
        conn.close()


def _deleting(config: Config, channel_id: int) -> Callable[[], None]:
    def delete() -> None:
        conn = db.connect(config.database_path)
        try:
            with db.transaction(conn):
                conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        finally:
            conn.close()

    return delete
