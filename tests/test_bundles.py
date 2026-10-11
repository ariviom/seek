import asyncio
import shutil
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from harness import (
    WRIGHT_AVATAR,
    Gate,
    Synonyms,
    add_channel,
    add_playlist,
    fake_channel,
    fake_video,
    fetched,
    free_port,
    list_playlist_videos,
    list_videos,
    running,
    said,
    search,
    start_sync,
    sync,
    sync_playlist,
    take_out_of_library,
    wait_for_syncs,
)

from seek.app import create_app
from seek.bundles import export_channel, format_export, format_import, import_bundle
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakePlaylist, FakeReranker, FakeTranscriptSource
from seek.ports import Chapter, Cue, VideoUnavailable
from seek.status_command import format_list, list_all
from seek.sync_command import SyncCommandError


def bundle_config(data_dir: Path) -> Config:
    """A Config naming the fake embedder's model, since the commands open the knowledge base with the Config's."""
    return Config(data_dir=data_dir, embedding_model=FakeEmbedder.model_name, embedding_dimension=FakeEmbedder.dimension)


@pytest.fixture
def sender(tmp_path: Path) -> Config:
    """Whoever exports the Bundle."""
    return bundle_config(tmp_path / "sender")


@pytest.fixture
def friend(tmp_path: Path) -> Config:
    """Whoever imports it: a data directory that has never been started."""
    return bundle_config(tmp_path / "friend")


def app_on(config: Config, transcripts: FakeTranscriptSource, embedder: FakeEmbedder | None = None) -> FastAPI:
    return create_app(
        config,
        transcripts,
        embedder or FakeEmbedder(),
        FakeReranker(),
        FakeChatEngine(),
        static_dir=config.data_dir / "no-bundle",
    )


async def test_an_exported_channel_is_listed_searchable_and_citable_where_it_was_never_added(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
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
        ),
        fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone")),
    ]
    async with running(app_on(sender, transcripts)) as client:
        await sync(client, await add_channel(client, "@woodbywright", "Paul Wright"))

    exported = export_channel(sender, "Paul Wright", tmp_path / "wright.seek")
    assert not friend.data_dir.exists()
    import_bundle(friend, exported.path)

    youtube, embedder = FakeTranscriptSource(), Synonyms()
    async with running(app_on(friend, youtube, embedder)) as client:
        [channel] = (await client.get("/api/channels")).json()
        by_words = await search(client, "which side of the line does the kerf go")
        by_vector = await search(client, "hone")

    assert channel == {
        "id": channel["id"],
        "youtube_channel_id": "UC-wright",
        "name": "Paul Wright",
        "indexed": True,
        "filters": {"published_after": None, "published_before": None, "playlist_id": None, "most_recent": None},
        "check_every_hours": 24,
        "indexed_videos": 2,
        "failed_videos": 0,
        "excluded_videos": 0,
        "last_synced_at": None,
        "avatar_url": WRIGHT_AVATAR,
    }
    assert by_words[0] == {
        "segment_id": by_words[0]["segment_id"],
        "text": (
            "First knife the baseline all round Now the saw does the work Keep the kerf on the waste side of the line"
        ),
        "start_seconds": 30.0,
        "matched_seconds": 41.5,
        "video_id": by_words[0]["video_id"],
        "youtube_video_id": "v-dovetails",
        "video_title": "Hand-cut dovetails",
        "published_on": "2024-05-17",
        "chapter_title": "Sawing",
        "channel_id": channel["id"],
        "channel_name": "Paul Wright",
        "playlist_ids": [],
        "score": by_words[0]["score"],
        "url": "https://www.youtube.com/watch?v=v-dovetails&t=41s",
    }
    assert format_export(replace(exported, size_bytes=98_400_000)).splitlines() == [
        f"Exported Paul Wright to {tmp_path / 'wright.seek'}: 2 Videos, 3 Segments, 98.4 MB.",
        "The file contains the creators' full Transcripts, so choose who you share it with.",
    ]
    # No Segment says "hone", so only its vector, filed under the right Segment, puts this one first.
    assert by_vector[0]["youtube_video_id"] == "v-chisels"
    # Nothing was fetched from YouTube and nothing embedded.
    assert youtube.calls == []
    assert embedder.passages == []


