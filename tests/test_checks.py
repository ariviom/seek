import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from harness import Gate, add_channel, add_playlist, fake_channel, fake_video, running, sync_playlist

from seek import db
from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakePlaylist, FakeReranker, FakeTranscriptSource
from seek.syncs import is_due

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("indexed", "every", "open_sync", "last_queued", "due"),
    [
        (True, 24, False, None, False),
        (True, 24, False, NOW - timedelta(hours=23), False),
        (True, 24, False, NOW - timedelta(hours=25), True),
        (True, 6, False, NOW - timedelta(hours=7), True),
        (True, 168, False, NOW - timedelta(days=6), False),
        (False, 24, False, None, False),
        (False, 24, False, NOW - timedelta(days=30), False),
        (True, None, False, None, False),
        (True, None, False, NOW - timedelta(days=30), False),
        (True, 24, True, None, False),
        (True, 24, True, NOW - timedelta(days=30), False),
    ],
    ids=[
        "never synced, so its first sync is the user's",
        "recent",
        "overdue",
        "overdue at six hours",
        "within a week",
        "paused, never synced",
        "paused, overdue",
        "off, never synced",
        "off, overdue",
        "queued or running, never finished",
        "queued or running, overdue",
    ],
)
def test_a_channel_or_playlist_is_due_when_active_on_idle_and_its_latest_sync_is_older_than_its_interval(
    indexed: bool, every: int | None, open_sync: bool, last_queued: datetime | None, due: bool
) -> None:
    assert is_due(indexed, every, open_sync, last_queued, NOW) is due


