"""The yt-dlp adapter's parsing and classification, below the API seam because yt-dlp can't be faked usefully."""

from datetime import date
from typing import Any

import pytest

from mentor.ports import Chapter, ChannelNotFound, Cue, VideoDetails, VideoListing, VideoUnavailable
from mentor.youtube import CaptionTrack, caption_track, channel_url, classify_error, listings, parse_json3, video_details

DETAILS = VideoDetails(
    video_id="v2jtQ96A2_Q", title="Why", published_on=date(2026, 9, 3), duration_seconds=559, description="", chapters=[]
)


def track(ext: str, url: str) -> dict[str, str]:
    return {"ext": ext, "url": url}


def tracks(*names: str) -> dict[str, list[dict[str, str]]]:
    return {name: [track("vtt", f"{name}.vtt"), track("json3", f"{name}.json3")] for name in names}


@pytest.mark.parametrize(
    ("given", "url"),
    [
        ("@woodbywright", "https://www.youtube.com/@woodbywright"),
        ("  @Rex.Krueger_1  ", "https://www.youtube.com/@Rex.Krueger_1"),
        ("https://www.youtube.com/@RexKrueger/videos", "https://www.youtube.com/@RexKrueger"),
        ("youtube.com/channel/UCj4SLNED1DiNPHComZTCbzw", "https://www.youtube.com/channel/UCj4SLNED1DiNPHComZTCbzw"),
        ("UCj4SLNED1DiNPHComZTCbzw", "https://www.youtube.com/channel/UCj4SLNED1DiNPHComZTCbzw"),
        ("https://m.youtube.com/c/WoodByWright?si=abc", "https://www.youtube.com/c/WoodByWright"),
        ("http://youtube.com/user/rexkrueger/featured", "https://www.youtube.com/user/rexkrueger"),
    ],
)
def test_channel_urls_handles_and_ids_become_canonical_channel_urls(given: str, url: str) -> None:
    assert channel_url(given) == url


@pytest.mark.parametrize(
    "given",
    [
        "https://example.com/@woodbywright",
        "https://www.youtube.com.evil.example/@woodbywright",
        "https://www.youtube.com/watch?v=jNQXAC9IVRw",
        "https://youtu.be/jNQXAC9IVRw",
        "file:///etc/passwd",
        "ftp://youtube.com/@woodbywright",
        "https://www.youtube.com/@a",
        "@has spaces",
        "Rex Krueger",
        "UCshort",
        "https://www.youtube.com/channel/not-a-channel-id",
    ],
)
def test_anything_but_a_youtube_channel_is_refused_before_yt_dlp_sees_it(given: str) -> None:
    with pytest.raises(ChannelNotFound, match="YouTube channel URL"):
        channel_url(given)


def test_listings_keep_order_and_leave_the_approximate_date_out() -> None:
    entries: list[dict[str, Any]] = [
        {"id": "v2jtQ96A2_Q", "title": "Why did I leave my shop?", "duration": 560, "timestamp": None},
        {"id": "c9OnQEHUpvI", "title": "The Forgotten Alternative", "duration": 1031.0},
        {"id": "LFzLQTySDCk", "title": "Upcoming", "duration": None},
        {"title": "No id"},
    ]

    assert listings(entries) == [
        VideoListing("v2jtQ96A2_Q", "Why did I leave my shop?", duration_seconds=560, published_on=None),
        VideoListing("c9OnQEHUpvI", "The Forgotten Alternative", duration_seconds=1031, published_on=None),
        VideoListing("LFzLQTySDCk", "Upcoming", duration_seconds=None, published_on=None),
    ]


def test_video_details_come_from_the_full_metadata_with_chapter_ends_filled_in() -> None:
    info = {
        "id": "jNQXAC9IVRw",
        "title": "Me at the zoo",
        "upload_date": "20050424",
        "duration": 19,
        "description": "The first video",
        "live_status": "not_live",
        "chapters": [{"start_time": 0, "title": "Intro"}, {"start_time": 5, "title": "The cool thing"}],
    }

    assert video_details(info) == VideoDetails(
        video_id="jNQXAC9IVRw",
        title="Me at the zoo",
        published_on=date(2005, 4, 24),
        duration_seconds=19,
        description="The first video",
        chapters=[Chapter(title="Intro", start=0.0, end=5.0), Chapter(title="The cool thing", start=5.0, end=19.0)],
    )


@pytest.mark.parametrize("live_status", ["is_live", "is_upcoming", "post_live"])
def test_live_and_upcoming_videos_fail_transiently(live_status: str) -> None:
    info = {"id": "x", "title": "Live Q&A", "live_status": live_status, "description": None}

    with pytest.raises(VideoUnavailable) as raised:
        video_details(info)

    assert raised.value.permanent is False
    assert "live" in raised.value.reason.lower()


def test_manual_english_subtitles_are_preferred_to_automatic_captions() -> None:
    info = {"subtitles": tracks("de", "en-GB", "live_chat"), "automatic_captions": tracks("en-orig", "en")}

    assert caption_track(info, [], DETAILS) == CaptionTrack(source="youtube_manual", url="en-GB.json3")


def test_automatic_captions_are_used_when_their_original_language_is_english() -> None:
    info = {"subtitles": {}, "automatic_captions": tracks("de", "en-orig", "en", "fr")}

    assert caption_track(info, [], DETAILS) == CaptionTrack(source="youtube_auto", url="en-orig.json3")


