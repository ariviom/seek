"""TranscriptSource backed by yt-dlp.

The module-level functions parse what yt-dlp returns and classify its errors without touching the network.
"""

import json
import logging
import random
import re
import threading
import time
import urllib.parse
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yt_dlp
from yt_dlp.networking.exceptions import HTTPError

from seek.ports import (
    PLAYLIST_MISSING_OR_PRIVATE,
    Chapter,
    ChannelInfo,
    ChannelListing,
    ChannelNotFound,
    Cue,
    PlaylistEntry,
    PlaylistInfo,
    PlaylistListing,
    PlaylistNotFound,
    SourceUnavailable,
    Storyboard,
    Transcript,
    VideoDetails,
    VideoListing,
    VideoUnavailable,
)

log = logging.getLogger(__name__)

_YOUTUBE = "https://www.youtube.com"
_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
_HANDLE = re.compile(r"@[\w.-]{3,30}")
# Legacy /c/ and /user/ channel names.
_LEGACY_NAME = re.compile(r"[\w.-]{1,100}")

_PLAYLIST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

_NOT_A_CHANNEL = "Enter a YouTube channel URL (youtube.com/@handle or youtube.com/channel/UC…), an @handle, or a channel id"
_NOT_A_PLAYLIST = "Enter a YouTube playlist URL (youtube.com/playlist?list=…) or a playlist id"
_PO_TOKEN_FIX = (
    "YouTube wants a PO token; install the bgutil-ytdlp-pot-provider plugin "
    "(https://github.com/Brainicism/bgutil-ytdlp-pot-provider)"
)
_NO_TAB = re.compile(r"does not have an? \w+ tab")
# Between the requests within one Sync call: a listing's pages, or a Video's page, player, and captions.
_REQUEST_PAUSE_SECONDS = 1
# A listing page of a channel tab; a listing given known ids stops once a page holds nothing else.
PAGE_SIZE = 30
# YouTube generates automatic captions some time after upload: until then "no captions" is worth retrying.
CAPTIONS_GRACE = timedelta(days=7)
# Stream manifests aren't needed for metadata and captions, and cost requests.
DEFAULT_EXTRACTOR_ARGS: Mapping[str, Sequence[str]] = {"skip": ("hls", "dash")}


def _jitter(seconds: float) -> float:
    """±30%, so paced requests don't land on a fixed beat."""
    return seconds * random.uniform(0.7, 1.3)


@dataclass(frozen=True)
class YouTubeSettings:
    # The least time between a Sync's calls: each listing, and each Video with its captions.
    delay_seconds: float
    # Retries while YouTube rate limits or can't be reached, after backoff_seconds and doubling each time.
    retries: int
    backoff_seconds: float
    cookie_file: Path | None
    # yt-dlp's BROWSER[+KEYRING][:PROFILE][::CONTAINER]; None reads no browser.
    cookies_from_browser: str | None = None
    # Merged over DEFAULT_EXTRACTOR_ARGS.
    extractor_args: Mapping[str, Sequence[str]] = field(default_factory=dict)


class _Log:
    """yt-dlp's logger. Keeps its messages about PO tokens, which is how it reports captions it withheld."""

    def __init__(self) -> None:
        self.po_token_messages: list[str] = []

    def _keep(self, message: str) -> None:
        if "po token" in message.lower():
            self.po_token_messages.append(message)

    def debug(self, message: str) -> None:
        self._keep(message)
        log.debug("yt-dlp: %s", message)

    def info(self, message: str) -> None:
        log.debug("yt-dlp: %s", message)

    def warning(self, message: str) -> None:
        self._keep(message)
        log.info("yt-dlp: %s", message)

    def error(self, message: str) -> None:
        # The same message is raised, and classified by the caller.
        log.debug("yt-dlp: %s", message)


class _Failed(Exception):
    def __init__(self, error: "YouTubeError") -> None:
        super().__init__(error.message)
        self.error = error


