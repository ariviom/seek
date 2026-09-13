"""TranscriptSource backed by yt-dlp.

The module-level functions parse what yt-dlp returns and classify its errors without touching the network.
"""

import json
import logging
import re
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import yt_dlp
from yt_dlp.networking.exceptions import HTTPError

from mentor.ports import (
    Chapter,
    ChannelInfo,
    ChannelNotFound,
    Cue,
    PlaylistNotFound,
    SourceUnavailable,
    Transcript,
    VideoDetails,
    VideoListing,
    VideoUnavailable,
)

log = logging.getLogger(__name__)

YOUTUBE = "https://www.youtube.com"
_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
_HANDLE = re.compile(r"@[\w.-]{3,30}")
# Legacy /c/ and /user/ channel names.
_LEGACY_NAME = re.compile(r"[\w.-]{1,100}")
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_PLAYLIST_ID = re.compile(r"[A-Za-z0-9_-]{2,64}")

NOT_A_CHANNEL = "Enter a YouTube channel URL (youtube.com/@handle or youtube.com/channel/UC…), an @handle, or a channel id"
PO_TOKEN_FIX = (
    "YouTube wants a PO token: install the bgutil-ytdlp-pot-provider plugin "
    "(https://github.com/Brainicism/bgutil-ytdlp-pot-provider), then retry failed Videos"
)
_NO_VIDEOS_TAB = "does not have a videos tab"


@dataclass(frozen=True)
class YouTubeSettings:
    # The least time between requests a Sync makes; resolving a channel for the web UI doesn't wait.
    delay_seconds: float
    # Retries while YouTube rate limits or can't be reached, after backoff_seconds and doubling each time.
    retries: int
    backoff_seconds: float
    cookie_file: Path | None


