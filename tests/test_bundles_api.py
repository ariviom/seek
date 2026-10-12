import errno
import os
import stat
from collections.abc import AsyncIterator, MutableMapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from harness import (
    Gate,
    add_channel,
    add_playlist,
    bundle_config,
    event_stream,
    fake_channel,
    fake_video,
    pause_playlist,
    running,
    said,
    search,
    start_playlist_sync,
    start_sync,
    sync,
    sync_playlist,
    take_out_of_library,
    wait_for_syncs,
)

from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakePlaylist, FakeReranker, FakeTranscriptSource


@pytest.fixture
def sender(tmp_path: Path) -> Config:
    """Whoever exports the Bundle."""
    return bundle_config(tmp_path / "sender")


@pytest.fixture
def friend(tmp_path: Path) -> Config:
    """Whoever imports it."""
    return bundle_config(tmp_path / "friend")


def app_on(config: Config, transcripts: FakeTranscriptSource, embedder: FakeEmbedder | None = None) -> FastAPI:
    return create_app(
        config,
        transcripts,
        embedder or FakeEmbedder(),
        FakeReranker(),
        FakeChatEngine(),
        static_dir=config.data_dir / "none",
    )


def held(config: Config) -> list[Path]:
    """What a started server holds in its temporary directory: a directory for each Bundle it has built and not yet
    sent."""
    return sorted(config.temporary_dir.iterdir())


def mode(path: Path) -> int:
    """Who may read, write, and enter it."""
    return stat.S_IMODE(path.stat().st_mode)


async def import_file(
    client: httpx.AsyncClient, content: bytes, content_type: str | None = "application/octet-stream"
) -> httpx.Response:
    """Sends the bytes to be imported as the web UI sends a file: as the request's whole body."""
    headers = {} if content_type is None else {"Content-Type": content_type}
    return await client.post("/api/bundles", content=content, headers=headers)


async def test_a_channels_bundle_is_built_downloaded_as_a_file_and_imports_into_another_seek(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone")),
        fake_video("v-saws", "Saws", cues=said("Sharpen the saw with a fine file")),
    ]
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)

        built = await client.post(f"/api/channels/{wright['id']}/bundles")
        assert built.status_code == 201, built.text
        report = built.json()
        download = await client.get(f"/api/bundles/{report['id']}")

    assert download.status_code == 200, download.text
    assert report == {
        "id": report["id"],
        "name": "Wood By Wright",
        "videos": 2,
        "segments": 2,
        "size_bytes": len(download.content),
        "playlist_filter_left_out": False,
    }
    assert download.headers["content-type"] == "application/octet-stream"
    assert download.headers["content-length"] == str(len(download.content))
    assert download.headers["content-disposition"] == (
        "attachment; filename=\"Wood By Wright.seek\"; filename*=UTF-8''Wood%20By%20Wright.seek"
    )

    # What was downloaded is the Channel's Bundle: the friend's Seek imports it, sent as the file's bytes.
    async with running(app_on(friend, transcripts)) as client:
        imported = await import_file(client, download.content)
        assert imported.status_code == 200, imported.text
        [channel] = (await client.get("/api/channels")).json()
        found = await search(client, "sharpen the saw with a file")
        # The report's id is the Channel's here, which is what starts its Sync.
        started = await start_sync(client, imported.json()["id"])
        await wait_for_syncs(client)
    assert imported.json() == {
        "kind": "channel",
        "id": channel["id"],
        "name": "Wood By Wright",
        "youtube_id": "UC-wright",
        "created": True,
        "filters": {"published_after": None, "published_before": None, "playlist_id": None, "most_recent": None},
        "added": 2,
        "already_indexed": 0,
        "left_out": {},
    }
    assert (channel["name"], channel["indexed_videos"]) == ("Wood By Wright", 2)
    assert found[0]["youtube_video_id"] == "v-saws"
    assert started["channel_id"] == channel["id"]
    # Nothing of it stays on the sender's disk, nor of the upload on the friend's.
    assert held(sender) == []
    assert held(friend) == []