async def test_a_channels_date_range_and_most_recent_count_travel_and_its_playlist_filter_is_left_out(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels", published_on=date(2024, 6, 1)))
    transcripts.playlists["PL-joinery"] = FakePlaylist("Joinery", [("UC-wright", "v-chisels")])
    filters = {
        "published_after": "2023-01-01",
        "published_before": "2024-12-31",
        "playlist_id": "PL-joinery",
        "most_recent": 25,
    }
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        assert (await client.patch(f"/api/channels/{wright['id']}", json={"filters": filters})).status_code == 200
        await sync(client, wright)

    exported = export_channel(sender, "UC-wright", tmp_path / "wright.seek")
    import_bundle(friend, exported.path)

    async with running(app_on(friend, FakeTranscriptSource())) as client:
        [channel] = (await client.get("/api/channels")).json()
    assert channel["filters"] == filters | {"playlist_id": None}
    assert format_export(exported).splitlines()[-1] == (
        "The Channel's Playlist filter was left out, so the recipient's Syncs will bring in its other Videos."
    )


async def test_a_bundle_holds_the_channels_searchable_videos_even_one_with_nothing_said_and_even_when_paused(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone")),
        # Captions that are all blank: done, with no Segments.
        fake_video("v-silent", "Silent build", cues=said(" ")),
        fake_video("v-members", "Members stream", failure=VideoUnavailable("Members-only video", permanent=True)),
        fake_video("v-tip", "Quick tip", listed_duration=60, duration=60),
    ]
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await start_sync(client, wright["id"])
        await wait_for_syncs(client)
        stages = {title: video["stage"] for title, video in (await list_videos(client, wright["id"])).items()}
        assert (await client.patch(f"/api/channels/{wright['id']}", json={"indexed": False})).status_code == 200

    exported = export_channel(sender, "Wood By Wright", tmp_path / "wright.seek")
    imported = import_bundle(friend, exported.path)

    async with running(app_on(friend, FakeTranscriptSource())) as client:
        [channel] = (await client.get("/api/channels")).json()
        arrived = {title: video["stage"] for title, video in (await list_videos(client, channel["id"])).items()}
    assert stages == {"Chisels": "done", "Silent build": "done", "Members stream": "failed", "Quick tip": "excluded"}
    assert arrived == {"Chisels": "done", "Silent build": "done"}
    assert (exported.videos, exported.segments, imported.added) == (2, 1, 2)
    # Pause state does not travel.
    assert channel["indexed"] is True


async def test_the_sync_after_an_import_fetches_only_videos_the_bundle_did_not_carry(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    carried = [
        fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone")),
        fake_video("v-silent", "Silent build", cues=said(" ")),
    ]
    fake_channel(transcripts, "UC-wright").videos += carried
    async with running(app_on(sender, transcripts)) as client:
        await sync(client, await add_channel(client, "@woodbywright"))
    exported = export_channel(sender, "Wood By Wright", tmp_path / "wright.seek")
    import_bundle(friend, exported.path)

    # The friend's own view of YouTube, where the Channel has published since.
    youtube = FakeTranscriptSource(channels=[replace(c, videos=[]) for c in transcripts.channels])
    fake_channel(youtube, "UC-wright").videos += [
        *carried,
        fake_video("v-saws", "Saws", published_on=date(2025, 4, 1), cues=said("Sharpen the saw with a fine file")),
    ]
    before = format_list(await list_all(replace(friend, port=free_port())))
    async with running(app_on(friend, youtube)) as client:
        [channel] = (await client.get("/api/channels")).json()
        await sync(client, channel)
        stages = {title: video["stage"] for title, video in (await list_videos(client, channel["id"])).items()}
        found = {r["youtube_video_id"] for r in await search(client, "sharpen with something fine")}

    assert before.splitlines() == [
        "Channels:",
        "  Wood By Wright (UC-wright): 2 ready, 0 failed, 0 excluded; never synced",
    ]
    assert fetched(youtube) == ["v-saws"]
    assert stages == {"Chisels": "done", "Silent build": "done", "Saws": "done"}
    assert found == {"v-chisels", "v-saws"}


async def test_export_adds_the_seek_extension_and_never_replaces_a_file(
    sender: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        await sync(client, await add_channel(client, "@woodbywright"))
    out = tmp_path / "out"
    out.mkdir()

    exported = export_channel(sender, "UC-wright", out / "wright")
    written = exported.path.read_bytes()
    with pytest.raises(SyncCommandError, match="wright.seek already exists"):
        export_channel(sender, "UC-wright", out / "wright")
    with pytest.raises(SyncCommandError, match="wright.seek already exists"):
        export_channel(sender, "UC-wright", out / "wright.seek")

    assert exported.path == out / "wright.seek"
    assert exported.size_bytes == len(written)
    assert [file.name for file in out.iterdir()] == ["wright.seek"]
    assert exported.path.read_bytes() == written


async def test_export_refuses_what_it_cannot_export_and_leaves_no_file_behind(
    sender: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-knives", "Knives"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright", "Wright")
        rex = await add_channel(client, "@rexkrueger")
        await sync(client, wright, rex)
        # Never synced, so it has nothing indexed.
        await add_channel(client, "@wrightvlogs", "Wright")
    take_out_of_library(sender, rex)
    out = tmp_path / "out"
    out.mkdir()

    refused = [
        ("UC-wright-vlog", out / "vlogs.seek", "The Channel 'Wright' has no indexed Videos to export"),
        ("Paul Sellers", out / "sellers.seek", "No Channel named 'Paul Sellers'"),
        ("wright", out / "wright.seek", "More than one Channel is named 'wright'.*UC-wright, UC-wright-vlog"),
        # A Channel outside the Library, there only to credit a Playlist's Videos.
        ("UC-rex", out / "rex.seek", "No Channel named 'UC-rex'"),
        ("UC-wright", out / "missing" / "wright.seek", "Could not write .*wright.seek"),
        ("UC-wright", out, "out is a directory; give the file to write the Bundle to"),
    ]
    for channel, path, message in refused:
        with pytest.raises(SyncCommandError, match=message):
            export_channel(sender, channel, path)
    # As the server refuses to start on a knowledge base embedded with another model.
    with pytest.raises(SyncCommandError, match="was embedded with fake-embedder"):
        export_channel(replace(sender, embedding_model="another-embedder"), "UC-wright", out / "wright.seek")

    assert list(out.iterdir()) == []


async def test_export_runs_beside_the_server_while_a_sync_holds_the_lease(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    gate = Gate()
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-saws", "Saws", before_fetch=gate))
        await start_sync(client, wright["id"])
        await gate.wait_entered()
        exported = await asyncio.to_thread(export_channel, sender, "UC-wright", tmp_path / "wright.seek")
        gate.released.set()
        await wait_for_syncs(client)
    import_bundle(friend, exported.path)

    async with running(app_on(friend, FakeTranscriptSource())) as client:
        [channel] = (await client.get("/api/channels")).json()
        arrived = {title: video["stage"] for title, video in (await list_videos(client, channel["id"])).items()}
    # Only what was searchable when the export read the knowledge base.
    assert arrived == {"Chisels": "done"}


def altered(bundle: Path, name: str, change: str) -> Path:
    """A copy of the Bundle with one statement run on it, as someone editing the file could."""
    copy = bundle.with_name(name)
    shutil.copy(bundle, copy)
    with closing(sqlite3.connect(copy, autocommit=True)) as conn:
        conn.execute(change)
    return copy


async def test_import_refuses_a_file_it_cannot_read_as_a_bundle_and_writes_nothing(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        await sync(client, await add_channel(client, "@woodbywright"))
    bundle = export_channel(sender, "UC-wright", tmp_path / "wright.seek").path
    notes = tmp_path / "notes.seek"
    notes.write_text("Remember to sharpen the chisels")
    other_database = tmp_path / "other.seek"
    with closing(sqlite3.connect(other_database, autocommit=True)) as conn:
        conn.execute("CREATE TABLE meta (format_version INTEGER)")
        conn.execute("INSERT INTO meta VALUES (1)")

    refused = [
        (notes, "notes.seek is not a Seek Bundle"),
        (tmp_path / "nowhere.seek", "nowhere.seek is not a Seek Bundle"),
        # A SQLite file that does not carry Seek's application id.
        (other_database, "other.seek is not a Seek Bundle"),
        (altered(bundle, "unmarked.seek", "PRAGMA application_id = 0"), "unmarked.seek is not a Seek Bundle"),
        (
            altered(bundle, "newer.seek", "UPDATE meta SET format_version = 2"),
            r"newer.seek was made by a newer Seek \(Bundle format 2, this build reads 1\); upgrade Seek",
        ),
        (
            altered(bundle, "model.seek", "UPDATE meta SET embedding_model = 'another-embedder'"),
            r"model.seek was embedded with another-embedder \(64 dimensions\), but this knowledge base uses "
            r"fake-embedder \(64 dimensions\)",
        ),
        (
            altered(bundle, "dimension.seek", "UPDATE meta SET embedding_dimension = 32"),
            r"dimension.seek was embedded with fake-embedder \(32 dimensions\), but this knowledge base uses "
            r"fake-embedder \(64 dimensions\)",
        ),
    ]
    for path, message in refused:
        with pytest.raises(SyncCommandError, match=message):
            import_bundle(friend, path)
    # Not even a knowledge base was created for a file that was refused.
    assert not friend.data_dir.exists()
    # As the server refuses to start on a knowledge base embedded with another model.
    with pytest.raises(SyncCommandError, match="The knowledge base was embedded with fake-embedder"):
        import_bundle(replace(sender, embedding_model="another-embedder"), tmp_path / "model.seek")

    async with running(app_on(friend, FakeTranscriptSource())) as client:
        assert (await client.get("/api/channels")).json() == []
        assert await search(client, "chisels") == []


async def test_import_says_what_it_added_and_what_to_do_next_and_refuses_a_channel_already_known(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [fake_video("v-chisels", "Chisels"), fake_video("v-saws", "Saws")]
    async with running(app_on(sender, transcripts)) as client:
        await sync(client, await add_channel(client, "@woodbywright", "Paul Wright"))
    bundle = export_channel(sender, "UC-wright", tmp_path / "wright.seek").path

    imported = import_bundle(friend, bundle)
    with pytest.raises(SyncCommandError, match="already has the Channel 'Paul Wright'"):
        import_bundle(friend, bundle)

    assert format_import(imported).splitlines() == [
        "Imported Paul Wright: 2 Videos added, searchable now.",
        "Next, start a Sync to pick up the Videos published since: seek sync --channel UC-wright",
    ]
    async with running(app_on(friend, FakeTranscriptSource())) as client:
        [channel] = (await client.get("/api/channels")).json()
        assert sorted(await list_videos(client, channel["id"])) == ["Chisels", "Saws"]


async def test_an_imported_segment_is_found_by_its_words_beyond_the_nearest_vectors(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        *(fake_video(f"v-technique-{n}", f"Technique {n}", cues=said("technique")) for n in range(60)),
        fake_video("v-domino", "Loose tenons", cues=said("the domino joiner makes loose tenons quickly for many other jobs")),
    ]
    async with running(app_on(sender, transcripts)) as client:
        await sync(client, await add_channel(client, "@woodbywright"))
    import_bundle(friend, export_channel(sender, "UC-wright", tmp_path / "wright.seek").path)

    async with running(app_on(friend, FakeTranscriptSource())) as client:
        # Every "technique" Segment is nearer the query than the long one naming the tool, so only the lexical
        # index, kept in step as the Segments were inserted, brings that one in.
        results = await search(client, "domino joiner technique")

    assert results[0]["youtube_video_id"] == "v-domino"


async def test_import_refuses_a_bundle_whose_videos_the_library_credits_to_another_channel_and_writes_nothing(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        await sync(client, await add_channel(client, "@woodbywright"))
    bundle = export_channel(sender, "UC-wright", tmp_path / "wright.seek").path
    # The friend's Playlist already includes that Video, which their YouTube listing credits to Rex Krueger.
    youtube = FakeTranscriptSource(channels=[replace(c, videos=[]) for c in transcripts.channels])
    fake_channel(youtube, "UC-rex").videos.append(fake_video("v-chisels", "Chisels"))
    youtube.playlists["PL-picks"] = FakePlaylist("Sharpening picks", [("UC-rex", "v-chisels")])
    async with running(app_on(friend, youtube)) as client:
        playlist = await add_playlist(client, "PL-picks")
        await sync_playlist(client, playlist)

    with pytest.raises(SyncCommandError, match=r"already has the Channel 'Wood By Wright' \(UC-wright\) or some"):
        import_bundle(friend, bundle)

    async with running(app_on(friend, youtube)) as client:
        assert (await client.get("/api/channels")).json() == []
        [video] = await list_playlist_videos(client, playlist["id"])
    assert (video["title"], video["channel_name"], video["stage"]) == ("Chisels", "Rex Krueger", "done")
