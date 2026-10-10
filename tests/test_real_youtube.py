"""Against YouTube itself; run with `uv run pytest -m real_youtube`."""

import pytest

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
