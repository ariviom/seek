import errno
import os
import stat
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from harness import (
    Gate,
    add_channel,
    add_playlist,
    bundle_config,
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
from seek.bundles import import_bundle
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


def app_on(config: Config, transcripts: FakeTranscriptSource) -> FastAPI:
    return create_app(
        config, transcripts, FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=config.data_dir / "none"
    )


def held(config: Config) -> list[Path]:
    """What a started server holds in its temporary directory: a directory for each Bundle it has built and not yet
    sent."""
    return sorted(config.temporary_dir.iterdir())


def mode(path: Path) -> int:
    """Who may read, write, and enter it."""
    return stat.S_IMODE(path.stat().st_mode)


async def test_a_channels_bundle_is_built_downloaded_as_a_file_and_imports_into_another_seek(
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
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

    # What was downloaded is the Channel's Bundle: the friend's Seek imports it.
    downloaded = tmp_path / "Wood By Wright.seek"
    downloaded.write_bytes(download.content)
    import_bundle(friend, downloaded)
    async with running(app_on(friend, FakeTranscriptSource())) as client:
        [channel] = (await client.get("/api/channels")).json()
        found = await search(client, "sharpen the saw with a file")
    assert (channel["name"], channel["indexed_videos"]) == ("Wood By Wright", 2)
    assert found[0]["youtube_video_id"] == "v-saws"
    # Nothing of it stays on the sender's disk.
    assert held(sender) == []


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
    sender: Config, friend: Config, transcripts: FakeTranscriptSource, tmp_path: Path
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
    downloaded = tmp_path / "Edge picks.seek"
    downloaded.write_bytes(download.content)
    import_bundle(friend, downloaded)
    async with running(app_on(friend, FakeTranscriptSource())) as client:
        [playlist] = (await client.get("/api/playlists")).json()
        found = await search(client, "strop the knife on leather")
    assert (playlist["name"], playlist["indexed_videos"]) == ("Edge picks", 2)
    assert found[0]["youtube_video_id"] == "v-knives"
    assert held(sender) == []


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
