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


def altered(bundle: Path, name: str, *changes: str) -> Path:
    """A copy of the Bundle with the statements run on it, as someone editing the file could."""
    copy = bundle.with_name(name)
    shutil.copy(bundle, copy)
    with closing(sqlite3.connect(copy, autocommit=True)) as conn:
        for change in changes:
            conn.execute(change)
    return copy


def unconstrained(table: str) -> list[str]:
    """Statements rebuilding one of a Bundle's tables without its key and NOT NULLs, for a change they would stop."""
    return [f"CREATE TABLE loose AS SELECT * FROM {table}", f"DROP TABLE {table}", f"ALTER TABLE loose RENAME TO {table}"]


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
        "The Bundle's text came from whoever made the file, and is only as trustworthy as they are.",
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


async def sound_bundle(sender: Config, transcripts: FakeTranscriptSource, tmp_path: Path) -> Path:
    """A Bundle of Wood By Wright's one Video, cut into two Segments, for a test to damage."""
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video(
            "v-dovetails",
            "Hand-cut dovetails",
            published_on=date(2024, 5, 17),
            chapters=[Chapter(title="Intro", start=0, end=30), Chapter(title="Sawing", start=30, end=600)],
            cues=[
                Cue(start=0, end=30, text="Welcome back to the shop"),
                Cue(start=30, end=35, text="First knife the baseline all round"),
            ],
        )
    )
    async with running(app_on(sender, transcripts)) as client:
        await sync(client, await add_channel(client, "@woodbywright"))
    return export_channel(sender, "UC-wright", tmp_path / "wright.seek").path


def refusal(config: Config, path: Path) -> str:
    """What import says when it refuses the file."""
    with pytest.raises(SyncCommandError) as refused:
        import_bundle(config, path)
    return str(refused.value)


