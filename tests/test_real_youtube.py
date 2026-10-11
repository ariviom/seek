"""Against YouTube itself; run with `uv run pytest -m real_youtube`."""

import re
import shutil
from pathlib import Path

import pytest

from seek.config import load_config
from seek.ports import PlaylistNotFound
from seek.youtube import YouTubeSettings, YouTubeTranscriptSource

pytestmark = pytest.mark.real_youtube


def test_captions_are_fetched_for_a_short_public_video() -> None:
    source = YouTubeTranscriptSource(YouTubeSettings(delay_seconds=0, retries=1, backoff_seconds=5, cookie_file=None))

    channel = source.resolve_channel("@jawed")
    details, transcript = source.fetch_video("jNQXAC9IVRw")

    assert channel.channel_id == "UC4QobU6STFB0P71PMvOGN5A"
    assert (details.title, details.published_on.isoformat()) == ("Me at the zoo", "2005-04-24")
    assert (transcript.source, transcript.language) == ("youtube_manual", "en")
    assert any("elephants" in cue.text.lower() for cue in transcript.cues)


def test_a_storyboard_comes_back_with_one_signature_covering_every_sheet() -> None:
    source = YouTubeTranscriptSource(YouTubeSettings(delay_seconds=0, retries=1, backoff_seconds=5, cookie_file=None))

    # Big Buck Bunny on Blender's channel: long enough for YouTube to have made a storyboard of it.
    storyboard = source.fetch_storyboard("YE7VzlLtp-4")
    # "Me at the zoo" is 19 seconds, and YouTube offers no storyboard at all for it.
    absent = source.fetch_storyboard("jNQXAC9IVRw")

    # The stored geometry rests on one template standing for every sheet, signature and all.
    assert storyboard is not None
    assert "/M{index}." in storyboard.url_template and "sqp=" in storyboard.url_template
    assert storyboard.fragment_count >= 1
    assert min(storyboard.columns, storyboard.rows, storyboard.width, storyboard.height) > 0
    assert storyboard.fps > 0
    assert absent is None


def test_a_public_playlist_lists_each_videos_creator_and_length_and_a_missing_one_is_refused() -> None:
    source = YouTubeTranscriptSource(YouTubeSettings(delay_seconds=0, retries=1, backoff_seconds=5, cookie_file=None))

    # Google's "Search Stories": a dozen videos, some since hidden, which YouTube lists without a creator.
    resolved = source.resolve_playlist("https://www.youtube.com/watch?v=GvgqDSnpRQM&list=PLBCF2DAC6FFB574DE")
    listing = source.list_playlist("PLBCF2DAC6FFB574DE")
    with pytest.raises(PlaylistNotFound) as missing:
        source.resolve_playlist("PLxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")

    assert (resolved.playlist_id, resolved.title) == ("PLBCF2DAC6FFB574DE", "Google Search Stories")
    assert resolved.video_count == len(listing.entries) > 0
    first = listing.entries[0]
    assert (first.video_id, first.channel_id, first.channel_name, first.duration_seconds) == (
        "GvgqDSnpRQM",
        "UCvceBgMIpKb4zK1ss-Sh90w",
        "Google Search Stories",
        90,
    )
    # The flat listing carries every entry's creator and length, so a Sync credits and judges a Video unfetched.
    assert all(re.fullmatch(r"UC[\w-]{22}", entry.channel_id) and entry.channel_name for entry in listing.entries)
    assert all(isinstance(entry.duration_seconds, int) for entry in listing.entries)
    # A hidden video has no entry, but its id is still listed, which is what keeps it in a Playlist.
    assert "fIc_VEQ7Vo0" in listing.video_ids
    assert "fIc_VEQ7Vo0" not in {entry.video_id for entry in listing.entries}
    assert "doesn't exist or is private" in str(missing.value)


def test_a_private_playlist_lists_with_its_owners_cookies(tmp_path: Path) -> None:
    config = load_config()
    if config.youtube_cookie_file is None and config.youtube_cookies_from_browser is None:
        pytest.skip("needs youtube_cookie_file or youtube_cookies_from_browser in the Seek config, signed in to YouTube")
    jar = None
    if config.youtube_cookie_file is not None:
        # A copy: yt-dlp rewrites the jar as each session closes, and a running server holds the real one.
        jar = Path(shutil.copyfile(config.youtube_cookie_file, tmp_path / "cookies.txt"))
    signed_in = YouTubeTranscriptSource(
        YouTubeSettings(
            delay_seconds=0,
            retries=1,
            backoff_seconds=5,
            cookie_file=jar,
            cookies_from_browser=config.youtube_cookies_from_browser,
            extractor_args=config.youtube_extractor_args,
        )
    )
    signed_out = YouTubeTranscriptSource(YouTubeSettings(delay_seconds=0, retries=1, backoff_seconds=5, cookie_file=None))

    # "Liked videos" is private to every account, so it stands for any private playlist the cookies' owner has.
    with pytest.raises(PlaylistNotFound, match="doesn't exist or is private"):
        signed_out.resolve_playlist("LL")
    mine = signed_in.list_playlist("LL")

    assert mine.title