class _CaptionsRefused(_Failed):
    """YouTube throttled the caption request itself, after the Video's page came through."""

    def __init__(self, error: "YouTubeError", details: VideoDetails) -> None:
        super().__init__(error)
        self.details = details


class YouTubeTranscriptSource:
    """Blocking. Sync calls come from one worker thread at a time; web UI calls may run alongside them."""

    def __init__(self, settings: YouTubeSettings) -> None:
        self._settings = settings
        # One yt-dlp session at a time: each rewrites the cookie file when it closes. The lock is this process's
        # own, so a second process sharing the jar must not write it (see cli._own_cookies).
        self._session = threading.Lock()
        self._next_sync_call = 0.0

    def resolve_channel(self, url_or_handle: str, paced: bool = False) -> ChannelInfo:
        url = channel_url(url_or_handle)
        try:
            # process=False reads the channel's own metadata without listing a tab, so a Shorts-only Channel resolves.
            info = self._call(lambda ydl, _: ydl.extract_info(url, download=False, process=False), sync=paced)
        except _Failed as failed:
            raise _channel_error(failed.error, url_or_handle) from None
        channel_id = info.get("channel_id")
        if not isinstance(channel_id, str) or not _CHANNEL_ID.fullmatch(channel_id):
            raise ChannelNotFound(f"No YouTube channel found for {url_or_handle}")
        return ChannelInfo(
            channel_id=channel_id,
            name=str(info.get("channel") or info.get("uploader") or channel_id),
            avatar_url=avatar_url(info),
        )

    def list_videos(self, channel_id: str, known_ids: Collection[str] = ()) -> ChannelListing:
        # The streams tab after the videos tab, so a listing's order stays newest first within each.
        found: list[VideoListing] = []
        avatar: str | None = None
        for tab in ("videos", "streams"):
            try:
                tab_avatar, entries = self._call(
                    _tab_entries(f"{_YOUTUBE}/channel/{channel_id}/{tab}", known_ids), sync=True
                )
            except _Failed as failed:
                if _NO_TAB.search(failed.error.message):
                    continue
                raise _channel_error(failed.error, channel_id) from None
            avatar = avatar or tab_avatar
            found += listings(entries)
        # Merged by id: a stream can appear on both tabs.
        merged: dict[str, VideoListing] = {}
        for listing in found:
            merged.setdefault(listing.video_id, listing)
        return ChannelListing(videos=list(merged.values()), avatar_url=avatar)

    def resolve_playlist(self, url_or_id: str) -> PlaylistInfo:
        listed_id = playlist_id(url_or_id)
        listing = self._list_playlist(listed_id, sync=False)
        return PlaylistInfo(playlist_id=listed_id, title=listing.title, video_count=len(listing.entries))

    def list_playlist(self, playlist_id: str) -> PlaylistListing:
        return self._list_playlist(playlist_id, sync=True)

    def _list_playlist(self, playlist_id: str, sync: bool) -> PlaylistListing:
        url = f"{_YOUTUBE}/playlist?list={playlist_id}"
        try:
            return self._call(
                lambda ydl, _: playlist_listing(ydl.sanitize_info(ydl.extract_info(url, download=False))), sync=sync
            )
        except _Failed as failed:
            if _is_missing(failed.error):
                raise PlaylistNotFound(PLAYLIST_MISSING_OR_PRIVATE) from None
            raise SourceUnavailable(failed.error.message) from None

    def fetch_video(self, video_id: str) -> tuple[VideoDetails, Transcript]:
        url = f"{_YOUTUBE}/watch?v={video_id}"

        def fetch(ydl: Any, logger: _Log) -> tuple[VideoDetails, Transcript]:
            # process=False: without format selection, formats YouTube withholds can't fail the extraction.
            info = ydl.sanitize_info(ydl.extract_info(url, download=False, process=False))
            details = video_details(info)
            track = caption_track(info, logger.po_token_messages, details, datetime.now(UTC).date())
            time.sleep(_jitter(_REQUEST_PAUSE_SECONDS))
            try:
                data = json.load(ydl.urlopen(track.url))
            except Exception as e:
                error = classify_error(str(e), _http_status(e))
                if error.kind == "unreachable":
                    raise
                if error.kind == "throttled":
                    raise _CaptionsRefused(error, details) from e
                raise VideoUnavailable(error.message, permanent=error.permanent, details=details) from e
            return details, Transcript(source=track.source, language="en", cues=parse_json3(data))

        try:
            return self._call(fetch, sync=True)
        except _CaptionsRefused as refused:
            # One refused caption request fails this Video alone; the Sync worker stops after a run of them.
            raise VideoUnavailable(
                refused.error.message, permanent=False, details=refused.details, throttled=True
            ) from None
        except _Failed as failed:
            if failed.error.kind in ("throttled", "unreachable"):
                raise SourceUnavailable(failed.error.message) from None
            raise VideoUnavailable(failed.error.message, permanent=failed.error.permanent) from None

    def fetch_storyboard(self, video_id: str) -> Storyboard | None:
        """The storyboard geometry alone, from the same extraction fetch_video performs, without its captions.

        Paced and retried exactly as a Sync's calls are. The backfill that uses it runs in its own process, so it
        waits on neither the pace nor the session lock a Sync in the server holds -- but both address YouTube from
        one machine, so running the two together raises the rate it sees (see backfill_command).
        """
        url = f"{_YOUTUBE}/watch?v={video_id}"

        def fetch(ydl: Any, _: _Log) -> Storyboard | None:
            return storyboard(ydl.sanitize_info(ydl.extract_info(url, download=False, process=False)))

        try:
            return self._call(fetch, sync=True)
        except _Failed as failed:
            if failed.error.kind in ("throttled", "unreachable"):
                raise SourceUnavailable(failed.error.message) from None
            raise VideoUnavailable(failed.error.message, permanent=failed.error.permanent) from None

    def _extractor_args(self) -> dict[str, Sequence[str]]:
        return {**DEFAULT_EXTRACTOR_ARGS, **self._settings.extractor_args}

    def _call[T](self, work: Callable[[Any, _Log], T], sync: bool) -> T:
        """Runs `work` in a fresh yt-dlp session.

        A Sync call waits its turn, and retries with backoff while YouTube throttles or can't be reached; a web UI
        call does neither, so it answers promptly. Raises _Failed with the classified error, or VideoUnavailable.
        """
        attempt = 0
        while True:
            if sync:
                wait = self._next_sync_call - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
            logger = _Log()
            params: dict[str, object] = {
                "quiet": True,
                # yt-dlp reports captions withheld for a PO token only in its verbose output.
                "verbose": True,
                "logger": logger,
                "skip_download": True,
                "extract_flat": "in_playlist",
                "socket_timeout": 30,
                "extractor_args": {"youtube": {k: list(v) for k, v in self._extractor_args().items()}},
            }
            if sync:
                params["sleep_interval_requests"] = _jitter(_REQUEST_PAUSE_SECONDS)
            if self._settings.cookie_file is not None:
                params["cookiefile"] = str(self._settings.cookie_file)
            if self._settings.cookies_from_browser is not None:
                params["cookiesfrombrowser"] = cookies_from_browser(self._settings.cookies_from_browser)
            failed: _Failed | None = None
            try:
                with self._session, yt_dlp.YoutubeDL(params) as ydl:
                    return work(ydl, logger)
            except (VideoUnavailable, _CaptionsRefused):
                # A refused caption request fails its Video at once; the Sync worker decides when to stop.
                raise
            except _Failed as e:
                failed, error = e, e.error
            except Exception as e:
                error = classify_error(str(e), _http_status(e))
            finally:
                if sync:
                    self._next_sync_call = time.monotonic() + _jitter(self._settings.delay_seconds)
            if not sync or error.kind not in ("throttled", "unreachable") or attempt >= self._settings.retries:
                raise failed or _Failed(error)
            wait = self._settings.backoff_seconds * 2**attempt
            log.warning("%s; retrying in %s s", error.message, wait)
            time.sleep(wait)
            attempt += 1