@pytest.mark.parametrize(
    ("name", "plain", "encoded"),
    [
        ('AC/DC "live"', "AC_DC _live_.seek", "AC_DC%20_live_.seek"),
        ("Sawdust 🪚", "Sawdust _.seek", "Sawdust%20%F0%9F%AA%9A.seek"),
        ("...", "bundle.seek", "bundle.seek"),
        ("a\\b<c>d:e|f?g*h\ti", "a_b_c_d_e_f_g_h_i.seek", "a_b_c_d_e_f_g_h_i.seek"),
        (". Wright .", "Wright.seek", "Wright.seek"),
        ("W" * 150, "W" * 100 + ".seek", "W" * 100 + ".seek"),
    ],
    ids=["a slash and a quote", "an emoji", "nothing but dots", "what Windows forbids", "dots around it", "too long"],
)
async def test_a_bundle_downloads_under_a_file_name_any_system_takes_whatever_the_channel_is_called(
    sender: Config, transcripts: FakeTranscriptSource, name: str, plain: str, encoded: str
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright", name)
        await sync(client, wright)
        built = (await client.post(f"/api/channels/{wright['id']}/bundles")).json()
        download = await client.get(f"/api/bundles/{built['id']}")

    # The report keeps the Channel's name as it is; only the file's is made safe.
    assert built["name"] == name
    assert download.headers["content-disposition"] == f"attachment; filename=\"{plain}\"; filename*=UTF-8''{encoded}"
    assert held(sender) == []


async def test_a_built_bundle_waits_where_only_the_user_can_read_it_and_is_served_once(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        assert held(sender) == []

        first = (await client.post(f"/api/channels/{wright['id']}/bundles")).json()
        second = (await client.post(f"/api/channels/{wright['id']}/bundles")).json()
        waiting = held(sender)
        modes = [mode(sender.temporary_dir), *(mode(directory) for directory in waiting)]
        files = [[mode(file) for file in directory.iterdir()] for directory in waiting]

        served = await client.get(f"/api/bundles/{first['id']}")
        again = await client.get(f"/api/bundles/{first['id']}")
        after_one = held(sender)
        other = await client.get(f"/api/bundles/{second['id']}")
        never_built = await client.get("/api/bundles/not-a-bundle")

    # Inside the data directory, each build in a directory of its own, holding the Bundle and nothing beside it.
    assert sender.temporary_dir.parent == sender.data_dir
    assert modes == [0o700, 0o700, 0o700]
    assert files == [[0o600], [0o600]]
    # Collected under ids nobody could guess.
    assert first["id"] != second["id"]
    assert min(len(first["id"]), len(second["id"])) >= 32
    assert (served.status_code, len(served.content)) == (200, first["size_bytes"])
    assert (again.status_code, again.json()) == (404, {"detail": "That Bundle is not here to download; export it again"})
    assert len(after_one) == 1
    assert other.status_code == 200
    assert never_built.status_code == 404
    assert held(sender) == []


async def test_a_download_that_breaks_partway_leaves_nothing_behind_and_is_not_served_again(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    app = app_on(sender, transcripts)
    async with running(app) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        built = (await client.post(f"/api/channels/{wright['id']}/bundles")).json()
        path = f"/api/bundles/{built['id']}"
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"127.0.0.1:7337")],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 7337),
        }
        started: list[int] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: MutableMapping[str, Any]) -> None:
            # The connection drops once the headers are out, before any of the file.
            if message["type"] == "http.response.start":
                started.append(message["status"])
            else:
                raise OSError("The browser went away")

        with pytest.raises(OSError, match="The browser went away"):
            await app(scope, receive, send)
        again = await client.get(path)

    assert started == [200]
    assert held(sender) == []
    assert again.status_code == 404


async def test_a_paused_channel_exports(sender: Config, transcripts: FakeTranscriptSource) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        assert (await client.patch(f"/api/channels/{wright['id']}", json={"indexed": False})).status_code == 200

        built = await client.post(f"/api/channels/{wright['id']}/bundles")
        download = await client.get(f"/api/bundles/{built.json()['id']}")

    assert (built.status_code, built.json()["videos"]) == (201, 1)
    assert download.status_code == 200
    assert held(sender) == []