class _Log:
    """yt-dlp's logger. Warnings are kept: they are where yt-dlp reports captions withheld for a PO token."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def debug(self, message: str) -> None:
        log.debug("yt-dlp: %s", message)

    def info(self, message: str) -> None:
        log.debug("yt-dlp: %s", message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)
        log.info("yt-dlp: %s", message)

    def error(self, message: str) -> None:
        # The same message is raised, and classified by the caller.
        log.debug("yt-dlp: %s", message)


class _Failed(Exception):
    def __init__(self, error: "YouTubeError") -> None:
        super().__init__(error.message)
        self.error = error


class YouTubeTranscriptSource:
    """Blocking, and safe to call from several threads; Sync requests are spaced out across all of them."""

    def __init__(self, settings: YouTubeSettings) -> None:
        self._settings = settings
        self._turn = threading.Lock()
        self._next_request = 0.0

    def resolve_channel(self, url_or_handle: str) -> ChannelInfo:
        url = channel_url(url_or_handle)
        try:
            info = self._playlist(f"{url}/videos", polite=False, playlistend=1)
        except _Failed as failed:
            if _NO_VIDEOS_TAB in failed.error.message:
                raise ChannelNotFound(f"{url_or_handle} has no videos tab, so there is nothing to ingest") from None
            raise _channel_error(failed.error, url_or_handle) from None
        channel_id = info.get("channel_id") or info.get("id")
        if not isinstance(channel_id, str) or not _CHANNEL_ID.fullmatch(channel_id):
            raise ChannelNotFound(f"No YouTube channel found for {url_or_handle}")
        name = info.get("channel") or info.get("uploader") or channel_id
        return ChannelInfo(channel_id=channel_id, name=str(name))

    def list_videos(self, channel_id: str) -> Sequence[VideoListing]:
        if not _CHANNEL_ID.fullmatch(channel_id):
            raise ChannelNotFound(f"No YouTube channel found for {channel_id}")
        try:
            info = self._playlist(f"{YOUTUBE}/channel/{channel_id}/videos", polite=True)
        except _Failed as failed:
            if _NO_VIDEOS_TAB in failed.error.message:
                return []
            raise _channel_error(failed.error, channel_id) from None
        return listings(info.get("entries") or [])

    def list_playlist(self, playlist_id: str) -> Sequence[str]:
        if not _PLAYLIST_ID.fullmatch(playlist_id):
            raise PlaylistNotFound(f"No YouTube playlist found for {playlist_id}")
        try:
            info = self._playlist(f"{YOUTUBE}/playlist?list={playlist_id}", polite=True)
        except _Failed as failed:
            if failed.error.kind in ("not_found", "unavailable"):
                raise PlaylistNotFound(f"No YouTube playlist found for {playlist_id}") from None
            raise SourceUnavailable(failed.error.message) from None
        return [entry["id"] for entry in info.get("entries") or [] if entry.get("id")]

    def fetch_video(self, video_id: str) -> tuple[VideoDetails, Transcript]:
        if not _VIDEO_ID.fullmatch(video_id):
            raise VideoUnavailable(f"{video_id!r} is not a YouTube video id", permanent=True)
        url = f"{YOUTUBE}/watch?v={video_id}"
        try:
            # process=False: without format selection, formats YouTube withholds can't fail the extraction.
            info, warnings = self._call(
                lambda ydl: ydl.sanitize_info(ydl.extract_info(url, download=False, process=False)), polite=True
            )
        except _Failed as failed:
            raise _video_error(failed.error, None) from None
        details = video_details(info)
        track = caption_track(info, warnings, details)
        try:
            data, _ = self._call(lambda ydl: json.load(ydl.urlopen(track.url)), polite=False)
        except _Failed as failed:
            raise _video_error(failed.error, details) from None
        return details, Transcript(source=track.source, language="en", cues=parse_json3(data))

    def _playlist(self, url: str, polite: bool, **options: object) -> Mapping[str, Any]:
        def extract(ydl: Any) -> Mapping[str, Any]:
            info = ydl.sanitize_info(ydl.extract_info(url, download=False))
            return {**info, "entries": list(info.get("entries") or [])}

        info, _ = self._call(extract, polite, extract_flat="in_playlist", **options)
        return info

    def _wait_turn(self) -> None:
        with self._turn:
            wait = self._next_request - time.monotonic()
            if wait > 0:
                time.sleep(wait)

    def _finished_request(self) -> None:
        with self._turn:
            self._next_request = time.monotonic() + self._settings.delay_seconds

    def _call[T](self, work: Callable[[Any], T], polite: bool, **options: object) -> tuple[T, list[str]]:
        """Runs `work` with a fresh YoutubeDL, and its warnings; retries with backoff while throttled or unreachable.

        Raises _Failed with the classified error.
        """
        attempt = 0
        while True:
            if polite:
                self._wait_turn()
            logger = _Log()
            params: dict[str, object] = {
                "quiet": True,
                "logger": logger,
                "skip_download": True,
                "socket_timeout": 30,
                # Stream manifests aren't needed for metadata and captions, and cost requests.
                "extractor_args": {"youtube": {"skip": ["hls", "dash"]}},
                **options,
            }
            if self._settings.cookie_file is not None:
                params["cookiefile"] = str(self._settings.cookie_file)
            try:
                with yt_dlp.YoutubeDL(params) as ydl:
                    return work(ydl), logger.warnings
            except Exception as e:
                error = classify_error(str(e), _http_status(e))
            finally:
                self._finished_request()
            if error.kind not in ("throttled", "unreachable") or attempt >= self._settings.retries:
                raise _Failed(error)
            wait = self._settings.backoff_seconds * 2**attempt
            log.warning("%s; retrying in %s s", error.message, wait)
            time.sleep(wait)
            attempt += 1


def _http_status(error: BaseException) -> int | None:
    # yt-dlp raises DownloadError wrapping the original exception, or an HTTPError from urlopen directly.
    exc_info = getattr(error, "exc_info", None)
    cause = exc_info[1] if exc_info else error
    for candidate in (cause, getattr(cause, "cause", None)):
        if isinstance(candidate, HTTPError):
            return int(candidate.status)
    return None


def _channel_error(error: "YouTubeError", channel: str) -> Exception:
    if error.kind in ("not_found", "unavailable"):
        return ChannelNotFound(f"No YouTube channel found for {channel}")
    return SourceUnavailable(error.message)


def _video_error(error: "YouTubeError", details: VideoDetails | None) -> Exception:
    if error.kind in ("throttled", "unreachable"):
        return SourceUnavailable(error.message)
    return VideoUnavailable(error.message, permanent=error.permanent, details=details)


def channel_url(text: str) -> str:
    """The canonical URL for a YouTube channel URL, @handle, or channel id.

    Only these reach yt-dlp, whose generic extractor would otherwise fetch any URL it is given.
    """
    text = text.strip()
    if _HANDLE.fullmatch(text):
        return f"{YOUTUBE}/{urllib.parse.quote(text, safe='@')}"
    if _CHANNEL_ID.fullmatch(text):
        return f"{YOUTUBE}/channel/{text}"
    if re.match(r"(?:www\.|m\.)?youtube\.com/", text):
        text = f"https://{text}"
    parts = urllib.parse.urlsplit(text)
    segments = [urllib.parse.unquote(s) for s in parts.path.split("/") if s]
    if parts.scheme in ("http", "https") and parts.hostname in _HOSTS and segments:
        first = segments[0]
        if _HANDLE.fullmatch(first):
            return f"{YOUTUBE}/{urllib.parse.quote(first, safe='@')}"
        if len(segments) > 1 and first == "channel" and _CHANNEL_ID.fullmatch(segments[1]):
            return f"{YOUTUBE}/channel/{segments[1]}"
        if len(segments) > 1 and first in ("c", "user") and _LEGACY_NAME.fullmatch(segments[1]):
            return f"{YOUTUBE}/{first}/{urllib.parse.quote(segments[1])}"
    raise ChannelNotFound(NOT_A_CHANNEL)


def _integer(value: object) -> int | None:
    return round(value) if isinstance(value, int | float) else None


def listings(entries: Iterable[Mapping[str, Any]]) -> list[VideoListing]:
    """A flat videos tab listing, in its order.

    Its dates are approximate ("2 years ago"), so none is kept: an undated Video is fetched and judged on its real date.
    """
    return [
        VideoListing(
            video_id=entry["id"],
            title=entry.get("title") or entry["id"],
            duration_seconds=_integer(entry.get("duration")),
            published_on=None,
        )
        for entry in entries
        if entry.get("id")
    ]


_LIVE = {
    "is_live": "Live stream in progress",
    "is_upcoming": "Upcoming live stream or premiere",
    "post_live": "Live stream still processing",
}


def _published_on(info: Mapping[str, Any]) -> date | None:
    for key in ("upload_date", "release_date"):
        if isinstance(info.get(key), str) and re.fullmatch(r"\d{8}", info[key]):
            return datetime.strptime(info[key], "%Y%m%d").date()
    for key in ("timestamp", "release_timestamp"):
        if isinstance(info.get(key), int | float):
            return datetime.fromtimestamp(info[key], UTC).date()
    return None


def video_details(info: Mapping[str, Any]) -> VideoDetails:
    """A Video's full metadata; raises VideoUnavailable for live and upcoming Videos, which may work later."""
    live = _LIVE.get(info.get("live_status") or "")
    if live is not None:
        raise VideoUnavailable(f"{live}; retried on the next Sync", permanent=False)
    published_on = _published_on(info)
    duration = _integer(info.get("duration"))
    if published_on is None or duration is None:
        raise VideoUnavailable("YouTube gave no publish date or length for this Video", permanent=False)
    raw_chapters = info.get("chapters") or []
    chapters = []
    for i, chapter in enumerate(raw_chapters):
        end = chapter.get("end_time")
        if end is None:
            end = raw_chapters[i + 1]["start_time"] if i + 1 < len(raw_chapters) else duration
        chapters.append(Chapter(title=chapter.get("title") or "", start=float(chapter["start_time"]), end=float(end)))
    return VideoDetails(
        video_id=info["id"],
        title=info.get("title") or info["id"],
        published_on=published_on,
        duration_seconds=duration,
        description=info.get("description") or "",
        chapters=chapters,
    )