def _tab_entries(
    url: str, known_ids: Collection[str]
) -> Callable[[Any, _Log], tuple[str | None, list[Mapping[str, Any]]]]:
    def extract(ydl: Any, _: _Log) -> tuple[str | None, list[Mapping[str, Any]]]:
        # process=False leaves the entries as a generator that fetches a page at a time, so stopping early
        # spares the requests for the pages of Videos already known.
        info = ydl.extract_info(url, download=False, process=False)
        return avatar_url(info), take_until_known(info.get("entries") or [], known_ids)

    return extract


# YouTube serves an avatar at whatever size its =sNNN suffix asks; the UI draws one at most 44 px across, so 176
# stays sharp on any screen without fetching the 900 px original.
_AVATAR_SIZE = re.compile(r"=s\d+(?=-|$)")


def avatar_url(info: Mapping[str, Any]) -> str | None:
    """The channel's avatar from a channel tab extraction's thumbnails, which hold its banners too."""
    thumbnails = [t for t in info.get("thumbnails") or [] if isinstance(t.get("url"), str)]
    # The square crop YouTube shows, else the uploaded original.
    square = [t for t in thumbnails if isinstance(t.get("width"), int) and t.get("width") == t.get("height")]
    uncropped = [t for t in thumbnails if t.get("id") == "avatar_uncropped"]
    candidates = [*square, *uncropped]
    return _AVATAR_SIZE.sub("=s176", candidates[0]["url"], count=1) if candidates else None