async def test_a_channel_checks_daily_until_its_interval_is_changed_or_turned_off(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")
    url = f"/api/channels/{wright['id']}"

    weekly = await client.patch(url, json={"check_every_hours": 168})
    renamed = await client.patch(url, json={"name": "Rob Wright"})
    paused = await client.patch(url, json={"indexed": False})
    off = await client.patch(url, json={"check_every_hours": None})
    listed = (await client.get("/api/channels")).json()

    assert wright["check_every_hours"] == 24
    assert weekly.json()["check_every_hours"] == 168
    # Leaving the field out leaves it unchanged, and pausing keeps it too; only null turns checks off.
    assert renamed.json()["check_every_hours"] == 168
    assert paused.json()["check_every_hours"] == 168
    assert off.json()["check_every_hours"] is None
    assert [c["check_every_hours"] for c in listed] == [None]


async def test_only_six_hours_a_day_a_week_or_off_are_accepted(client: httpx.AsyncClient) -> None:
    wright = await add_channel(client, "@woodbywright")
    url = f"/api/channels/{wright['id']}"

    accepted = [(await client.patch(url, json={"check_every_hours": hours})).status_code for hours in (6, 24, 168)]
    refused = [
        (await client.patch(url, json={"check_every_hours": value})).status_code
        for value in (0, 12, 48, -6, 24.0, "24", True, "daily")
    ]

    assert accepted == [200, 200, 200]
    assert refused == [422] * 8
    assert [c["check_every_hours"] for c in (await client.get("/api/channels")).json()] == [168]


async def test_a_playlist_reports_its_next_check_once_synced_unless_paused_or_off(
    client: httpx.AsyncClient, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-knives", "Knives"))
    transcripts.playlists["PL-picks"] = FakePlaylist("Picks", [("UC-rex", "v-knives")])
    added = await add_playlist(client, "PL-picks")
    url = f"/api/playlists/{added['id']}"

    async def next_check() -> object:
        [listed] = (await client.get("/api/playlists")).json()
        return listed["next_check_at"]

    never_synced = await next_check()
    await sync_playlist(client, added)
    [sync] = (await client.get("/api/syncs")).json()
    queued_at = datetime.fromisoformat(sync["queued_at"])
    daily = await next_check()
    six_hourly = (await client.patch(url, json={"check_every_hours": 6})).json()["next_check_at"]
    await client.patch(url, json={"indexed": False})
    paused = await next_check()
    await client.patch(url, json={"indexed": True, "check_every_hours": None})
    off = await next_check()

    # Its first Sync is the user's, so nothing is due before it.
    assert (added["next_check_at"], never_synced) == (None, None)
    assert daily == (queued_at + timedelta(hours=24)).isoformat()
    assert six_hourly == (queued_at + timedelta(hours=6)).isoformat()
    assert (paused, off) == (None, None)


def hours_ago(hours: int) -> str:
    return (NOW - timedelta(hours=hours)).isoformat(timespec="seconds")


def seed_knowledge_base(config: Config) -> None:
    """Channels in every state the checks tell apart, and Playlists in the main ones, each named for its state."""
    conn = db.connect(config.database_path)
    db.migrate(conn)
    conn.executescript(
        f"""
        INSERT INTO channels (id, youtube_channel_id, name, indexed, check_every_hours, in_library) VALUES
            (1, 'UC-1', 'never synced', 1, 24, 1),
            (2, 'UC-2', 'recent', 1, 6, 1),
            (3, 'UC-3', 'overdue', 1, 24, 1),
            (4, 'UC-4', 'paused', 0, 24, 1),
            (5, 'UC-5', 'off', 1, NULL, 1),
            (6, 'UC-6', 'queued', 1, 24, 1),
            (7, 'UC-7', 'running', 1, 24, 1),
            (8, 'UC-8', 'outside the Library', 1, 24, 0);
        INSERT INTO playlists (id, youtube_playlist_id, name, indexed, check_every_hours) VALUES
            (1, 'PL-1', 'never synced playlist', 1, 24),
            (2, 'PL-2', 'recent playlist', 1, 6),
            (3, 'PL-3', 'overdue playlist', 1, 24),
            (4, 'PL-4', 'paused playlist', 0, 24);
        INSERT INTO syncs (channel_id, status, queued_at, stage_counts) VALUES
            (2, 'done', '{hours_ago(1)}', '{{}}'),
            (3, 'done', '{hours_ago(25)}', '{{}}'),
            (4, 'done', '{hours_ago(200)}', '{{}}'),
            (5, 'done', '{hours_ago(200)}', '{{}}'),
            (6, 'queued', '{hours_ago(200)}', '{{}}'),
            (7, 'running', '{hours_ago(200)}', '{{}}'),
            (8, 'done', '{hours_ago(200)}', '{{}}');
        INSERT INTO syncs (playlist_id, status, queued_at, stage_counts) VALUES
            (2, 'done', '{hours_ago(1)}', '{{}}'),
            (3, 'done', '{hours_ago(25)}', '{{}}'),
            (4, 'done', '{hours_ago(200)}', '{{}}');
        """
    )
    conn.close()


def syncs_per_source(syncs: list[dict[str, object]]) -> dict[object, int]:
    counts: dict[object, int] = {}
    for sync in syncs:
        counts[sync["source_name"]] = counts.get(sync["source_name"], 0) + 1
    return counts


async def test_the_server_queues_one_sync_for_each_due_channel_and_playlist_at_start_and_as_others_fall_due(
    config: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    seed_knowledge_base(config)
    clock = [NOW]
    # Holding the embedding model keeps every queued Sync queued, so what the checks queued stays visible.
    gate = Gate()
    app = create_app(
        config,
        transcripts,
        FakeEmbedder(before_load=gate),
        FakeReranker(),
        FakeChatEngine("cli"),
        static_dir=tmp_path / "no-bundle",
        check_seconds=0.02,
        clock=lambda: clock[0],
    )
    try:
        async with running(app) as client:
            # Several checks run meanwhile; none queues a second Sync.
            await asyncio.sleep(0.3)
            at_start = (await client.get("/api/syncs")).json()
            clock[0] = NOW + timedelta(hours=6)
            await asyncio.sleep(0.3)
            later = (await client.get("/api/syncs")).json()
    finally:
        gate.released.set()

    new_at_start = [s for s in at_start if s["id"] > 10]
    assert sorted(s["source_name"] for s in new_at_start) == ["overdue", "overdue playlist"]
    assert all(s["status"] == "queued" for s in new_at_start)
    assert syncs_per_source(at_start) == {
        "recent": 1, "overdue": 2, "paused": 1, "off": 1, "queued": 1, "running": 1, "outside the Library": 1,
        "recent playlist": 1, "overdue playlist": 2, "paused playlist": 1,
    }
    # Six hours on, the 6-hourly Channel and Playlist are due; the others either wait on the Sync already queued or
    # aren't checked.
    assert syncs_per_source(later) == syncs_per_source(at_start) | {"recent": 2, "recent playlist": 2}