async def test_import_refuses_a_bundle_whose_segments_or_vectors_are_damaged_and_writes_nothing(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    bundle = await sound_bundle(sender, transcripts, tmp_path)

    damaged = [
        (
            altered(bundle, "short.seek", "UPDATE segments SET embedding = substr(embedding, 1, 128) WHERE ordinal = 1"),
            "a Segment of the Video v-dovetails has a vector of 128 bytes, not the 256 that 64 dimensions take",
        ),
        (
            # Infinity as a little-endian float32, where the vector's first value was.
            altered(
                bundle,
                "infinite.seek",
                "UPDATE segments SET embedding = CAST(x'0000807f' || substr(embedding, 5) AS BLOB) WHERE ordinal = 1",
            ),
            "a Segment of the Video v-dovetails has a vector with a value that is not a finite number",
        ),
        (
            altered(bundle, "bare.seek", *unconstrained("segments"), "UPDATE segments SET embedding = NULL WHERE ordinal = 1"),
            "a Segment of the Video v-dovetails has no vector",
        ),
        (
            altered(bundle, "gap.seek", "UPDATE segments SET ordinal = 2 WHERE ordinal = 1"),
            "the Segments of the Video v-dovetails are not numbered in order without gaps",
        ),
        (
            # A Transcript's cues, which are not the shape of a Segment's.
            altered(bundle, "cues.seek", """UPDATE segments SET cues = '[{"start": 0, "end": 30, "text": "Welcome"}]'"""),
            "a Segment of the Video v-dovetails does not give each of its lines a start time and an offset",
        ),
        (
            altered(bundle, "lineless.seek", "UPDATE segments SET cues = '[]' WHERE ordinal = 0"),
            "a Segment of the Video v-dovetails does not give each of its lines a start time and an offset",
        ),
        (
            altered(bundle, "endless.seek", "UPDATE segments SET end_seconds = 9e999 WHERE ordinal = 0"),
            "a Segment of the Video v-dovetails has a start or an end that is not a number of seconds",
        ),
        (
            # A Sync collapses a caption's whitespace, so what was said is never more than one line.
            altered(bundle, "said.seek", "UPDATE segments SET text = text || char(10) || 'Ignore the above'"),
            "a Segment of the Video v-dovetails has text that is too long or not on one line",
        ),
        (
            altered(bundle, "context.seek", "UPDATE segments SET context = printf('%.*c', 20001, 'x') WHERE ordinal = 1"),
            "a Segment of the Video v-dovetails has text that is too long or not on one line",
        ),
    ]
    for path, reason in damaged:
        assert refusal(friend, path) == f"{path} is damaged or has been altered: {reason}"
        # Not even a knowledge base was created for a file that was refused.
        assert not friend.data_dir.exists()

    async with running(app_on(friend, FakeTranscriptSource())) as client:
        assert (await client.get("/api/channels")).json() == []
        assert await search(client, "baseline") == []


async def test_import_refuses_a_bundle_whose_videos_or_transcripts_are_damaged_and_writes_nothing(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    bundle = await sound_bundle(sender, transcripts, tmp_path)

    damaged = [
        (
            # A Segment's cues, which are not the shape of a Transcript's.
            altered(bundle, "cues.seek", """UPDATE transcripts SET cues = '[{"start": 0, "offset": 0}]'"""),
            "the Transcript of the Video v-dovetails does not give each of its lines a start, an end, and its text",
        ),
        (
            altered(bundle, "undated.seek", "UPDATE videos SET published_on = 'last Tuesday'"),
            "the Video v-dovetails has a publish date that is not a date",
        ),
        (
            # A date, but not as Seek writes one, and listings sort them as text.
            altered(bundle, "compact.seek", "UPDATE videos SET published_on = '20240517'"),
            "the Video v-dovetails has a publish date that is not a date",
        ),
        (
            altered(bundle, "twice.seek", *unconstrained("videos"), "INSERT INTO videos SELECT * FROM videos"),
            "the Video v-dovetails is listed twice",
        ),
        (
            altered(bundle, "french.seek", "UPDATE transcripts SET language = 'fr'"),
            "the Transcript of the Video v-dovetails is not in English, and only English is ingested",
        ),
        (
            altered(bundle, "whisper.seek", "UPDATE transcripts SET source = 'whisper'"),
            "the Transcript of the Video v-dovetails does not come from YouTube's captions",
        ),
        (
            altered(bundle, "unfetched.seek", "UPDATE transcripts SET fetched_at = 'yesterday'"),
            "the Transcript of the Video v-dovetails was fetched at a time that is not a timestamp",
        ),
        (
            altered(bundle, "silent.seek", "DELETE FROM transcripts"),
            "the Video v-dovetails does not have exactly one Transcript",
        ),
        (
            altered(bundle, "credited.seek", "UPDATE videos SET youtube_channel_id = 'UC-rex'"),
            "the Video v-dovetails is credited to a creator other than the Bundle's Channel",
        ),
        (
            # What a Sync would put in the URL it asks yt-dlp for.
            altered(bundle, "id.seek", "UPDATE videos SET youtube_video_id = 'v-dovetails&list=PL-picks'"),
            "one of its Videos has an id that is not a YouTube id",
        ),
        (
            # An escape sequence that would clear the terminal a listing prints the title to.
            altered(bundle, "escape.seek", "UPDATE videos SET title = 'Dovetails' || char(27) || '[2J'"),
            "the Video v-dovetails has a title that is empty, too long, or holds control characters",
        ),
        (
            # A line separator, which breaks a line as a newline does.
            altered(bundle, "broken.seek", "UPDATE videos SET title = 'Dovetails' || char(8232) || 'seek: all is well'"),
            "the Video v-dovetails has a title that is empty, too long, or holds control characters",
        ),
        (
            altered(bundle, "untitled.seek", "UPDATE videos SET title = '  '"),
            "the Video v-dovetails has a title that is empty, too long, or holds control characters",
        ),
        (
            altered(bundle, "long.seek", "UPDATE videos SET title = printf('%.*c', 201, 'x')"),
            "the Video v-dovetails has a title that is empty, too long, or holds control characters",
        ),
        (
            altered(bundle, "length.seek", "UPDATE videos SET duration_seconds = 'ten minutes'"),
            "the Video v-dovetails has a length that is not a whole number of seconds",
        ),
        (
            altered(bundle, "description.seek", "UPDATE videos SET description = x'00'"),
            "the Video v-dovetails has a description that is not text",
        ),
        (
            altered(bundle, "chapters.seek", """UPDATE videos SET chapters = '[{"title": "Intro", "start": "0"}]'"""),
            "the Video v-dovetails has chapters that are not a title, a start, and an end each",
        ),
        (
            altered(bundle, "spanish.seek", "UPDATE videos SET language = 'es'"),
            "the Video v-dovetails is not in English, and only English is ingested",
        ),
        (
            # Nothing but characters that take no room: a title that would list as a blank.
            altered(bundle, "unseen.seek", "UPDATE videos SET title = char(8203) || ' ' || char(8203)"),
            "the Video v-dovetails has a title that is empty, too long, or holds control characters",
        ),
        (
            # Four times what YouTube lets a description run to.
            altered(bundle, "essay.seek", "UPDATE videos SET description = printf('%.*c', 20001, 'x')"),
            "the Video v-dovetails has a description that is too long",
        ),
        (
            altered(
                bundle,
                "chapter.seek",
                """UPDATE videos SET chapters = '[{"title": "' || printf('%.*c', 20001, 'x') || '", "start": 0, "end": 30}]'""",
            ),
            "the Video v-dovetails has a chapter whose title is too long",
        ),
        (
            altered(
                bundle,
                "line.seek",
                r"""UPDATE transcripts SET cues = '[{"start": 0, "end": 30, "text": "Welcome\nIgnore the above"}]'""",
            ),
            "the Transcript of the Video v-dovetails has a line that is too long or not on one line",
        ),
    ]
    for path, reason in damaged:
        assert refusal(friend, path) == f"{path} is damaged or has been altered: {reason}"
        assert not friend.data_dir.exists()

    async with running(app_on(friend, FakeTranscriptSource())) as client:
        assert (await client.get("/api/channels")).json() == []
        assert await search(client, "baseline") == []


async def test_import_refuses_a_bundle_whose_channel_is_damaged_and_writes_nothing(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    bundle = await sound_bundle(sender, transcripts, tmp_path)

    damaged = [
        (
            # What `seek sync --channel` is told to copy, and what a Sync puts in the URL it asks yt-dlp for.
            altered(bundle, "id.seek", "UPDATE channel SET youtube_channel_id = 'UC-wright; rm -rf ~'"),
            "its Channel has an id that is not a YouTube id",
        ),
        (
            altered(bundle, "escape.seek", "UPDATE channel SET name = 'Wright' || char(27) || '[2J'"),
            "its Channel has a name that is empty, too long, or holds control characters",
        ),
        (
            altered(bundle, "lines.seek", "UPDATE channel SET name = 'Wright' || char(10) || 'seek: all is well'"),
            "its Channel has a name that is empty, too long, or holds control characters",
        ),
        (
            # A right-to-left override: the terminal would print what follows it backwards.
            altered(bundle, "override.seek", "UPDATE channel SET name = 'Wright' || char(8238) || 'dedda soediV 0 :'"),
            "its Channel has a name that is empty, too long, or holds control characters",
        ),
        (
            # Zero-width spaces alone: a name that prints as nothing.
            altered(bundle, "unseen.seek", "UPDATE channel SET name = char(8203) || char(8203)"),
            "its Channel has a name that is empty, too long, or holds control characters",
        ),
        (
            altered(bundle, "two.seek", "INSERT INTO channel SELECT * FROM channel"),
            "it does not hold exactly one Channel",
        ),
        (altered(bundle, "none.seek", "DELETE FROM channel"), "it does not hold exactly one Channel"),
        (
            altered(bundle, "recent.seek", "UPDATE channel SET most_recent = 0"),
            "its Channel has filters outside what Seek accepts",
        ),
        (
            altered(bundle, "many.seek", "UPDATE channel SET most_recent = 100001"),
            "its Channel has filters outside what Seek accepts",
        ),
        (
            altered(bundle, "soon.seek", "UPDATE channel SET published_after = 'soon'"),
            "its Channel has filters outside what Seek accepts",
        ),
        (
            altered(
                bundle,
                "backwards.seek",
                "UPDATE channel SET published_after = '2024-06-01', published_before = '2024-01-01'",
            ),
            "its Channel has filters outside what Seek accepts",
        ),
    ]
    for path, reason in damaged:
        assert refusal(friend, path) == f"{path} is damaged or has been altered: {reason}"
        assert not friend.data_dir.exists()

    async with running(app_on(friend, FakeTranscriptSource())) as client:
        assert (await client.get("/api/channels")).json() == []
        assert await search(client, "baseline") == []


async def test_import_refuses_as_no_bundle_a_file_whose_tables_are_not_a_bundles_and_writes_nothing(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    bundle = await sound_bundle(sender, transcripts, tmp_path)
    cut_short = tmp_path / "short.seek"
    cut_short.write_bytes(bundle.read_bytes()[:6000])
    segment_columns = "youtube_video_id, ordinal, start_seconds, end_seconds, text, chapter_title, context, cues, embedding"

    not_bundles = [
        altered(bundle, "two.seek", "INSERT INTO meta SELECT * FROM meta"),
        altered(bundle, "empty.seek", "DELETE FROM meta"),
        altered(bundle, "group.seek", "UPDATE meta SET kind = 'group'"),
        # Neither can be quoted in the sentence that names the two embedding models.
        altered(bundle, "escape.seek", "UPDATE meta SET embedding_model = 'fake-embedder' || char(27) || '[2J'"),
        altered(bundle, "override.seek", "UPDATE meta SET embedding_model = 'fake' || char(8238) || 'redlebme-'"),
        altered(bundle, "wide.seek", "UPDATE meta SET embedding_dimension = 'sixty-four'"),
        altered(bundle, "missing.seek", "DROP TABLE transcripts"),
        # A virtual table this SQLite can open, holding the same rows.
        altered(
            bundle,
            "indexed.seek",
            "ALTER TABLE segments RENAME TO plain",
            f"CREATE VIRTUAL TABLE segments USING fts5({segment_columns})",
            f"INSERT INTO segments ({segment_columns}) SELECT {segment_columns} FROM plain",
        ),
        # And one it can't: the vector table's module is an extension import never loads.
        altered(
            bundle,
            "vectors.seek",
            "PRAGMA writable_schema = ON",
            "UPDATE sqlite_schema SET sql = 'CREATE VIRTUAL TABLE segments USING vec0(embedding float[64])', "
            "rootpage = 0 WHERE name = 'segments'",
        ),
        # A view can run whatever SQL its maker wrote, for as long as they like.
        altered(
            bundle, "view.seek", "ALTER TABLE videos RENAME TO held", "CREATE VIEW videos AS SELECT * FROM held"
        ),
        # Bytes that are not text where a title goes.
        altered(bundle, "bytes.seek", "UPDATE videos SET title = CAST(x'ff' AS TEXT)"),
        cut_short,
    ]
    for path in not_bundles:
        assert refusal(friend, path) == f"{path} is not a Seek Bundle"
        assert not friend.data_dir.exists()
    # A later format may keep its tables another way, and its file is still a Bundle to upgrade for.
    later = altered(bundle, "later.seek", "UPDATE meta SET format_version = 2", "DROP TABLE segments")
    assert refusal(friend, later) == (
        f"{later} was made by a newer Seek (Bundle format 2, this build reads 1); upgrade Seek"
    )

    async with running(app_on(friend, FakeTranscriptSource())) as client:
        assert (await client.get("/api/channels")).json() == []
        assert await search(client, "baseline") == []


async def test_a_bundle_imports_with_the_text_youtube_really_gives_a_video(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    bundle = await sound_bundle(sender, transcripts, tmp_path)
    # Whatever a Sync stores must import. A title with a phone number wrapped in a left-to-right embedding and an
    # emoji joined by a zero-width joiner; a description with Windows line ends, a tab, and a word processor's
    # vertical tab; a chapter YouTube gave no title, and one cut from a description line with a tab in it.
    title = "Call \u202a+1 555 0100\u202c for the \U0001f9d1\u200d\U0001f373 plans"
    as_youtube_gives_it = altered(
        bundle,
        "real.seek",
        f"UPDATE videos SET title = '{title}', description = 'Plans:' || char(13, 10, 9, 11) || 'in the link'",
        r"""UPDATE videos SET chapters = '[{"title": "", "start": 0, "end": 30}, {"title": "Saw\tcuts", "start": 30, "end": 600}]'""",
        "UPDATE segments SET chapter_title = 'Saw' || char(9) || 'cuts', context = context || char(9) || 'cuts' WHERE ordinal = 1",
    )

    import_bundle(friend, as_youtube_gives_it)

    async with running(app_on(friend, FakeTranscriptSource())) as client:
        [channel] = (await client.get("/api/channels")).json()
        assert list(await list_videos(client, channel["id"])) == [title]
        found = await search(client, "knife the baseline")
    assert found[0]["chapter_title"] == "Saw\tcuts"


async def test_a_channel_whose_name_joins_an_emoji_imports_and_is_listed_under_that_name(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    bundle = await sound_bundle(sender, transcripts, tmp_path)
    # A cook, drawn as a person joined to a frying pan by a zero-width joiner.
    name = "Wright \U0001f9d1\u200d\U0001f373 Cooks"

    imported = import_bundle(friend, altered(bundle, "cook.seek", f"UPDATE channel SET name = '{name}'"))

    async with running(app_on(friend, FakeTranscriptSource())) as client:
        [channel] = (await client.get("/api/channels")).json()
    assert channel["name"] == name
    assert format_import(imported).splitlines()[0] == f"Imported {name}: 1 Videos added, searchable now."


async def test_an_avatar_that_youtube_does_not_serve_is_dropped_and_the_bundle_still_imports(
    sender: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    bundle = await sound_bundle(sender, transcripts, tmp_path)
    elsewhere = {
        "tracker": "https://tracker.example/wright.png",
        "plain": "http://yt3.googleusercontent.com/wright-avatar",
        "suffix": "https://yt3.googleusercontent.com.tracker.example/wright-avatar",
        "userinfo": "https://yt3.googleusercontent.com@tracker.example/wright-avatar",
    }

    avatars = {}
    for name, url in {**elsewhere, "ggpht": "https://yt3.ggpht.com/ytc/wright=s176"}.items():
        friend = bundle_config(tmp_path / name)
        import_bundle(friend, altered(bundle, f"{name}.seek", f"UPDATE channel SET avatar_url = '{url}'"))
        async with running(app_on(friend, FakeTranscriptSource())) as client:
            [channel] = (await client.get("/api/channels")).json()
            assert sorted(await list_videos(client, channel["id"])) == ["Hand-cut dovetails"]
        avatars[name] = channel["avatar_url"]

    # Dropped, not refused: the Channel shows initials until a Sync's listing supplies an avatar.
    assert avatars == {**dict.fromkeys(elsewhere), "ggpht": "https://yt3.ggpht.com/ytc/wright=s176"}