def take_until_known(
    entries: Iterable[Mapping[str, Any]], known_ids: Collection[str], page_size: int = PAGE_SIZE
) -> list[Mapping[str, Any]]:
    """The entries up to the end of the first full page holding only known ids; all of them when none are known."""
    taken: list[Mapping[str, Any]] = []
    run = 0
    for entry in entries:
        taken.append(entry)
        run = run + 1 if entry.get("id") in known_ids else 0
        if known_ids and run >= page_size and len(taken) % page_size == 0:
            break
    return taken


def cookies_from_browser(text: str) -> tuple[str, str | None, str | None, str | None]:
    """yt-dlp's cookiesfrombrowser parameter from its BROWSER[+KEYRING][:PROFILE][::CONTAINER] form."""
    match = re.fullmatch(
        r"(?P<name>[^+:]+)(?:\s*\+\s*(?P<keyring>[^:]+))?(?:\s*:\s*(?!:)(?P<profile>.+?))?(?:\s*::\s*(?P<container>.+))?",
        text,
    )
    if match is None:
        raise ValueError(f"invalid cookies from browser: {text!r}")
    name, keyring, profile, container = match.group("name", "keyring", "profile", "container")
    return (name.strip().lower(), profile, keyring and keyring.strip().upper(), container)


def _http_status(error: BaseException) -> int | None:
    # yt-dlp raises DownloadError wrapping the original exception, or an HTTPError from urlopen directly.
    exc_info = getattr(error, "exc_info", None)
    cause = exc_info[1] if exc_info else error
    for candidate in (cause, getattr(cause, "cause", None)):
        if isinstance(candidate, HTTPError):
            return int(candidate.status)
    return None


def _is_missing(error: "YouTubeError") -> bool:
    return error.kind == "not_found" or (error.kind == "unavailable" and error.permanent)


def _channel_error(error: "YouTubeError", channel: str) -> Exception:
    if _is_missing(error):
        return ChannelNotFound(f"No YouTube channel found for {channel}")
    return SourceUnavailable(error.message)