async def test_a_channel_exports_what_is_indexed_so_far_while_its_sync_is_running(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    gate = Gate()
    wright_on_youtube = fake_channel(transcripts, "UC-wright")
    wright_on_youtube.videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        wright_on_youtube.videos.append(fake_video("v-saws", "Saws", before_fetch=gate))
        await start_sync(client, wright["id"])
        await gate.wait_entered()

        built = await client.post(f"/api/channels/{wright['id']}/bundles")
        [running_sync, _] = (await client.get("/api/syncs")).json()
        download = await client.get(f"/api/bundles/{built.json()['id']}")
        gate.released.set()
        await wait_for_syncs(client)

    assert running_sync["status"] == "running"
    assert (built.status_code, built.json()["videos"]) == (201, 1)
    assert download.status_code == 200
    assert held(sender) == []


async def test_a_channel_that_shares_its_name_with_another_exports_its_own_videos(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [fake_video("v-chisels", "Chisels"), fake_video("v-saws", "Saws")]
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-knives", "Knives"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright", "Woodworking")
        rex = await add_channel(client, "@rexkrueger", "Woodworking")
        await sync(client, wright, rex)

        of_wright = await client.post(f"/api/channels/{wright['id']}/bundles")
        of_rex = await client.post(f"/api/channels/{rex['id']}/bundles")
        for built in (of_wright, of_rex):
            await client.get(f"/api/bundles/{built.json()['id']}")

    assert (of_wright.status_code, of_wright.json()["name"], of_wright.json()["videos"]) == (201, "Woodworking", 2)
    assert (of_rex.status_code, of_rex.json()["name"], of_rex.json()["videos"]) == (201, "Woodworking", 1)
    assert held(sender) == []


async def test_a_channels_playlist_filter_is_reported_as_left_out(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    transcripts.playlists["PL-joinery"] = FakePlaylist("Joinery", [("UC-wright", "v-chisels")])
    filters = {"published_after": None, "published_before": None, "playlist_id": "PL-joinery", "most_recent": None}
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        assert (await client.patch(f"/api/channels/{wright['id']}", json={"filters": filters})).status_code == 200
        await sync(client, wright)

        built = await client.post(f"/api/channels/{wright['id']}/bundles")
        await client.get(f"/api/bundles/{built.json()['id']}")

    assert built.json()["playlist_filter_left_out"] is True
    assert held(sender) == []


async def test_a_channel_with_no_indexed_videos_is_refused_in_the_commands_sentence(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")

        refused = await client.post(f"/api/channels/{wright['id']}/bundles")

    assert refused.status_code == 422
    assert refused.json() == {"detail": "The Channel 'Wood By Wright' has no indexed Videos to export"}
    assert held(sender) == []


async def test_a_build_the_server_has_nowhere_to_write_is_refused_without_a_path_of_the_servers(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        sender.temporary_dir.chmod(0o500)
        try:
            if os.access(sender.temporary_dir, os.W_OK):
                pytest.skip("The current user/filesystem does not enforce directory write permissions")
            refused = await client.post(f"/api/channels/{wright['id']}/bundles")
        finally:
            sender.temporary_dir.chmod(0o700)

    assert refused.status_code == 422
    # The system's own words for why, and nothing of where.
    assert refused.json() == {"detail": f"Could not write the Bundle: {os.strerror(errno.EACCES)}"}
    assert held(sender) == []


async def test_a_channel_that_is_not_in_the_library_has_no_bundle_to_build(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        take_out_of_library(sender, wright)

        outside = await client.post(f"/api/channels/{wright['id']}/bundles")
        missing = await client.post(f"/api/channels/{wright['id'] + 1}/bundles")

    assert (outside.status_code, outside.json()) == (404, {"detail": f"Channel {wright['id']} not found"})
    assert (missing.status_code, missing.json()) == (404, {"detail": f"Channel {wright['id'] + 1} not found"})
    assert held(sender) == []


def sharpening(transcripts: FakeTranscriptSource) -> None:
    """The playlist PL-sharpening, "Sharpening": Wood By Wright's chisels, then Rex Krueger's knives."""
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone"))
    )
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-knives", "Knives", cues=said("Strop the knife on leather"))
    )
    transcripts.playlists["PL-sharpening"] = FakePlaylist(
        "Sharpening", [("UC-wright", "v-chisels"), ("UC-rex", "v-knives")]
    )


async def test_a_playlists_bundle_is_built_downloaded_as_a_file_and_imports_into_another_seek(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)
    async with running(app_on(sender, transcripts)) as client:
        picks = await add_playlist(client, "PL-sharpening", "Edge picks")
        await sync_playlist(client, picks)

        built = await client.post(f"/api/playlists/{picks['id']}/bundles")
        assert built.status_code == 201, built.text
        report = built.json()
        download = await client.get(f"/api/bundles/{report['id']}")

    assert download.status_code == 200, download.text
    assert report == {
        "id": report["id"],
        "name": "Edge picks",
        "videos": 2,
        "segments": 2,
        "size_bytes": len(download.content),
        "playlist_filter_left_out": False,
    }
    assert download.headers["content-type"] == "application/octet-stream"
    assert download.headers["content-disposition"] == (
        "attachment; filename=\"Edge picks.seek\"; filename*=UTF-8''Edge%20picks.seek"
    )

    # What was downloaded is the Playlist's Bundle: the friend's Seek imports it, as a Playlist.
    async with running(app_on(friend, transcripts)) as client:
        imported = await import_file(client, download.content)
        assert imported.status_code == 200, imported.text
        [playlist] = (await client.get("/api/playlists")).json()
        in_library = (await client.get("/api/channels")).json()
        found = await search(client, "strop the knife on leather")
        started = await start_playlist_sync(client, imported.json()["id"])
        await wait_for_syncs(client)
    assert imported.json() == {
        "kind": "playlist",
        "id": playlist["id"],
        "name": "Edge picks",
        "youtube_id": "PL-sharpening",
        "created": True,
        "filters": None,
        "added": 2,
        "already_indexed": 0,
        "left_out": {},
    }
    assert (playlist["name"], playlist["indexed_videos"]) == ("Edge picks", 2)
    # Its Videos' creators stay outside the Library.
    assert in_library == []
    assert found[0]["youtube_video_id"] == "v-knives"
    assert started["playlist_id"] == playlist["id"]
    assert held(sender) == []
    assert held(friend) == []


async def test_a_paused_playlist_exports(sender: Config, transcripts: FakeTranscriptSource) -> None:
    sharpening(transcripts)
    async with running(app_on(sender, transcripts)) as client:
        picks = await add_playlist(client, "PL-sharpening")
        await sync_playlist(client, picks)
        await pause_playlist(client, picks)

        built = await client.post(f"/api/playlists/{picks['id']}/bundles")
        download = await client.get(f"/api/bundles/{built.json()['id']}")

    assert (built.status_code, built.json()["name"], built.json()["videos"]) == (201, "Sharpening", 2)
    assert download.status_code == 200
    assert held(sender) == []


async def test_a_playlist_exports_what_is_indexed_so_far_while_its_sync_is_running(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    gate = Gate()
    sharpening(transcripts)
    async with running(app_on(sender, transcripts)) as client:
        picks = await add_playlist(client, "PL-sharpening")
        await sync_playlist(client, picks)
        fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-saws", "Saws", before_fetch=gate))
        transcripts.playlists["PL-sharpening"].entries.append(("UC-wright", "v-saws"))
        await start_playlist_sync(client, picks["id"])
        await gate.wait_entered()

        built = await client.post(f"/api/playlists/{picks['id']}/bundles")
        [running_sync, _] = (await client.get("/api/syncs")).json()
        download = await client.get(f"/api/bundles/{built.json()['id']}")
        gate.released.set()
        await wait_for_syncs(client)

    assert running_sync["status"] == "running"
    assert (built.status_code, built.json()["videos"]) == (201, 2)
    assert download.status_code == 200
    assert held(sender) == []


async def test_a_playlist_with_no_indexed_videos_is_refused_in_the_commands_sentence(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)
    async with running(app_on(sender, transcripts)) as client:
        picks = await add_playlist(client, "PL-sharpening")

        refused = await client.post(f"/api/playlists/{picks['id']}/bundles")

    assert refused.status_code == 422
    assert refused.json() == {"detail": "The Playlist 'Sharpening' has no indexed Videos to export"}
    assert held(sender) == []


async def test_a_playlist_that_is_not_there_has_no_bundle_to_build(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)
    async with running(app_on(sender, transcripts)) as client:
        picks = await add_playlist(client, "PL-sharpening")
        await sync_playlist(client, picks)

        missing = await client.post(f"/api/playlists/{picks['id'] + 1}/bundles")

    assert (missing.status_code, missing.json()) == (404, {"detail": f"Playlist {picks['id'] + 1} not found"})
    assert held(sender) == []


async def library(client: httpx.AsyncClient) -> tuple[list[tuple[str, int]], list[tuple[str, int]], list[str]]:
    """What the app shows of its Library: each Channel's and each Playlist's name and count of indexed Videos, and
    the Videos a search for sharpening finds."""
    listed = [
        [(entry["name"], entry["indexed_videos"]) for entry in (await client.get(f"/api/{kind}")).json()]
        for kind in ("channels", "playlists")
    ]
    found = sorted({result["youtube_video_id"] for result in await search(client, "sharpen the chisel on a stone")})
    return listed[0], listed[1], found


async def test_a_file_that_is_not_a_bundle_is_refused_as_the_file_with_nothing_of_where_the_server_put_it(
    friend: Config, transcripts: FakeTranscriptSource
) -> None:
    async with running(app_on(friend, transcripts)) as client:
        notes = await import_file(client, b"Remember to sharpen the chisels")
        nothing = await import_file(client, b"")
        after = await library(client)

    # The sentence is about what was picked: the server's own path for it is in neither.
    assert (notes.status_code, notes.json()) == (422, {"detail": "The file is not a Seek Bundle"})
    assert (nothing.status_code, nothing.json()) == (422, {"detail": "The file is not a Seek Bundle"})
    assert after == ([], [], [])
    assert held(friend) == []


async def bundle_of(client: httpx.AsyncClient, entry: str) -> bytes:
    """The Bundle the app builds of `channels/<id>` or `playlists/<id>`, as the browser would download it."""
    built = await client.post(f"/api/{entry}/bundles")
    assert built.status_code == 201, built.text
    download = await client.get(f"/api/bundles/{built.json()['id']}")
    assert download.status_code == 200, download.text
    return download.content


async def test_a_bundle_embedded_with_another_model_is_refused_in_a_sentence_naming_both(
    friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    sender = replace(bundle_config(tmp_path / "sender"), embedding_model="another-embedder")
    async with running(app_on(sender, transcripts, FakeEmbedder(model_name="another-embedder"))) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        bundle = await bundle_of(client, f"channels/{wright['id']}")

    async with running(app_on(friend, transcripts)) as client:
        refused = await import_file(client, bundle)
        after = await library(client)

    assert refused.status_code == 422
    assert refused.json() == {
        "detail": "The file was embedded with another-embedder (64 dimensions), but this knowledge base uses "
        "fake-embedder (64 dimensions); a Bundle imports only into a knowledge base that uses the same embedding model"
    }
    assert after == ([], [], [])
    assert held(friend) == []


async def test_a_playlist_whose_name_another_playlist_has_is_refused_with_what_to_do_about_it_in_the_web_ui(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)
    transcripts.playlists["PL-other"] = FakePlaylist("Other", [])
    async with running(app_on(sender, transcripts)) as client:
        picks = await add_playlist(client, "PL-sharpening")
        await sync_playlist(client, picks)
        bundle = await bundle_of(client, f"playlists/{picks['id']}")

    async with running(app_on(friend, transcripts)) as client:
        # The friend's own Playlist, named as the Bundle's is but for its capitals.
        await add_playlist(client, "PL-other", "SHARPENING")
        before = await library(client)
        refused = await import_file(client, bundle)
        after = await library(client)

    # No flag of the command's: in the web UI the way out is to rename the Playlist that has the name.
    assert refused.status_code == 409
    assert refused.json() == {
        "detail": "A Playlist named 'SHARPENING' already exists; rename it, then import the file again."
    }
    assert after == before == ([], [("SHARPENING", 0)], [])
    assert held(friend) == []


async def test_a_bundle_of_a_channel_already_in_the_library_fills_it_in_and_leaves_its_name_alone(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    wright_on_youtube = fake_channel(transcripts, "UC-wright")
    wright_on_youtube.videos.append(fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone")))
    async with running(app_on(friend, transcripts)) as client:
        mine = await add_channel(client, "@woodbywright", "Paul's bench")
        await sync(client, mine)
    wright_on_youtube.videos.append(fake_video("v-saws", "Saws", cues=said("Sharpen the saw with a fine file")))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        bundle = await bundle_of(client, f"channels/{wright['id']}")

    async with running(app_on(friend, transcripts)) as client:
        imported = await import_file(client, bundle)
        after = await library(client)

    assert imported.status_code == 200, imported.text
    assert imported.json() == {
        "kind": "channel",
        "id": mine["id"],
        "name": "Paul's bench",
        "youtube_id": "UC-wright",
        "created": False,
        "filters": None,
        "added": 1,
        "already_indexed": 1,
        "left_out": {},
    }
    assert after == ([("Paul's bench", 2)], [], ["v-chisels", "v-saws"])
    assert held(friend) == []


async def test_a_new_channel_arrives_with_its_filters_and_the_report_counts_what_was_left_out_by_its_reason(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos += [
        fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone")),
        fake_video("v-saws", "Saws", listed_duration=900, duration=900),
    ]
    filters = {"published_after": "2025-01-01", "published_before": None, "playlist_id": None, "most_recent": 5}
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        assert (await client.patch(f"/api/channels/{wright['id']}", json={"filters": filters})).status_code == 200
        await sync(client, wright)
        bundle = await bundle_of(client, f"channels/{wright['id']}")

    # The friend's Seek keeps only Videos of twelve minutes and more, which one of the two is not.
    friend = replace(friend, min_duration_seconds=720)
    async with running(app_on(friend, transcripts)) as client:
        imported = await import_file(client, bundle)
        [channel] = (await client.get("/api/channels")).json()

    assert imported.status_code == 200, imported.text
    assert imported.json() == {
        "kind": "channel",
        "id": channel["id"],
        "name": "Wood By Wright",
        "youtube_id": "UC-wright",
        "created": True,
        "filters": filters,
        "added": 1,
        "already_indexed": 0,
        "left_out": {"Shorter than the 720 second minimum": 1},
    }
    assert (channel["filters"], channel["indexed_videos"]) == (filters, 1)
    assert held(friend) == []


async def test_every_open_page_is_told_of_an_imported_channel_and_of_nothing_when_an_import_is_refused(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        bundle = await bundle_of(client, f"channels/{wright['id']}")

    app = app_on(friend, transcripts)
    async with running(app) as client, event_stream(app) as events:
        refused = await import_file(client, b"Remember to sharpen the chisels")
        imported = await import_file(client, bundle)
        # Whatever follows the import on the stream, so that an event the refusal sent would be among them.
        await client.patch("/api/settings", json={"thumbnails": False})
        told = await events.until(lambda event: event["type"] == "settings")

    assert refused.status_code == 422
    # The event a Sync of the Channel sends, on which a page reloads its Channels, Playlists, and Videos table.
    assert told == [{"type": "videos", "channel_id": imported.json()["id"], "playlist_ids": []}, {"type": "settings"}]


async def test_an_imported_playlist_is_told_of_under_each_creator_of_its_videos(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)
    async with running(app_on(sender, transcripts)) as client:
        picks = await add_playlist(client, "PL-sharpening")
        await sync_playlist(client, picks)
        bundle = await bundle_of(client, f"playlists/{picks['id']}")

    app = app_on(friend, transcripts)
    async with running(app) as client, event_stream(app) as events:
        # In the friend's Library already, though the Bundle fills in a Video of its own that was never synced.
        wright = await add_channel(client, "@woodbywright")
        imported = await import_file(client, bundle)
        told = await events.until(lambda event: event["type"] == "videos" and event["channel_id"] != wright["id"])

    playlist_id = imported.json()["id"]
    assert [event for event in told if event["type"] == "videos"] == [
        {"type": "videos", "channel_id": wright["id"], "playlist_ids": [playlist_id]},
        {"type": "videos", "channel_id": told[-1]["channel_id"], "playlist_ids": [playlist_id]},
    ]


async def test_an_upload_arriving_in_pieces_waits_where_only_the_user_can_read_it_and_is_imported_whole(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        bundle = await bundle_of(client, f"channels/{wright['id']}")
    modes: list[list[int]] = []

    async def in_pieces() -> AsyncIterator[bytes]:
        half = len(bundle) // 2
        yield bundle[:half]
        # Asked for the rest, so the first half has been stored: in a directory of the upload's own.
        [directory] = held(friend)
        [file] = directory.iterdir()
        modes.append([mode(friend.temporary_dir), mode(directory), mode(file)])
        yield bundle[half:]

    async with running(app_on(friend, transcripts)) as client:
        imported = await client.post(
            "/api/bundles", content=in_pieces(), headers={"Content-Type": "application/octet-stream"}
        )
        channels, _, _ = await library(client)

    assert modes == [[0o700, 0o700, 0o600]]
    assert (imported.status_code, imported.json()["added"]) == (200, 1)
    assert channels == [("Wood By Wright", 1)]
    assert held(friend) == []


NOT_SENT_AS_A_FILE = {"detail": "A Bundle is imported as the body of the request, sent as application/octet-stream"}


@pytest.mark.parametrize(
    "content_type",
    ["multipart/form-data; boundary=x", "application/x-www-form-urlencoded", "text/plain", "application/json", None],
    ids=["a form with a file", "a form", "text", "JSON", "none"],
)
async def test_a_bundle_sent_as_anything_but_bytes_is_refused_which_is_what_a_form_on_another_site_could_send(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, content_type: str | None
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        bundle = await bundle_of(client, f"channels/{wright['id']}")

    async with running(app_on(friend, transcripts)) as client:
        # A Bundle Seek would import, were it sent as one.
        refused = await import_file(client, bundle, content_type)
        after = await library(client)

    assert (refused.status_code, refused.json()) == (415, NOT_SENT_AS_A_FILE)
    assert after == ([], [], [])
    assert held(friend) == []


async def test_a_body_of_another_content_type_is_refused_before_any_of_it_is_read(
    friend: Config, transcripts: FakeTranscriptSource
) -> None:
    app = app_on(friend, transcripts)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/bundles",
        "raw_path": b"/api/bundles",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1:7337"), (b"content-type", b"text/plain")],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 7337),
    }
    asked_for_the_body: list[bool] = []
    answered: list[int] = []

    async def receive() -> dict[str, Any]:
        asked_for_the_body.append(True)
        return {"type": "http.request", "body": b"Remember to sharpen the chisels", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            answered.append(message["status"])

    async with running(app):
        await app(scope, receive, send)

    assert answered == [415]
    assert asked_for_the_body == []
    assert held(friend) == []


@pytest.mark.parametrize(
    "content_type",
    ["application/octet-stream; charset=binary", "Application/Octet-Stream", "application/octet-stream ;x=y"],
    ids=["a parameter after it", "in capitals", "a space before the parameter"],
)
async def test_a_bundle_imports_whatever_follows_or_however_the_content_type_is_written(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, content_type: str
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        bundle = await bundle_of(client, f"channels/{wright['id']}")

    async with running(app_on(friend, transcripts)) as client:
        imported = await import_file(client, bundle, content_type)
        channels, _, _ = await library(client)

    assert (imported.status_code, imported.json()["added"]) == (200, 1)
    assert channels == [("Wood By Wright", 1)]
    assert held(friend) == []