@dataclass(frozen=True)
class CaptionTrack:
    source: Literal["youtube_auto", "youtube_manual"]
    url: str


def _language(key: str) -> str:
    # Track keys look like "en", "en-GB", "en-orig", or "de-XwLwiJMB_Xs".
    return key.split("-")[0]


def _json3_url(formats: Sequence[Mapping[str, Any]]) -> str | None:
    return next((f["url"] for f in formats if f.get("ext") == "json3" and f.get("url")), None)


def caption_track(info: Mapping[str, Any], warnings: Sequence[str], details: VideoDetails) -> CaptionTrack:
    """The English captions to ingest: manual subtitles first, else automatic captions of English speech.

    Automatic captions come in every language by translation; the "-orig" track is the spoken language.
    """
    manual = {key: formats for key, formats in (info.get("subtitles") or {}).items() if key != "live_chat"}
    automatic = info.get("automatic_captions") or {}
    for key in sorted(manual, key=lambda k: k != "en"):
        if _language(key) == "en" and (url := _json3_url(manual[key])):
            return CaptionTrack(source="youtube_manual", url=url)
    spoken_tracks = [key for key in automatic if key.endswith("-orig")] or list(automatic)
    for key in spoken_tracks:
        if _language(key) == "en" and (url := _json3_url(automatic[key])):
            return CaptionTrack(source="youtube_auto", url=url)
    languages = [_language(key) for key in spoken_tracks] or [_language(key) for key in manual]
    if languages:
        raise VideoUnavailable(
            f"Captions are in {languages[0]!r}; only English is ingested",
            permanent=True,
            language=languages[0],
            details=details,
        )
    if any("po token" in warning.lower() for warning in warnings):
        raise VideoUnavailable(f"No captions: {PO_TOKEN_FIX}", permanent=False, details=details)
    raise VideoUnavailable("No captions", permanent=True, details=details)