def channel_url(text: str) -> str:
    """The canonical URL for a YouTube channel URL, @handle, or channel id.

    Only these reach yt-dlp, whose generic extractor would otherwise fetch any URL it is given.
    """
    text = text.strip()
    if _HANDLE.fullmatch(text):
        return f"{_YOUTUBE}/{urllib.parse.quote(text, safe='@')}"
    if _CHANNEL_ID.fullmatch(text):
        return f"{_YOUTUBE}/channel/{text}"
    if re.match(r"(?:www\.|m\.)?youtube\.com/", text, flags=re.IGNORECASE):
        text = f"https://{text}"
    parts = urllib.parse.urlsplit(text)
    segments = [urllib.parse.unquote(s) for s in parts.path.split("/") if s]
    if parts.scheme in ("http", "https") and parts.hostname in _HOSTS and segments:
        first = segments[0]
        if _HANDLE.fullmatch(first):
            return f"{_YOUTUBE}/{urllib.parse.quote(first, safe='@')}"
        if len(segments) > 1 and first == "channel" and _CHANNEL_ID.fullmatch(segments[1]):
            return f"{_YOUTUBE}/channel/{segments[1]}"
        if len(segments) > 1 and first in ("c", "user") and _LEGACY_NAME.fullmatch(segments[1]):
            return f"{_YOUTUBE}/{first}/{urllib.parse.quote(segments[1])}"
    raise ChannelNotFound(_NOT_A_CHANNEL)


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


def playlist_id(text: str) -> str:
    """The playlist id a playlist, watch, or share URL carries in its list parameter, or the id given alone.

    Only the id reaches yt-dlp, in a URL built here.
    """
    text = text.strip()
    listed = urllib.parse.parse_qs(urllib.parse.urlsplit(text).query).get("list")
    found = listed[0] if listed else text
    if not _PLAYLIST_ID.fullmatch(found):
        raise PlaylistNotFound(_NOT_A_PLAYLIST)
    return found


def playlist_listing(info: Mapping[str, Any]) -> PlaylistListing:
    """A flat playlist extraction's title and entries, in its order.

    An entry without a creator's channel id is a video YouTube hides (private or deleted): it is left out of the
    entries, and only its id is kept, which says the playlist still lists it.
    """
    listed = [entry for entry in info.get("entries") or [] if entry.get("id")]
    return PlaylistListing(
        title=info.get("title") or info["id"],
        entries=[
            PlaylistEntry(
                video_id=entry["id"],
                title=entry.get("title") or entry["id"],
                duration_seconds=_integer(entry.get("duration")),
                channel_id=entry["channel_id"],
                channel_name=entry.get("channel") or entry["channel_id"],
            )
            for entry in listed
            if entry.get("channel_id")
        ],
        video_ids=[entry["id"] for entry in listed],
    )


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
        raise VideoUnavailable(live, permanent=False)
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
        storyboard=storyboard(info),
    )


# The best storyboard yt-dlp exposes; the tiers below it are smaller copies of the same frames.
_BEST_SHEET = "sb0"
# A sheet URL's path ends in the sheet's number: .../storyboard3_L3/M0.jpg.
_SHEET_PATH = re.compile(r"(?P<prefix>.*/)M(?P<index>\d+)(?P<suffix>\.[A-Za-z0-9]+)")


def _sheet_template(urls: Sequence[str]) -> str | None:
    """The one URL every sheet shares, with {index} where its number goes; None if they don't all share one.

    The signature (sqp/sigh) is a query parameter, and a sheet fetched without it is refused, so a template is
    only honest while every sheet carries the same one. Measured over 25 Videos they always did -- but a Video
    whose sheets disagree is better treated as having no storyboard than stored under a template that 403s.
    """
    templates = set()
    for index, url in enumerate(urls):
        parts = urllib.parse.urlsplit(url)
        match = _SHEET_PATH.fullmatch(parts.path)
        if match is None or int(match["index"]) != index:
            return None
        templates.add(parts._replace(path=f"{match['prefix']}M{{index}}{match['suffix']}").geturl())
    return templates.pop() if len(templates) == 1 else None


