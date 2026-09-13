"""Against YouTube itself; run with `uv run pytest -m real_youtube`."""

import pytest

from mentor.youtube import YouTubeSettings, YouTubeTranscriptSource

pytestmark = pytest.mark.real_youtube


def test_captions_are_fetched_for_a_short_public_video() -> None:
    source = YouTubeTranscriptSource(YouTubeSettings(delay_seconds=0, retries=1, backoff_seconds=5, cookie_file=None))

    channel = source.resolve_channel("@jawed")
    details, transcript = source.fetch_video("jNQXAC9IVRw")

    assert channel.channel_id == "UC4QobU6STFB0P71PMvOGN5A"
    assert (details.title, details.published_on.isoformat()) == ("Me at the zoo", "2005-04-24")
    assert (transcript.source, transcript.language) == ("youtube_manual", "en")
    assert any("elephants" in cue.text.lower() for cue in transcript.cues)