def parse_json3(data: Mapping[str, Any]) -> list[Cue]:
    """YouTube's json3 caption events as Cues. Automatic captions overlap, so each Cue ends by the next one's start."""
    lines: list[tuple[float, float, str]] = []
    for event in data.get("events") or []:
        text = " ".join("".join(seg.get("utf8", "") for seg in event.get("segs") or []).split())
        if text:
            start = event["tStartMs"] / 1000
            lines.append((start, (event["tStartMs"] + event.get("dDurationMs", 0)) / 1000, text))
    return [
        Cue(start=start, end=min(end, lines[i + 1][0]) if i + 1 < len(lines) else end, text=text)
        for i, (start, end, text) in enumerate(lines)
    ]


type ErrorKind = Literal["not_found", "unavailable", "throttled", "unreachable", "other"]


@dataclass(frozen=True)
class YouTubeError:
    kind: ErrorKind
    # User-facing.
    message: str
    permanent: bool


def classify_error(message: str, http_status: int | None) -> YouTubeError:
    """What a yt-dlp error means. Throttled and unreachable errors are about YouTube, not the Video or channel."""
    text = re.sub(r"^ERROR:\s*", "", message.strip())
    text = re.sub(r"^\[[\w:]+\]\s*[^:\s]+:\s*", "", text)
    # yt-dlp's command-line advice about cookies doesn't apply here; youtube_cookie_file does.
    text = re.sub(r"\.?\s*Use --cookies.*$", "", text, flags=re.DOTALL).strip()
    lower = text.lower()

    def mentions(*needles: str) -> bool:
        return any(needle in lower for needle in needles)

    if mentions("po token"):
        return YouTubeError("unavailable", f"{text}. {PO_TOKEN_FIX}", permanent=False)
    if http_status == 429 or mentions("too many requests", "not a bot", "captcha", "rate-limited", "try again later"):
        return YouTubeError(
            "throttled",
            f"YouTube is rate limiting requests ({text}); try again later, or configure youtube_cookie_file",
            permanent=False,
        )
    if (http_status is not None and http_status >= 500) or (
        http_status is None
        and mentions("unable to download", "timed out", "connection", "name resolution", "network is unreachable")
    ):
        return YouTubeError("unreachable", f"Could not reach YouTube: {text}", permanent=False)
    if http_status == 404 or mentions("does not exist", "not found"):
        return YouTubeError("not_found", text, permanent=True)
    if mentions("members-only", "join this channel"):
        return YouTubeError("unavailable", "Members-only Video", permanent=True)
    if mentions("confirm your age", "age-restricted", "inappropriate for some users"):
        return YouTubeError(
            "unavailable",
            "Age-restricted Video; a youtube_cookie_file from a signed-in adult account may allow it",
            permanent=True,
        )
    if mentions("will begin", "premiere"):
        return YouTubeError("unavailable", f"Upcoming live stream or premiere ({text}); retried on the next Sync", False)
    if mentions("private video"):
        return YouTubeError("unavailable", "Private Video", permanent=True)
    if mentions("available in your country"):
        return YouTubeError("unavailable", "Not available in this country", permanent=True)
    if mentions("unavailable", "removed", "terminated", "no longer available", "not available"):
        return YouTubeError("unavailable", text, permanent=True)
    return YouTubeError("other", f"YouTube error: {text}", permanent=False)
