import asyncio
import errno
import io
import json
import logging
import os
import sqlite3
import stat
import time
from collections.abc import AsyncIterator, MutableMapping
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from harness import (
    Gate,
    add_channel,
    add_playlist,
    altered,
    app_on,
    bundle_config,
    event_stream,
    fake_channel,
    fake_video,
    pause_playlist,
    query,
    running,
    said,
    search,
    serving,
    start_playlist_sync,
    start_sync,
    sync,
    sync_playlist,
    take_out_of_library,
    wait_for_syncs,
)

from seek import bundles_api, syncs
from seek.bundles import ImportReport, import_bundle
from seek.config import Config
from seek.db import Database
from seek.fakes import FakeEmbedder, FakePlaylist, FakeTranscriptSource
from seek.videos import Source


def held(config: Config) -> list[Path]:
    """What a started server holds in its temporary directory: a directory for each Bundle it has built and not yet
    sent, and for each upload it has not finished with."""
    return sorted(config.temporary_dir.iterdir())


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


async def import_file(
    client: httpx.AsyncClient, content: bytes, content_type: str | None = "application/octet-stream"
) -> httpx.Response:
    """Sends the bytes as the web UI sends a file: as the request's whole body."""
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
        ("W" * 98 + ". " + "W" * 50, "W" * 98 + ".seek", "W" * 98 + ".seek"),
    ],
    ids=[
        "a slash and a quote",
        "an emoji",
        "nothing but dots",
        "what Windows forbids",
        "dots around it",
        "too long",
        "a dot and a space where it is cut",
    ],
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