@pytest.mark.parametrize(
    ("info", "language"),
    [
        ({"subtitles": {}, "automatic_captions": tracks("de-orig", "de", "en")}, "de"),
        ({"subtitles": tracks("de-XwLwiJMB_Xs"), "automatic_captions": {}}, "de"),
    ],
)
def test_videos_spoken_in_another_language_fail_permanently_with_the_language(
    info: dict[str, Any], language: str
) -> None:
    with pytest.raises(VideoUnavailable) as raised:
        caption_track(info, [], DETAILS)

    assert (raised.value.permanent, raised.value.language, raised.value.details) == (True, language, DETAILS)
    assert "English" in raised.value.reason


def test_videos_without_captions_fail_permanently_unless_youtube_withheld_them_for_a_po_token() -> None:
    info: dict[str, Any] = {"subtitles": {}, "automatic_captions": {}}
    warning = "[youtube] x: There are missing subtitles languages because a PO token was not provided."

    with pytest.raises(VideoUnavailable) as no_captions:
        caption_track(info, [], DETAILS)
    with pytest.raises(VideoUnavailable) as withheld:
        caption_track(info, [warning], DETAILS)

    assert (no_captions.value.reason, no_captions.value.permanent, no_captions.value.details) == (
        "No captions",
        True,
        DETAILS,
    )
    assert withheld.value.permanent is False
    assert "bgutil-ytdlp-pot-provider" in withheld.value.reason


def test_json3_captions_become_cues_without_blank_lines_or_overlaps() -> None:
    data = {
        "events": [
            {"tStartMs": 0, "dDurationMs": 557240, "id": 1},
            {"tStartMs": 520, "dDurationMs": 6000, "segs": [{"utf8": "Your"}, {"utf8": " knee", "tOffsetMs": 200}]},
            {"tStartMs": 3870, "dDurationMs": 2650, "aAppend": 1, "segs": [{"utf8": "\n"}]},
            {"tStartMs": 3880, "dDurationMs": 5000, "segs": [{"utf8": "goes up\non this,"}]},
            {"tStartMs": 9000, "dDurationMs": 1000, "segs": [{"utf8": " "}]},
        ]
    }

    assert parse_json3(data) == [
        Cue(start=0.52, end=3.88, text="Your knee"),
        Cue(start=3.88, end=8.88, text="goes up on this,"),
    ]


LOGIN_HINT = (
    " Use --cookies-from-browser or --cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ"
    "#how-do-i-pass-cookies-to-yt-dlp  for how to manually pass cookies. Also see  https://github.com/yt-dlp/yt-dlp"
    "/wiki/Extractors#exporting-youtube-cookies  for tips on effectively exporting YouTube cookies"
)


@pytest.mark.parametrize(
    ("message", "status", "kind", "permanent", "contains"),
    [
        ("ERROR: [youtube] x: Join this channel to get access to members-only content like this video, and other "
         "exclusive perks.", None, "unavailable", True, "Members-only"),
        (f"ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate for some users.{LOGIN_HINT}",
         None, "unavailable", True, "Age-restricted"),
        ("ERROR: [youtube] x: This live event will begin in 3 days.", None, "unavailable", False, "live"),
        ("ERROR: [youtube] x: Premieres in 2 hours", None, "unavailable", False, "live"),
        ("ERROR: [youtube] x: Private video. Sign in if you've been granted access to this video", None,
         "unavailable", True, "Private"),
        ("ERROR: [youtube] x: The uploader has not made this video available in your country", None,
         "unavailable", True, "country"),
        ("ERROR: [youtube] x: This video is unavailable", None, "unavailable", True, "This video is unavailable"),
        ("ERROR: [youtube] x: This video has been removed by the uploader", None, "unavailable", True, "removed"),
        (f"ERROR: [youtube] x: Sign in to confirm you’re not a bot.{LOGIN_HINT}", None, "throttled", False, "bot"),
        ("ERROR: [youtube] x: Unable to download webpage: HTTP Error 429: Too Many Requests", 429, "throttled",
         False, "429"),
        ("ERROR: [youtube:tab] @nope/videos: Unable to download API page: HTTP Error 404: Not Found", 404,
         "not_found", True, "404"),
        ("ERROR: [youtube:tab] UCaaaaaaaaaaaaaaaaaaaaaa: YouTube said: This channel does not exist.", None,
         "not_found", True, "does not exist"),
        ("ERROR: [youtube:tab] PLaaaa: YouTube said: The playlist does not exist.", None, "not_found", True,
         "does not exist"),
        ("ERROR: [youtube] x: Requested format requires a GVS PO Token which was not provided", None,
         "unavailable", False, "bgutil-ytdlp-pot-provider"),
        ("ERROR: [youtube] x: Unable to download webpage: <urlopen error [Errno -3] Temporary failure in name "
         "resolution>", None, "unreachable", False, "name resolution"),
        ("ERROR: [youtube] x: Something new went wrong", None, "other", False, "Something new went wrong"),
    ],
)
def test_yt_dlp_errors_are_classified_with_a_user_facing_reason(
    message: str, status: int | None, kind: str, permanent: bool, contains: str
) -> None:
    error = classify_error(message, status)

    assert (error.kind, error.permanent) == (kind, permanent)
    assert contains in error.message
    assert not error.message.startswith("ERROR")
    assert "--cookies" not in error.message