def storyboard(info: Mapping[str, Any]) -> Storyboard | None:
    """The geometry of the Video's best scrubber storyboard, or None when the extraction offers none this can use.

    Costs no request of its own: the storyboard formats come with the metadata and captions a Sync already fetches.
    """
    sheets = [f for f in info.get("formats") or [] if f.get("format_id") == _BEST_SHEET]
    if not sheets:
        return None
    sheet = sheets[0]
    grid = [sheet.get(key) for key in ("columns", "rows", "width", "height")]
    fps = sheet.get("fps")
    urls = [f["url"] for f in sheet.get("fragments") or [] if f.get("url")]
    if not all(isinstance(value, int) and value > 0 for value in grid):
        return None
    if not isinstance(fps, int | float) or fps <= 0 or not urls:
        return None
    template = _sheet_template(urls)
    if template is None:
        return None
    columns, rows, width, height = (int(value) for value in grid)
    return Storyboard(
        columns=columns,
        rows=rows,
        width=width,
        height=height,
        fps=float(fps),
        url_template=template,
        fragment_count=len(urls),
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


def caption_track(
    info: Mapping[str, Any], po_token_messages: Sequence[str], details: VideoDetails, today: date | None = None
) -> CaptionTrack:
    """The English captions to ingest: manual subtitles first, else automatic captions of English speech.

    Automatic captions come in every language by translation; the "-orig" track is the spoken language. Without one,
    only a lone automatic track (a language YouTube doesn't translate) can be trusted to be what was spoken. A Video
    published within CAPTIONS_GRACE of `today` may not have its automatic captions yet, so its lack of them is
    transient.
    """
    manual = {key: formats for key, formats in (info.get("subtitles") or {}).items() if key != "live_chat"}
    automatic = info.get("automatic_captions") or {}
    for key in sorted(manual, key=lambda k: k != "en"):
        if _language(key) == "en" and (url := _json3_url(manual[key])):
            return CaptionTrack(source="youtube_manual", url=url)
    spoken_tracks = [key for key in automatic if key.endswith("-orig")] or (list(automatic) if len(automatic) == 1 else [])
    for key in spoken_tracks:
        if _language(key) == "en" and (url := _json3_url(automatic[key])):
            return CaptionTrack(source="youtube_auto", url=url)
    languages = [_language(key) for key in [*spoken_tracks, *manual] if _language(key) != "en"]
    if languages:
        raise VideoUnavailable(
            f"Captions are in {languages[0]!r}; only English is ingested",
            permanent=True,
            language=languages[0],
            details=details,
        )
    # Formats withheld for a PO token are reported too; only the subtitle reports explain missing captions.
    if any("subtitles" in m.lower() and "not provided" in m.lower() for m in po_token_messages):
        raise VideoUnavailable(f"No captions: {_PO_TOKEN_FIX}", permanent=False, details=details)
    if (today or datetime.now(UTC).date()) - details.published_on <= CAPTIONS_GRACE:
        raise VideoUnavailable(
            "No captions yet; YouTube may still be generating them for this new Video", permanent=False, details=details
        )
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
        return YouTubeError("unavailable", f"{text}. {_PO_TOKEN_FIX}", permanent=False)
    # YouTube answers 403 to an address it has started blocking.
    if http_status in (403, 429) or mentions(
        "too many requests", "not a bot", "captcha", "rate-limited", "try again later"
    ):
        return YouTubeError(
            "throttled",
            f"YouTube is rate limiting requests ({text}); try again later, or configure youtube_cookie_file",
            permanent=False,
        )
    if (http_status is not None and http_status >= 500) or (
        http_status is None
        and mentions("unable to download", "timed out", "connection", "name resolution", "network is unreachable", "ssl")
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
        return YouTubeError("unavailable", f"Upcoming live stream or premiere ({text})", permanent=False)
    if mentions("private video"):
        return YouTubeError("unavailable", "Private Video", permanent=True)
    if mentions("available in your country"):
        return YouTubeError("unavailable", "Not available in this country", permanent=True)
    if mentions("private", "unavailable", "removed", "terminated", "no longer available", "not available"):
        return YouTubeError("unavailable", text, permanent=True)
    return YouTubeError("other", f"YouTube error: {text}", permanent=False)