async def test_a_request_for_a_built_bundles_headers_alone_leaves_it_to_be_collected(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        built = (await client.post(f"/api/channels/{wright['id']}/bundles")).json()

        # As a download manager asks before it fetches.
        probed = await client.head(f"/api/bundles/{built['id']}")
        waiting = held(sender)
        collected = await client.get(f"/api/bundles/{built['id']}")
        gone = await client.head(f"/api/bundles/{built['id']}")

    assert (probed.status_code, probed.content) == (200, b"")
    assert probed.headers["content-length"] == str(built["size_bytes"])
    assert probed.headers["content-disposition"] == (
        "attachment; filename=\"Wood By Wright.seek\"; filename*=UTF-8''Wood%20By%20Wright.seek"
    )
    assert len(waiting) == 1
    assert (collected.status_code, len(collected.content)) == (200, built["size_bytes"])
    assert gone.status_code == 404
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


@pytest.mark.parametrize(
    ("change", "sentence"),
    [
        (
            "UPDATE segments SET end_seconds = 9e999",
            "The file is damaged or has been altered: a Segment of the Video v-chisels has a start or an end that is "
            "not a number of seconds",
        ),
        (
            "UPDATE meta SET format_version = 2",
            "The file was made by a newer Seek (Bundle format 2, this build reads 1); upgrade Seek",
        ),
    ],
    ids=["damaged", "made by a newer Seek"],
)
async def test_a_bundle_that_import_refuses_once_it_has_read_it_is_refused_as_the_file_with_no_path_of_the_servers(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path, change: str, sentence: str
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        downloaded = tmp_path / "wright.seek"
        downloaded.write_bytes(await bundle_of(client, f"channels/{wright['id']}"))

    async with running(app_on(friend, transcripts)) as client:
        refused = await import_file(client, altered(downloaded, "changed.seek", change).read_bytes())
        after = await library(client)

    assert (refused.status_code, refused.json()) == (422, {"detail": sentence})
    assert str(friend.data_dir) not in refused.text
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


async def wrights_bundle(sender: Config, transcripts: FakeTranscriptSource) -> bytes:
    """The Bundle a sender's Seek builds of Wood By Wright, whose one Video is on sharpening chisels."""
    fake_channel(transcripts, "UC-wright").videos.append(
        fake_video("v-chisels", "Chisels", cues=said("Sharpen the chisel on a fine stone"))
    )
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        return await bundle_of(client, f"channels/{wright['id']}")


async def in_halves(content: bytes, read: list[int]) -> AsyncIterator[bytes]:
    """The file in two pieces, each noted once the server has asked for what follows it: it read the file to its
    end when both are."""
    half = len(content) // 2
    for piece in (content[:half], content[half:]):
        yield piece
        read.append(len(piece))


AS_A_FILE = {"Content-Type": "application/octet-stream"}
SYNC_IN_THE_WAY = {"detail": "A Sync is running or waiting to run; import when it has finished."}


async def test_an_import_is_refused_while_a_sync_is_running_and_accepted_once_it_has_finished(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    bundle = await wrights_bundle(sender, transcripts)
    gate = Gate()
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-knives", "Knives", before_fetch=gate))
    read: list[int] = []
    async with running(app_on(friend, transcripts)) as client:
        rex = await add_channel(client, "@rexkrueger")
        await start_sync(client, rex["id"])
        await gate.wait_entered()
        before = await library(client)

        refused = await client.post("/api/bundles", content=in_halves(bundle, read), headers=AS_A_FILE)
        after = await library(client)
        stored = held(friend)
        gate.released.set()
        await wait_for_syncs(client)
        later = await import_file(client, bundle)

    # The server's own sentence, not the command's: it refuses before the import function is asked.
    assert (refused.status_code, refused.json()) == (409, SYNC_IN_THE_WAY)
    # Read to its end all the same, so the browser gets the sentence and not a dropped connection, and discarded.
    assert sum(read) == len(bundle)
    assert stored == []
    assert after == before == ([("Rex Krueger", 0)], [], [])
    assert (later.status_code, later.json()["added"]) == (200, 1)
    assert held(friend) == []


async def test_an_import_is_refused_for_as_long_as_a_sync_waits_to_run_though_none_is_running(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    bundle = await wrights_bundle(sender, transcripts)
    fake_channel(transcripts, "UC-rex").videos.append(
        fake_video("v-knives", "Knives", cues=said("Strop the knife on leather"))
    )
    # A Sync stays queued while the embedding model loads, which on a first run is a download.
    loading = Gate()
    read: list[int] = []
    async with running(app_on(friend, transcripts, FakeEmbedder(before_load=loading))) as client:
        rex = await add_channel(client, "@rexkrueger")
        await start_sync(client, rex["id"])
        await loading.wait_entered()
        waiting = [s["status"] for s in (await client.get("/api/syncs")).json()]

        refused = await client.post("/api/bundles", content=in_halves(bundle, read), headers=AS_A_FILE)
        still_waiting = [s["status"] for s in (await client.get("/api/syncs")).json()]
        stored = held(friend)
        loading.released.set()
        await wait_for_syncs(client)
        # Nothing can be searched while the model loads, so the Library is looked at once it has.
        after = await library(client)

    assert waiting == still_waiting == ["queued"]
    assert (refused.status_code, refused.json()) == (409, SYNC_IN_THE_WAY)
    assert sum(read) == len(bundle)
    assert stored == []
    # Rex Krueger's Sync ran; nothing of Wood By Wright's Bundle is there.
    assert after == ([("Rex Krueger", 1)], [], ["v-knives"])
    assert held(friend) == []


class Paused:
    """A file sent as a body that pauses before its last chunk, which holds its import open as an upload still
    arriving, for the test to end when it likes."""

    def __init__(self, content: bytes) -> None:
        self._content = content
        # Set once the server has asked for the last chunk, so it has taken the import on and stored the first.
        self.arriving = asyncio.Event()
        self.let_go = asyncio.Event()

    async def chunks(self) -> AsyncIterator[bytes]:
        half = len(self._content) // 2
        yield self._content[:half]
        self.arriving.set()
        await self.let_go.wait()
        yield self._content[half:]

    def sent_to(self, client: httpx.AsyncClient) -> asyncio.Task[httpx.Response]:
        return asyncio.create_task(client.post("/api/bundles", content=self.chunks(), headers=AS_A_FILE))


ANOTHER_IMPORT = {"detail": "Another import is running; try again when it has finished."}


@pytest.mark.parametrize("first_is_a_bundle", [True, False], ids=["which completes", "which is refused"])
async def test_a_second_import_is_refused_while_one_is_uploading_and_a_later_one_accepted_once_it_has_ended(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, first_is_a_bundle: bool
) -> None:
    bundle = await wrights_bundle(sender, transcripts)
    first = Paused(bundle if first_is_a_bundle else b"Remember to sharpen the chisels")
    read: list[int] = []
    async with running(app_on(friend, transcripts)) as client:
        uploading = first.sent_to(client)
        await asyncio.wait_for(first.arriving.wait(), 5)
        before = await library(client)

        refused = await client.post("/api/bundles", content=in_halves(bundle, read), headers=AS_A_FILE)
        after = await library(client)
        stored = held(friend)
        first.let_go.set()
        ended = await uploading
        later = await import_file(client, bundle)

    assert (refused.status_code, refused.json()) == (409, ANOTHER_IMPORT)
    # Read to its end and discarded: the one upload stored is the first's.
    assert sum(read) == len(bundle)
    assert len(stored) == 1
    assert after == before == ([], [], [])
    # However the first ended, it no longer holds the place of the one import.
    if first_is_a_bundle:
        assert (ended.status_code, ended.json()["added"]) == (200, 1)
        assert (later.status_code, later.json()["added"], later.json()["already_indexed"]) == (200, 0, 1)
    else:
        assert (ended.status_code, ended.json()) == (422, {"detail": "The file is not a Seek Bundle"})
        assert (later.status_code, later.json()["added"], later.json()["already_indexed"]) == (200, 1, 0)
    assert held(friend) == []


async def test_a_sync_that_starts_while_the_file_is_still_arriving_refuses_the_import_in_the_commands_sentence(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    bundle = await wrights_bundle(sender, transcripts)
    gate = Gate()
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-knives", "Knives", before_fetch=gate))
    upload = Paused(bundle)
    async with running(app_on(friend, transcripts)) as client:
        rex = await add_channel(client, "@rexkrueger")
        uploading = upload.sent_to(client)
        await asyncio.wait_for(upload.arriving.wait(), 5)
        # Nothing was running or queued when the server looked, so the upload was taken on.
        await start_sync(client, rex["id"])
        await gate.wait_entered()
        before = await library(client)

        upload.let_go.set()
        refused = await uploading
        after = await library(client)
        gate.released.set()
        await wait_for_syncs(client)

    # The Sync lease is what refuses it, as it refuses `seek import`.
    assert refused.status_code == 422
    assert refused.json() == {"detail": "A Sync is running; run the import again when it has finished"}
    assert after == before == ([("Rex Krueger", 0)], [], [])
    assert held(friend) == []


async def test_a_sync_queued_while_an_import_ran_starts_when_the_import_ends_without_waiting_for_the_poll(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    bundle = await wrights_bundle(sender, transcripts)
    fake_channel(transcripts, "UC-rex").videos.append(fake_video("v-knives", "Knives"))
    upload = Paused(bundle)
    # An hour between the worker's looks at the queue: within the test, only being woken starts a Sync.
    async with running(app_on(friend, transcripts, sync_poll_seconds=3600)) as client:
        rex = await add_channel(client, "@rexkrueger")
        uploading = upload.sent_to(client)
        await asyncio.wait_for(upload.arriving.wait(), 5)
        # Queued as another seek process queues one, which tells the server nothing: the worker sleeps on.
        await Database(friend.database_path).run(lambda conn: syncs.enqueue(conn, Source("channel", rex["id"])))
        waiting = [s["status"] for s in (await client.get("/api/syncs")).json()]

        upload.let_go.set()
        imported = await uploading
        [started] = await wait_for_syncs(client)

    assert waiting == ["queued"]
    assert (imported.status_code, imported.json()["added"]) == (200, 1)
    assert (started["channel_id"], started["status"]) == (rex["id"], "done")


async def test_an_upload_the_server_has_nowhere_to_store_is_refused_as_the_file_without_a_path_of_the_servers(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    bundle = await wrights_bundle(sender, transcripts)
    read: list[int] = []
    async with running(app_on(friend, transcripts)) as client:
        friend.temporary_dir.chmod(0o500)
        try:
            if os.access(friend.temporary_dir, os.W_OK):
                pytest.skip("The current user/filesystem does not enforce directory write permissions")
            refused = await client.post("/api/bundles", content=in_halves(bundle, read), headers=AS_A_FILE)
        finally:
            friend.temporary_dir.chmod(0o700)
        later = await import_file(client, bundle)

    # A sentence of Seek's, where a failure with none has the page blame a proxy: the system's own words for why,
    # and nothing of where.
    assert refused.status_code == 422
    assert refused.json() == {"detail": f"The file could not be stored: {os.strerror(errno.EACCES)}"}
    assert sum(read) == len(bundle)
    assert (later.status_code, later.json()["added"]) == (200, 1)
    assert held(friend) == []


class NoRoom(io.FileIO):
    """A file on a disk that has filled: it is created, and nothing can be written to it."""

    def write(self, data: object) -> int:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))


async def test_an_upload_the_disk_has_no_room_for_is_refused_the_same_way_and_what_was_stored_is_deleted(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = await wrights_bundle(sender, transcripts)
    read: list[int] = []
    async with running(app_on(friend, transcripts)) as client:
        # No disk is filled for the test: the server's one way of creating an upload's file gives it this one.
        monkeypatch.setattr(bundles_api, "_create", lambda path: NoRoom(path, "x"))
        refused = await client.post("/api/bundles", content=in_halves(bundle, read), headers=AS_A_FILE)
        stored = held(friend)
        monkeypatch.undo()
        later = await import_file(client, bundle)

    assert refused.status_code == 422
    assert refused.json() == {"detail": f"The file could not be stored: {os.strerror(errno.ENOSPC)}"}
    # The first half was refused by the disk, and the rest was read all the same and kept nowhere.
    assert sum(read) == len(bundle)
    assert stored == []
    assert (later.status_code, later.json()["added"]) == (200, 1)
    assert held(friend) == []


async def test_an_import_whose_channel_leaves_the_library_as_it_ends_says_that_it_finished_and_the_channel_is_gone(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = await wrights_bundle(sender, transcripts)

    def then_removed(config: Config, path: Path, called: str) -> ImportReport:
        report = import_bundle(config, path, called=called)
        # What a Remove pressed on another page does when it lands after the import's last write and before the
        # server looks the Channel up, a moment no test can otherwise reach.
        [channel] = query(config, "SELECT id FROM channels")
        take_out_of_library(config, {"id": channel["id"]})
        return report

    monkeypatch.setattr(bundles_api, "import_bundle", then_removed)
    async with running(app_on(friend, transcripts)) as client:
        answered = await import_file(client, bundle)
        channels, _, _ = await library(client)

    assert answered.status_code == 404
    assert answered.json() == {
        "detail": "The import finished, but the Channel 'Wood By Wright' is no longer in the Library"
    }
    assert channels == []
    assert held(friend) == []


def too_large(cap: str) -> dict[str, str]:
    return {"detail": f"The file is larger than {cap}, the most the web UI imports; import it with `seek import`."}


async def test_a_file_declared_larger_than_the_cap_is_refused_with_the_way_to_import_it_all_the_same(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    bundle = await wrights_bundle(sender, transcripts)
    async with running(app_on(friend, transcripts, bundle_upload_cap_bytes=1000)) as client:
        # A Bundle Seek would import, were it not some tens of times the most this one takes.
        refused = await import_file(client, bundle)
        after = await library(client)

    assert int(refused.request.headers["content-length"]) == len(bundle) > 1000
    assert (refused.status_code, refused.json()) == (413, too_large("1 KB"))
    assert after == ([], [], [])
    assert held(friend) == []


async def test_a_length_declared_over_2_gb_is_refused_at_once_without_any_of_the_body_being_read(
    friend: Config, transcripts: FakeTranscriptSource
) -> None:
    # The cap a server has unless it is told another, and one byte more than it.
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
        "headers": [
            (b"host", b"127.0.0.1:7337"),
            (b"content-type", b"application/octet-stream"),
            (b"content-length", b"2000000001"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 7337),
    }
    asked_for_the_body: list[bool] = []
    answered: list[int] = []
    said_why = b""

    async def receive() -> dict[str, Any]:
        asked_for_the_body.append(True)
        return {"type": "http.request", "body": b"The first of a great many bytes", "more_body": True}

    async def send(message: MutableMapping[str, Any]) -> None:
        nonlocal said_why
        if message["type"] == "http.response.start":
            answered.append(message["status"])
        else:
            said_why += message.get("body", b"")

    async with running(app):
        await app(scope, receive, send)

    assert answered == [413]
    assert json.loads(said_why) == too_large("2 GB")
    assert asked_for_the_body == []
    assert held(friend) == []


async def test_a_file_that_passes_the_cap_without_declaring_its_length_is_refused_and_what_was_stored_deleted(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    bundle = await wrights_bundle(sender, transcripts)
    read: list[int] = []
    async with running(app_on(friend, transcripts, bundle_upload_cap_bytes=1000)) as client:
        refused = await client.post("/api/bundles", content=in_halves(bundle, read), headers=AS_A_FILE)
        after = await library(client)
        stored = held(friend)
        # It no longer holds the place of the one import: the next is refused for its own size, not for the first.
        again = await client.post("/api/bundles", content=in_halves(bundle, []), headers=AS_A_FILE)

    assert "content-length" not in refused.request.headers
    assert (refused.status_code, refused.json()) == (413, too_large("1 KB"))
    # The first half was already over, so the rest was never asked for.
    assert read == []
    assert stored == []
    assert after == ([], [], [])
    assert (again.status_code, again.json()) == (413, too_large("1 KB"))
    assert held(friend) == []


async def test_a_file_over_the_cap_is_refused_for_its_size_whatever_else_is_in_the_way(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    bundle = await wrights_bundle(sender, transcripts)
    # Small enough to be taken on, and held open as an upload still arriving.
    first = Paused(b"Remember to sharpen the chisels")
    read: list[int] = []
    async with running(app_on(friend, transcripts, bundle_upload_cap_bytes=1000)) as client:
        uploading = first.sent_to(client)
        await asyncio.wait_for(first.arriving.wait(), 5)

        declared = await import_file(client, bundle)
        undeclared = await client.post("/api/bundles", content=in_halves(bundle, read), headers=AS_A_FILE)
        fits = await import_file(client, b"Remember to sharpen the saws")
        first.let_go.set()
        ended = await uploading

    # Its size is what can't be waited out, so that is what each is told, and not to try again later.
    assert (declared.status_code, declared.json()) == (413, too_large("1 KB"))
    # One that declared no length is read no further than the cap, though nothing of it is stored.
    assert (undeclared.status_code, undeclared.json()) == (413, too_large("1 KB"))
    assert read == []
    assert (fits.status_code, fits.json()) == (409, ANOTHER_IMPORT)
    assert (ended.status_code, ended.json()) == (422, {"detail": "The file is not a Seek Bundle"})
    assert held(friend) == []


async def emptied(config: Config, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while held(config):
            await asyncio.sleep(0.01)


async def test_a_built_bundle_nobody_collects_is_deleted_once_its_time_is_up_and_is_then_not_there_to_download(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    sharpening(transcripts)
    # Half a second where a server gives ten minutes.
    async with running(app_on(sender, transcripts, built_bundle_expiry_seconds=0.5)) as client:
        wright = await add_channel(client, "@woodbywright")
        picks = await add_playlist(client, "PL-sharpening")
        await sync(client, wright)
        await sync_playlist(client, picks)

        collected = (await client.post(f"/api/playlists/{picks['id']}/bundles")).json()
        in_time = await client.get(f"/api/bundles/{collected['id']}")
        # Built last, and looked for only once its time is up: nothing is counted while the half second runs,
        # which on a slow machine may already be over.
        left = (await client.post(f"/api/channels/{wright['id']}/bundles")).json()
        await emptied(sender)
        too_late = await client.get(f"/api/bundles/{left['id']}")

    # One collected in time is sent whole; its time running out afterwards finds nothing to do.
    assert (in_time.status_code, len(in_time.content)) == (200, collected["size_bytes"])
    assert (too_late.status_code, too_late.json()) == (404, {"detail": "That Bundle is not here to download; export it again"})
    assert held(sender) == []


async def test_a_built_bundle_nobody_collected_is_removed_when_its_server_stops_and_not_when_another_does(
    sender: Config, transcripts: FakeTranscriptSource
) -> None:
    fake_channel(transcripts, "UC-wright").videos.append(fake_video("v-chisels", "Chisels"))
    async with running(app_on(sender, transcripts)) as client:
        wright = await add_channel(client, "@woodbywright")
        await sync(client, wright)
        built = (await client.post(f"/api/channels/{wright['id']}/bundles")).json()
        # A second server started by mistake on the same data directory stops again without having served.
        async with running(app_on(sender, transcripts)):
            pass
        still_waiting = held(sender)
        collected = await client.get(f"/api/bundles/{built['id']}")
        await client.post(f"/api/channels/{wright['id']}/bundles")
        left = held(sender)

    assert len(still_waiting) == 1
    assert (collected.status_code, len(collected.content)) == (200, built["size_bytes"])
    assert len(left) == 1
    assert held(sender) == []


def leftover(config: Config, name: str, directory_age: float, file_age: float) -> Path:
    """An upload's or a build's directory as a server that stopped would leave it, with each of the directory and
    the file in it last modified so many seconds ago."""
    directory = config.temporary_dir / name
    directory.mkdir(parents=True)
    file = directory / "upload.seek"
    file.write_bytes(b"What had arrived of a Bundle")
    now = time.time()
    os.utime(file, (now - file_age, now - file_age))
    os.utime(directory, (now - directory_age, now - directory_age))
    return directory


async def test_a_server_clears_at_start_what_was_left_over_an_hour_ago_and_keeps_what_another_may_still_be_writing(
    friend: Config, transcripts: FakeTranscriptSource
) -> None:
    hour = 3600
    stale = leftover(friend, "left-by-a-crash", directory_age=hour + 60, file_age=hour + 60)
    fresh = leftover(friend, "left-a-moment-ago", directory_age=hour - 60, file_age=hour - 60)
    # A large upload on a slow line: its directory was made long ago, and its file is still being written.
    arriving = leftover(friend, "still-arriving", directory_age=2 * hour, file_age=1)
    stray = friend.temporary_dir / "stray.seek"
    stray.write_bytes(b"Not in a directory of its own")
    os.utime(stray, (time.time() - 2 * hour, time.time() - 2 * hour))

    async with running(app_on(friend, transcripts)):
        # Before it serves anything: this is the first thing asked of it.
        kept = held(friend)

    assert kept == sorted([fresh, arriving])
    assert [file.name for directory in kept for file in directory.iterdir()] == ["upload.seek", "upload.seek"]
    assert not stale.exists() and not stray.exists()


async def begin_upload(base_url: str, sent: bytes, length: int) -> asyncio.StreamWriter:
    """Starts sending a file of `length` bytes to a served app as a browser does, on a connection of its own that
    the test can drop, and returns it with `sent` on its way."""
    url = httpx.URL(base_url)
    _, writer = await asyncio.open_connection(url.host, url.port)
    head = (
        f"POST /api/bundles HTTP/1.1\r\nHost: {url.netloc.decode()}\r\n"
        f"Content-Type: application/octet-stream\r\nContent-Length: {length}\r\n\r\n"
    )
    writer.write(head.encode() + sent)
    await writer.drain()
    return writer


async def stored_whole(config: Config, length: int, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while [file.stat().st_size for directory in held(config) for file in directory.iterdir()] != [length]:
            await asyncio.sleep(0.01)


async def test_an_upload_whose_browser_goes_away_partway_is_discarded_and_a_later_import_is_accepted(
    sender: Config,
    friend: Config,
    transcripts: FakeTranscriptSource,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = await wrights_bundle(sender, transcripts)
    async with serving(app_on(friend, transcripts)) as base_url, httpx.AsyncClient(base_url=base_url) as client:
        # The server logs a request that raised on a logger of its own, which keeps its records from the root's.
        server_log = logging.getLogger("uvicorn.error")
        monkeypatch.setattr(server_log, "handlers", [*server_log.handlers, caplog.handler])
        connection = await begin_upload(base_url, bundle[: len(bundle) // 2], len(bundle))
        # Taken on, with half of it here: until it ends it is the one import.
        async with asyncio.timeout(5):
            while not held(friend):
                await asyncio.sleep(0.01)
        meanwhile = await import_file(client, bundle)

        connection.transport.abort()
        await emptied(friend)
        after = await library(client)
        later = await import_file(client, bundle)

    assert (meanwhile.status_code, meanwhile.json()) == (409, ANOTHER_IMPORT)
    # Nothing of the half that arrived was imported, and nothing of it is kept.
    assert after == ([], [], [])
    assert (later.status_code, later.json()["added"]) == (200, 1)
    # The request nobody was waiting on ended as a refusal, not as a failure of the server's to log.
    assert [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR] == []
    assert held(friend) == []


async def test_an_import_whose_file_had_arrived_runs_to_its_end_though_the_browser_has_gone_and_open_pages_are_told(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource
) -> None:
    bundle = await wrights_bundle(sender, transcripts)
    app = app_on(friend, transcripts)
    async with serving(app) as base_url, httpx.AsyncClient(base_url=base_url) as client:
        async with event_stream(app) as events:
            # Something else is writing to the knowledge base, as another seek process may: the import waits for
            # it, which is what keeps it running for as long as the test needs.
            with closing(sqlite3.connect(friend.database_path, autocommit=True)) as writer:
                writer.execute("BEGIN IMMEDIATE")
                connection = await begin_upload(base_url, bundle, len(bundle))
                # With the whole file stored, the handler has the body to its end, which no test can watch
                # directly. It rests on the upload declaring its length: the server then hands over the bytes
                # that complete it already marked as the last, so the handler never asks the connection for
                # more, and asking is the only way it would learn the browser has gone.
                await stored_whole(friend, len(bundle))
                connection.transport.abort()
                # Long enough for the server to have noticed, were it to do anything about it.
                await asyncio.sleep(0.2)
                still_importing = await import_file(client, bundle)
                writer.execute("ROLLBACK")
            told = await events.until(lambda event: event["type"] == "videos")
        after = await library(client)
        later = await import_file(client, bundle)

    # The place of the one import stayed taken for as long as the import ran, and no longer.
    assert (still_importing.status_code, still_importing.json()) == (409, ANOTHER_IMPORT)
    assert after == ([("Wood By Wright", 1)], [], ["v-chisels"])
    [channel_id] = {event["channel_id"] for event in told if event["type"] == "videos"}
    assert (later.status_code, later.json()["id"], later.json()["already_indexed"]) == (200, channel_id, 1)
    assert held(friend) == []
