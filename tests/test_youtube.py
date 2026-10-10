"""The yt-dlp adapter's parsing and classification, below the API seam because yt-dlp can't be faked usefully."""

import time
from datetime import date, timedelta
from typing import Any

import pytest
import yt_dlp

from seek.ports import Chapter, ChannelNotFound, Cue, Storyboard, VideoDetails, VideoListing, VideoUnavailable
from seek.youtube import (
    avatar_url,
    CaptionTrack,
    caption_track,
    channel_url,
    classify_error,
    cookies_from_browser,
    listings,
    parse_json3,
    YouTubeSettings,
    YouTubeTranscriptSource,
    storyboard,
    take_until_known,
    video_details,
)

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


def test_the_avatar_is_the_square_crop_at_a_small_size_and_never_a_banner() -> None:
    avatar = "https://yt3.googleusercontent.com/pSHat-8"
    banner = "https://yt3.googleusercontent.com/2SLF"
    # As a channel tab extraction lists them: the square avatar, the original upload, then banners.
    thumbnails: list[dict[str, Any]] = [
        {"url": f"{avatar}=s900-c-k-c0x00ffffff-no-rj", "width": 900, "height": 900},
        {"id": "avatar_uncropped", "url": f"{avatar}=s0", "preference": 1},
        {"url": f"{banner}=w1060-fcrop64=1,00005a57ffffa5a8-k-c0xffffffff-no-nd-rj", "width": 1060, "height": 175},
        {"id": "banner_uncropped", "url": f"{banner}=s0", "preference": -5},
    ]

    assert avatar_url({"thumbnails": thumbnails}) == f"{avatar}=s176-c-k-c0x00ffffff-no-rj"
    assert avatar_url({"thumbnails": thumbnails[1:]}) == f"{avatar}=s176"
    assert avatar_url({"thumbnails": thumbnails[2:]}) is None
    assert avatar_url({}) is None


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


@pytest.mark.parametrize(
    "info",
    [
        # Translations of speech in an unknown language, with no "-orig" track to say which was spoken.
        {"subtitles": {}, "automatic_captions": tracks("de", "en", "fr")},
        {"subtitles": {"en": [track("vtt", "en.vtt")]}, "automatic_captions": {}},
    ],
)
def test_captions_that_cant_be_trusted_or_read_count_as_none(info: dict[str, Any]) -> None:
    with pytest.raises(VideoUnavailable) as raised:
        caption_track(info, [], DETAILS)

    assert (raised.value.reason, raised.value.language) == ("No captions", None)


def test_videos_without_captions_fail_permanently_unless_youtube_withheld_them_for_a_po_token() -> None:
    info: dict[str, Any] = {"subtitles": {}, "automatic_captions": {}}
    warning = "[debug] [youtube] x: There are missing subtitles languages because a PO token was not provided."

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


def test_a_new_video_without_captions_fails_transiently_while_youtube_may_still_be_generating_them() -> None:
    info: dict[str, Any] = {"subtitles": {}, "automatic_captions": {}}

    with pytest.raises(VideoUnavailable) as fresh:
        caption_track(info, [], DETAILS, today=DETAILS.published_on + timedelta(days=7))
    with pytest.raises(VideoUnavailable) as old:
        caption_track(info, [], DETAILS, today=DETAILS.published_on + timedelta(days=8))

    assert (fresh.value.permanent, fresh.value.details) == (False, DETAILS)
    assert "still be generating" in fresh.value.reason
    assert (old.value.reason, old.value.permanent) == ("No captions", True)


def test_a_listing_stops_after_the_first_page_holding_only_known_videos() -> None:
    entries = [{"id": f"v{n}"} for n in range(10)]
    known = {f"v{n}" for n in range(3, 10)}

    # Page 2 (v3–v5) is the first holding only known ids, so the listing ends with it.
    assert [e["id"] for e in take_until_known(entries, known, page_size=3)] == ["v0", "v1", "v2", "v3", "v4", "v5"]
    assert take_until_known(entries, set(), page_size=3) == entries
    # A page that is only partly known keeps the listing going.
    assert take_until_known(entries, {"v1", "v2", "v4", "v5"}, page_size=3) == entries


@pytest.mark.parametrize(
    ("given", "parsed"),
    [
        ("firefox", ("firefox", None, None, None)),
        ("Chrome:Profile 1", ("chrome", "Profile 1", None, None)),
        ("chromium+gnomekeyring:Default::work", ("chromium", "Default", "GNOMEKEYRING", "work")),
    ],
)
def test_browser_cookie_settings_take_yt_dlps_form(given: str, parsed: tuple[str | None, ...]) -> None:
    assert cookies_from_browser(given) == parsed


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
        ("ERROR: [youtube] x: Unable to download API page: HTTP Error 403: Forbidden", 403, "throttled", False, "403"),
        ("ERROR: [youtube:tab] PLaaaa: YouTube said: This playlist is private.", None, "unavailable", True,
         "private"),
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


# A storyboard sheet URL as YouTube signs it: one signature, in the query, shared by every sheet of the Video.
SHEETS = "https://i.ytimg.com/sb/v2jtQ96A2_Q/storyboard3_L3"
SIGNATURE = "sqp=-oaymwENSDfyq4qpAwVwAcABBqLzl_8DBgiN2YjEBg==&sigh=rs$AOn4CLDhbELErul4_LCpfuzhIUtDN0dkUg"


def sheet_urls(count: int, *, prefix: str = SHEETS, signature: str = SIGNATURE) -> list[dict[str, object]]:
    return [{"url": f"{prefix}/M{i}.jpg?{signature}", "duration": 89.5} for i in range(count)]


def extraction(**best: object) -> dict[str, Any]:
    """A recorded extraction: the storyboard tiers yt-dlp returns beside the media formats, sb0 the largest."""
    return {
        "id": "v2jtQ96A2_Q",
        "title": "Why",
        "upload_date": "20260903",
        "duration": 559,
        "live_status": "not_live",
        "formats": [
            {"format_id": "251", "ext": "webm", "url": "https://example.invalid/audio"},
            {
                "format_id": "sb0",
                "columns": 3,
                "rows": 3,
                "width": 320,
                "height": 180,
                "fps": 0.10116199589883801,
                "fragments": sheet_urls(17),
                **best,
            },
            # The smaller tier, which is the same frames again and must not be preferred.
            {
                "format_id": "sb1",
                "columns": 5,
                "rows": 5,
                "width": 160,
                "height": 90,
                "fps": 0.1,
                "fragments": sheet_urls(7),
            },
        ],
    }


def test_storyboard_geometry_comes_from_the_largest_tier_of_a_recorded_extraction() -> None:
    assert storyboard(extraction()) == Storyboard(
        columns=3,
        rows=3,
        width=320,
        height=180,
        fps=0.10116199589883801,
        url_template=f"{SHEETS}/M{{index}}.jpg?{SIGNATURE}",
        fragment_count=17,
    )


@pytest.mark.parametrize(
    "best",
    [
        # The sheets' signatures differ, so no one template stands for them all.
        {"fragments": [{"url": f"{SHEETS}/M0.jpg?{SIGNATURE}"}, {"url": f"{SHEETS}/M1.jpg?sqp=other&sigh=other"}]},
        # They aren't numbered the way a template assumes.
        {"fragments": [{"url": f"{SHEETS}/M0.jpg?{SIGNATURE}"}, {"url": f"{SHEETS}/M7.jpg?{SIGNATURE}"}]},
        {"fragments": [{"url": f"{SHEETS}/first.jpg?{SIGNATURE}"}]},
        {"fragments": []},
        {"fps": 0},
        {"fps": None},
        {"columns": 0},
        {"rows": None},
        {"width": None},
        {"height": 0},
    ],
)
def test_a_storyboard_this_code_cannot_crop_is_treated_as_absent(best: dict[str, object]) -> None:
    assert storyboard(extraction(**best)) is None


def test_an_extraction_offering_no_storyboard_at_all_has_none() -> None:
    assert storyboard({"id": "x"}) is None
    assert storyboard({"id": "x", "formats": [{"format_id": "251", "ext": "webm"}]}) is None


def test_video_details_carry_the_storyboard_of_the_same_extraction() -> None:
    details = video_details(extraction())

    assert details.storyboard is not None
    assert (details.storyboard.width, details.storyboard.fragment_count) == (320, 17)


class _StubYoutubeDL:
    """yt-dlp's surface as the adapter uses it, returning one recorded extraction and reaching no network."""

    def __init__(self, params: dict[str, object]) -> None:
        self.params = params

    def __enter__(self) -> "_StubYoutubeDL":
        return self

    def __exit__(self, *exception: object) -> None:
        return None

    def sanitize_info(self, info: dict[str, Any]) -> dict[str, Any]:
        return info

    def extract_info(self, url: str, download: bool, process: bool) -> dict[str, Any]:
        return extraction()


def test_fetching_one_storyboard_keeps_the_pace_a_syncs_calls_keep(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _StubYoutubeDL)
    source = YouTubeTranscriptSource(
        YouTubeSettings(delay_seconds=10, retries=0, backoff_seconds=1, cookie_file=None)
    )

    first = source.fetch_storyboard("v2jtQ96A2_Q")
    second = source.fetch_storyboard("v2jtQ96A2_Q")

    assert first is not None and first == second
    # The first call goes at once; the next waits out the delay a Sync waits, jittered by up to 30% either way.
    assert [7 <= wait <= 13 for wait in slept] == [True]
