"""`seek export` and `seek import`: one Channel's or one Playlist's indexed Videos as a Bundle, a `.seek` file
another Seek imports.

A Bundle is a single SQLite database in plain tables, so any SQLite reads it without extensions. Nothing in it is
keyed by a local id: Videos go by their YouTube ids and Segments by their order within the Video. Both commands run
in this process against the knowledge base, never through the server.
"""

import importlib.metadata
import json
import math
import os
import re
import sqlite3
import struct
import tempfile
import threading
import unicodedata
import uuid
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Sequence
from contextlib import closing, contextmanager, suppress
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import ConfigDict, TypeAdapter, ValidationError

from seek import channels, db, playlists, sync_worker, syncs
from seek.channels import Channel, ChannelFilters
from seek.channels_api import FiltersBody
from seek.config import Config
from seek.fields import Name
from seek.playlists import Playlist
from seek.ports import Chapter, ChannelInfo, Cue, PlaylistInfo
from seek.segmentation import SegmentCue
from seek.sync_command import SyncCommandError, find_channel, find_playlist
from seek.videos import ExclusionRules, exclusion, judge_included

# The ASCII bytes of "SEEK", kept in the SQLite header: how import tells a Bundle from any other SQLite file.
APPLICATION_ID = 0x5345454B
FORMAT_VERSION = 1
Kind = Literal["channel", "playlist"]
EXTENSION = ".seek"

# What every Bundle holds. Vectors are the knowledge base's own bytes: little-endian float32, four per dimension.
_SCHEMA = """
    CREATE TABLE meta (
        format_version INTEGER NOT NULL,
        seek_version TEXT NOT NULL,
        embedding_model TEXT NOT NULL,
        embedding_dimension INTEGER NOT NULL,
        kind TEXT NOT NULL,
        exported_at TEXT NOT NULL
    );
    CREATE TABLE videos (
        youtube_video_id TEXT PRIMARY KEY,
        youtube_channel_id TEXT NOT NULL,
        title TEXT NOT NULL,
        duration_seconds INTEGER,
        published_on TEXT,
        description TEXT,
        chapters TEXT,
        language TEXT
    );
    CREATE TABLE transcripts (
        youtube_video_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        language TEXT NOT NULL,
        cues TEXT NOT NULL,
        fetched_at TEXT NOT NULL
    );
    CREATE TABLE segments (
        youtube_video_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        start_seconds REAL NOT NULL,
        end_seconds REAL NOT NULL,
        text TEXT NOT NULL,
        chapter_title TEXT,
        context TEXT NOT NULL,
        cues TEXT NOT NULL,
        embedding BLOB NOT NULL,
        PRIMARY KEY (youtube_video_id, ordinal)
    );
"""


# The Bundle's one Library entry, in tables of its kind's own: a Channel with the filters that travel, or a
# Playlist with the creators its Videos are credited to and each Video's place in it.
_ENTRY_SCHEMA: dict[Kind, str] = {
    "channel": """
        CREATE TABLE channel (
            youtube_channel_id TEXT NOT NULL,
            name TEXT NOT NULL,
            avatar_url TEXT,
            published_after TEXT,
            published_before TEXT,
            most_recent INTEGER
        );
    """,
    "playlist": """
        CREATE TABLE playlist (
            youtube_playlist_id TEXT NOT NULL,
            name TEXT NOT NULL
        );
        CREATE TABLE creators (
            youtube_channel_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            avatar_url TEXT
        );
        CREATE TABLE playlist_videos (
            youtube_video_id TEXT PRIMARY KEY,
            position INTEGER NOT NULL
        );
    """,
}

# The tables import reads, by the Bundle's kind.
_TABLES: dict[Kind, set[str]] = {
    "channel": {"meta", "channel", "videos", "transcripts", "segments"},
    "playlist": {"meta", "playlist", "creators", "playlist_videos", "videos", "transcripts", "segments"},
}
# The pattern the web API accepts for a playlist id. A Sync puts a Bundle's ids in the URLs it asks yt-dlp for.
_YOUTUBE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
# As long as the web API lets a name be; YouTube stops a title at half that.
_NAME_LENGTH = 200
# Several times the longest text a Sync stores in one piece: YouTube stops a description at 5,000 characters, and
# a Segment is a minute and a half of speech.
_TEXT_LENGTH = 20_000
# Control characters, and the two separators that break a line as they do: a name and a title are one line each.
_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
# The whitespace other than a space, which a Sync collapses out of every caption, so nothing said holds any.
_LINE_BREAKS = re.compile(r"[\t\n\x0b\x0c\r\x1c-\x1f\x85\u2028\u2029]")
# No text of a Bundle holds one: YouTube gives none, and C code that reads text stops at the first.
_NUL = "\x00"
# Bidi embeddings, overrides, and isolates, which reorder the line a name is printed on. Other format characters
# stay: YouTube's names join emoji with one.
_REORDERING = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
# Where YouTube serves a channel's avatar from. The whole prefix is matched, so nothing later in the URL can name
# another server.
_AVATAR_HOSTS = ("https://yt3.ggpht.com/", "https://yt3.googleusercontent.com/")
# Several times the longest avatar URL YouTube gives, which run to a couple of hundred characters.
_AVATAR_LENGTH = 2_000
# What a Sync accepts of a Transcript: YouTube's captions, in English.
_SOURCES = ("youtube_auto", "youtube_manual")
_LANGUAGE = "en"

# The JSON columns read strictly, as the shapes Seek stores: a key too many, or a number written as text, would
# break every search and listing that reads the row.
_AS_STORED = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
_CHAPTERS = TypeAdapter(list[Chapter], config=_AS_STORED)
_TRANSCRIPT_CUES = TypeAdapter(list[Cue], config=_AS_STORED)
_SEGMENT_CUES = TypeAdapter(list[SegmentCue], config=_AS_STORED)
# The name `--name` gives, held to what the web API takes for one.
_NAME: TypeAdapter[str] = TypeAdapter(Name)


@dataclass(frozen=True)
class ExportReport:
    # Where the Bundle was written.
    path: Path
    # The Channel's or the Playlist's.
    name: str
    videos: int
    segments: int
    size_bytes: int
    # The Channel has a Playlist filter, which a Bundle never carries.
    playlist_filter_left_out: bool


@dataclass(frozen=True)
class ImportReport:
    """What an import did. Every Video in the Bundle is counted once, in `added`, `already_indexed`, or `left_out`."""

    kind: Kind
    # The Channel's or the Playlist's name here, and its id on YouTube.
    name: str
    youtube_id: str
    # False when it was in the Library already, where it keeps its name and every setting.
    created: bool
    # The filters that arrived with a Channel import created; None otherwise.
    filters: ChannelFilters | None
    # Videos that became searchable from the Bundle.
    added: int
    # Videos that were done here already, left as they were.
    already_indexed: int
    # Videos the Bundle did not fill in, counted by the reason.
    left_out: dict[str, int]


class PlaylistNameTaken(SyncCommandError):
    """Import's refusal of a Playlist whose name another Playlist of the Library has, told apart from its others
    because what to do about it depends on who asked: `seek import` has a flag for it, and the web UI has none.

    `name` is the name as that other Playlist has it.
    """

    def __init__(self, name: str, remedy: str = "import this one under another name with --name") -> None:
        super().__init__(f"A Playlist named {name!r} already exists; {remedy}")
        self.name = name


def _seek_version() -> str:
    try:
        return importlib.metadata.version("seek")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _open_knowledge_base(config: Config) -> None:
    """Opens and migrates the knowledge base as the server does, with the Config's embedding model."""
    try:
        db.initialize(config.database_path, config.embedding_model, config.embedding_dimension)
    except RuntimeError as e:
        # The knowledge base belongs to another embedding model or a newer Seek.
        raise SyncCommandError(str(e)) from e


@dataclass(frozen=True)
class _Entry:
    """What export found to write: the Channel or Playlist, and its searchable Videos in the order they go in."""

    kind: Kind
    name: str
    # The rows of the entry's own tables, each as a statement and its values.
    rows: list[tuple[str, Sequence[object]]]
    videos: list[sqlite3.Row]
    playlist_filter_left_out: bool = False


# A Video as a Bundle carries it, with the YouTube channel id of the Channel it is credited to.
_VIDEO_COLUMNS = """
    videos.id, videos.youtube_video_id, channels.youtube_channel_id, videos.title, videos.duration_seconds,
    videos.published_on, videos.description, videos.chapters, videos.language
"""


def export_channel(config: Config, channel: str, path: Path, called: str | None = None) -> ExportReport:
    """Writes the Channel with this name or YouTube channel id to a Bundle at the path, adding `.seek` when the
    path lacks it.

    The Bundle holds the Channel's searchable Videos, Paused or not. It is read in one read transaction, so it is
    a consistent snapshot even while a Sync writes; no Sync lease is taken and no model is loaded.

    A refusal names the Bundle by its path, or by `called` as it stands when that is given: the server gives one,
    since where it writes a Bundle is a path of its own that the page asking has no business reading.
    """

    def entry(conn: sqlite3.Connection) -> _Entry:
        found = find_channel(channels.list_channels(conn), channel)
        videos = conn.execute(
            f"""
            SELECT {_VIDEO_COLUMNS}
            FROM videos JOIN channels ON channels.id = videos.channel_id
            WHERE videos.channel_id = ? AND videos.pipeline_stage = 'done' AND videos.excluded_reason IS NULL
            ORDER BY videos.id
            """,
            (found.id,),
        ).fetchall()
        # The Playlist filter stays behind: it names a YouTube playlist every Sync of the recipient's would have
        # to list, and one they can't see would fail each of them.
        row = (
            """
            INSERT INTO channel (youtube_channel_id, name, avatar_url, published_after, published_before,
                                 most_recent)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                found.youtube_channel_id,
                found.name,
                found.avatar_url,
                found.filters.published_after and found.filters.published_after.isoformat(),
                found.filters.published_before and found.filters.published_before.isoformat(),
                found.filters.most_recent,
            ),
        )
        return _Entry("channel", found.name, [row], videos, found.filters.playlist_id is not None)

    return _export(config, path, entry, called)


def export_playlist(config: Config, playlist: str, path: Path, called: str | None = None) -> ExportReport:
    """Writes the Playlist with this name or YouTube playlist id to a Bundle at the path, as `export_channel`
    writes a Channel.

    The Bundle holds the searchable Videos the Playlist includes, Paused or not, each with its place in the
    Playlist, and the creators they are credited to, in the Library or outside it.
    """

    def entry(conn: sqlite3.Connection) -> _Entry:
        found = find_playlist(playlists.list_playlists(conn), playlist)
        videos = conn.execute(
            f"""
            SELECT {_VIDEO_COLUMNS}, playlist_videos.position
            FROM playlist_videos
            JOIN videos ON videos.id = playlist_videos.video_id
            JOIN channels ON channels.id = videos.channel_id
            WHERE playlist_videos.playlist_id = ? AND videos.pipeline_stage = 'done'
              AND videos.excluded_reason IS NULL
            ORDER BY playlist_videos.position, videos.id
            """,
            (found.id,),
        ).fetchall()
        creators = conn.execute(
            """
            SELECT youtube_channel_id, name, avatar_url FROM channels
            WHERE youtube_channel_id IN (SELECT value FROM json_each(?)) ORDER BY id
            """,
            (json.dumps(sorted({video["youtube_channel_id"] for video in videos})),),
        ).fetchall()
        rows: list[tuple[str, Sequence[object]]] = [
            ("INSERT INTO playlist (youtube_playlist_id, name) VALUES (?, ?)", (found.youtube_playlist_id, found.name)),
            *(
                ("INSERT INTO creators (youtube_channel_id, name, avatar_url) VALUES (?, ?, ?)", tuple(creator))
                for creator in creators
            ),
            *(
                (
                    "INSERT INTO playlist_videos (youtube_video_id, position) VALUES (?, ?)",
                    (video["youtube_video_id"], video["position"]),
                )
                for video in videos
            ),
        ]
        return _Entry("playlist", found.name, rows, videos)

    return _export(config, path, entry, called)


def _export(
    config: Config, path: Path, find: Callable[[sqlite3.Connection], _Entry], called: str | None
) -> ExportReport:
    """Writes the entry `find` reads from the knowledge base to a Bundle at the path."""
    if path.is_dir():
        raise SyncCommandError(f"{called or path} is a directory; give the file to write the Bundle to")
    destination = path if path.name.endswith(EXTENSION) else path.with_name(path.name + EXTENSION)
    _refuse_existing(destination, called)
    _open_knowledge_base(config)
    with closing(db.connect(config.database_path)) as conn:
        # Left open until the connection closes: every read below sees the knowledge base as it is now.
        conn.execute("BEGIN")
        entry = find(conn)
        if not entry.videos:
            raise SyncCommandError(f"The {entry.kind.capitalize()} {entry.name!r} has no indexed Videos to export")
        model = conn.execute("SELECT name, dimension FROM embedding_model").fetchone()
        # Written under another name and renamed once complete, so a `.seek` file is never half a Bundle.
        temporary, bundle = _new_bundle(destination, entry.kind, called)
        try:
            with closing(bundle):
                bundle.execute(
                    """
                    INSERT INTO meta (format_version, seek_version, embedding_model, embedding_dimension, kind,
                                      exported_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (FORMAT_VERSION, _seek_version(), model["name"], model["dimension"], entry.kind, db.now_iso()),
                )
                for statement, values in entry.rows:
                    bundle.execute(statement, values)
                segments = sum(_export_video(conn, bundle, video) for video in entry.videos)
                bundle.execute("COMMIT")
            # Again, since the write can take minutes and a rename replaces what is there without a word.
            _refuse_existing(destination, called)
            temporary.rename(destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    return ExportReport(
        destination,
        entry.name,
        len(entry.videos),
        segments,
        destination.stat().st_size,
        entry.playlist_filter_left_out,
    )


def _refuse_existing(destination: Path, called: str | None) -> None:
    if destination.exists():
        raise SyncCommandError(f"{called or destination} already exists; export never replaces a file")


def _new_bundle(destination: Path, kind: Kind, called: str | None) -> tuple[Path, sqlite3.Connection]:
    """An empty Bundle of that kind under a temporary name beside the destination, inside a transaction for the
    caller to commit; returns that name with it.

    The file is created here, exclusively and under a name nobody can guess, and is readable by its owner alone:
    in a directory others can write to, a link planted where the Bundle was about to go would otherwise have the
    Transcripts written through it. SQLite opens it again by name, so a directory where another user can rename
    files (one that is writable by them and not sticky) is still no place to export to.
    """
    try:
        handle, name = tempfile.mkstemp(dir=destination.parent, prefix=f"{destination.name}.", suffix=".tmp")
        os.close(handle)
    except OSError as e:
        # The system's error names the file as well, so a caller that keeps the path out gets its reason alone.
        reason = e if called is None else e.strerror
        raise SyncCommandError(f"Could not write {called or destination}: {reason}") from e
    temporary = Path(name)
    try:
        bundle = sqlite3.connect(temporary, autocommit=True)
        bundle.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        # No journal while writing: a failed export deletes the file anyway, and a journal would be a second file
        # at a name derived from this one. The mode is not stored, so the Bundle opens with a rollback journal,
        # never WAL, and is always exactly one file.
        bundle.execute("PRAGMA journal_mode = OFF")
        bundle.execute("BEGIN")
        bundle.executescript(_SCHEMA + _ENTRY_SCHEMA[kind])
    except sqlite3.Error as e:
        temporary.unlink(missing_ok=True)
        raise SyncCommandError(f"Could not write {called or destination}: {e}") from e
    return temporary, bundle


def format_export(report: ExportReport) -> str:
    megabytes = report.size_bytes / 1_000_000
    size = f"{megabytes:.1f} MB" if megabytes >= 1 else f"{max(1, report.size_bytes // 1000)} KB"
    counts = f"{report.videos} Videos, {report.segments} Segments, {size}"
    lines = [
        f"Exported {report.name} to {report.path}: {counts}.",
        "The file contains the creators' full Transcripts, so choose who you share it with.",
    ]
    if report.playlist_filter_left_out:
        lines.append(
            "The Channel's Playlist filter was left out, so the recipient's Syncs will bring in its other Videos."
        )
    return "\n".join(lines)


def _export_video(conn: sqlite3.Connection, bundle: sqlite3.Connection, video: sqlite3.Row) -> int:
    """Copies one Video, its Transcript, and its Segments with their vectors; returns how many Segments."""
    key = {"youtube_video_id": video["youtube_video_id"]}
    bundle.execute(
        """
        INSERT INTO videos (youtube_video_id, youtube_channel_id, title, duration_seconds, published_on,
                            description, chapters, language)
        VALUES (:youtube_video_id, :youtube_channel_id, :title, :duration_seconds, :published_on,
                :description, :chapters, :language)
        """,
        dict(video),
    )
    transcript = conn.execute(
        "SELECT source, language, cues, fetched_at FROM transcripts WHERE video_id = ?", (video["id"],)
    ).fetchone()
    bundle.execute(
        """
        INSERT INTO transcripts (youtube_video_id, source, language, cues, fetched_at)
        VALUES (:youtube_video_id, :source, :language, :cues, :fetched_at)
        """,
        {**dict(transcript), **key},
    )
    segments = conn.execute(
        """
        SELECT id, start_seconds, end_seconds, text, chapter_title, context, cues
        FROM segments WHERE video_id = ? ORDER BY id
        """,
        (video["id"],),
    ).fetchall()
    for ordinal, segment in enumerate(segments):
        # One lookup per Segment id: the vector table finds a row by its id, but scans every vector for any other
        # condition.
        (embedding,) = conn.execute(
            "SELECT embedding FROM segment_vectors WHERE segment_id = ?", (segment["id"],)
        ).fetchone()
        bundle.execute(
            """
            INSERT INTO segments (youtube_video_id, ordinal, start_seconds, end_seconds, text, chapter_title,
                                  context, cues, embedding)
            VALUES (:youtube_video_id, :ordinal, :start_seconds, :end_seconds, :text, :chapter_title,
                    :context, :cues, :embedding)
            """,
            {**dict(segment), **key, "ordinal": ordinal, "embedding": embedding},
        )
    return len(segments)


def import_bundle(
    config: Config,
    path: Path,
    name: str | None = None,
    progress: Callable[[int, int], None] | None = None,
    called: str | None = None,
) -> ImportReport:
    """Merges the Bundle's Channel or Playlist into the Library, its Videos searchable at once: nothing is fetched
    from YouTube and nothing embedded. Creates the knowledge base if there is none yet.

    A Channel not in the Library is added to it, Active and checked daily, under `name` or else the Bundle's, with
    the Bundle's avatar and filters; one known only for crediting a Playlist's Videos keeps those Videos. A Channel
    already in the Library keeps its name and every setting. Then each Video: one that is done here is left exactly
    as it is, one this Seek's own rules exclude or credits to another Channel is left out, and any other is filled
    in from the Bundle.

    A Playlist not yet added is added the same way, and refused when another Playlist has its name; one already
    added keeps its name and settings. It is made to include each Video, which is judged as a Sync of the Playlist
    would judge it: a new one is credited to its creator, who stays outside the Library unless already in it, and
    only the minimum length leaves one out.

    Import runs beside a server, and holds the Sync lease from before its first write until it ends: it is
    refused while a Sync is running, and a Sync queued meanwhile waits for it. Should another process take the
    lease, or the knowledge base be too busy for it to be renewed, it stops before its next Video and says which.
    No record of progress is kept: running the import again repeats the
    merge, which is how an interrupted one resumes. `progress` is called after each of the Bundle's Videos is
    committed, filled in or not, with how many are behind it and how many the Bundle holds.

    A Bundle is untrusted input. It is refused whole, before anything is written, when this build can't read it,
    when it was embedded with another model, or when anything in it is not what a Sync would have stored. Each
    Video is then committed on its own, so a running server's writes wait for one Video at most.

    A refusal names the Bundle by its path, or by `called` as it stands when that is given, as export's does: the
    server imports an upload from a path of its own.
    """
    if name is not None:
        try:
            name = _NAME.validate_python(name)
        except ValidationError as e:
            raise SyncCommandError("A name is 1 to 200 characters") from e
    with _open_bundle(path, called or str(path)) as bundle:
        meta = _meta(bundle)
        model, dimension = config.embedding_model, config.embedding_dimension
        if (meta["embedding_model"], meta["embedding_dimension"]) != (model, dimension):
            # Vectors from two models can't be compared, and a Bundle carries no way to embed its text again.
            raise SyncCommandError(
                f"{bundle.called} was embedded with {meta['embedding_model']} "
                f"({meta['embedding_dimension']} dimensions), "
                f"but this knowledge base uses {model} ({dimension} dimensions); a Bundle imports only into a "
                "knowledge base that uses the same embedding model"
            )
        kind: Kind = meta["kind"]
        if kind == "channel":
            info, filters = _channel(bundle)
            videos = _videos(bundle, {info.channel_id}, "a creator other than the Bundle's Channel")
        else:
            listed = _playlist(bundle)
            creators = _creators(bundle)
            videos = _videos(bundle, creators, "a creator the Bundle does not list")
            positions = _positions(bundle, videos)
        # Every Video is read before the first write: a refusal partway would leave the Library half-changed.
        for youtube_video_id in videos:
            _contents(bundle, youtube_video_id, dimension)
        _open_knowledge_base(config)
        # The lease is taken once the whole Bundle has been checked and before the entry, which is the first write.
        with closing(db.connect(config.database_path)) as conn, _sync_lease(config, conn) as lease_lost:
            entry: Channel | Playlist
            arrived: ChannelFilters | None = None
            if kind == "channel":
                # A Channel already in the Library is the user's own: nothing of the Bundle's entry replaces it.
                existing = [c for c in channels.list_channels(conn) if c.youtube_channel_id == info.channel_id]
                entry = channel = existing[0] if existing else channels.create_channel(conn, info, name, filters)
                youtube_id, created = channel.youtube_channel_id, not existing
                if created:
                    arrived = filters
                # The rules are this Seek's own: its minimum length, and the filters now in force on the Channel.
                rules = ExclusionRules(config.min_duration_seconds, channel.filters)
            else:
                added = [p for p in playlists.list_playlists(conn) if p.youtube_playlist_id == listed.playlist_id]
                entry = playlist = added[0] if added else _create_playlist(conn, listed, name)
                youtube_id, created = playlist.youtube_playlist_id, not added
                # A Video a Playlist includes answers to this Seek's minimum length and to no Channel's filters.
                rules = ExclusionRules(config.min_duration_seconds, ChannelFilters())
            added_videos = already_indexed = 0
            left_out: Counter[str] = Counter()
            for youtube_video_id, video in videos.items():
                if (lost := lease_lost()) is not None:
                    # Whoever has the lease now may be writing these Videos; what is committed stays.
                    behind = added_videos + already_indexed + left_out.total()
                    raise SyncCommandError(
                        f"{lost} after {behind} of {len(videos)} Videos; run the import again to carry on where it "
                        "stopped"
                    )
                # Read again rather than kept since the check: a Channel's vectors run to a hundred megabytes.
                transcript, segments = _contents(bundle, youtube_video_id, dimension)
                with db.transaction(conn):
                    if kind == "playlist":
                        creator = creators[cast(str, video["youtube_channel_id"])]
                        _include(conn, playlist.id, positions[youtube_video_id], rules, creator, video)
                    known = conn.execute(
                        "SELECT channel_id, pipeline_stage, excluded_reason FROM videos WHERE youtube_video_id = ?",
                        (youtube_video_id,),
                    ).fetchone()
                    if kind == "playlist":
                        # Whoever the Video is credited to here: it keeps that Channel.
                        reason, credited = cast(str | None, known["excluded_reason"]), cast(int, known["channel_id"])
                    else:
                        reason, credited = _left_out(channel, rules, video, known), channel.id
                    if reason is not None:
                        left_out[reason] += 1
                    elif known is not None and known["pipeline_stage"] == "done":
                        already_indexed += 1
                    else:
                        _import_video(conn, credited, video, transcript, segments)
                        added_videos += 1
                if progress is not None:
                    progress(added_videos + already_indexed + left_out.total(), len(videos))
    return ImportReport(
        kind,
        entry.name,
        youtube_id,
        created,
        arrived,
        added_videos,
        already_indexed,
        dict(left_out),
    )


# How import says it lost the Sync lease, each the start of a sentence that ends with how far it had got.
_LEASE_TAKEN = "Another seek process took over running Syncs"
_LEASE_NOT_RENEWED = "The knowledge base was too busy for the import to keep its hold on Syncs"


@contextmanager
def _sync_lease(config: Config, conn: sqlite3.Connection) -> Iterator[Callable[[], str | None]]:
    """Holds the Sync lease as the worker does, so that import is the one process writing Videos, and gives it up
    however the block ends. Refuses while a Sync holds it.

    Yields a check to make before each Video: None while the lease is held, or else how it was lost, to another
    process or to a knowledge base too busy for it to be renewed. A background thread renews the lease at the
    worker's cadence meanwhile, since one Video, or whoever is told of the progress, may take longer than the
    lease lasts.
    """
    holder = uuid.uuid4().hex
    # Read when called, here and below, not once at import: the lease test shortens it.
    if not syncs.acquire_lease(conn, holder, sync_worker.LEASE_SECONDS):
        raise SyncCommandError("A Sync is running; run the import again when it has finished")
    lost: list[str] = []
    ended = threading.Event()

    def renew() -> None:
        # On a connection of its own: a SQLite connection stays with the thread that opened it.
        with closing(db.connect(config.database_path)) as own:
            while not ended.wait(sync_worker.LEASE_SECONDS / 4):
                try:
                    renewed = syncs.renew_lease(own, holder, sync_worker.LEASE_SECONDS)
                except sqlite3.Error:
                    # Another write outlasted the busy timeout. The lease may have run out by the next try.
                    lost.append(_LEASE_NOT_RENEWED)
                    return
                if not renewed:
                    lost.append(_LEASE_TAKEN)
                    return

    def how_lost() -> str | None:
        if lost:
            return lost[0]
        # Renewed here too, so a lease another process took is found out now, not a quarter of a lease later.
        try:
            return None if syncs.renew_lease(conn, holder, sync_worker.LEASE_SECONDS) else _LEASE_TAKEN
        except sqlite3.OperationalError:
            return _LEASE_NOT_RENEWED

    renewing = threading.Thread(target=renew, daemon=True)
    renewing.start()
    try:
        yield how_lost
    finally:
        try:
            ended.set()
            renewing.join()
        finally:
            # Even when a second Ctrl+C ends the wait for the thread. Only this holder's lease goes, never one
            # another process took. A release that fails must not replace whatever ended the import; the lease
            # expires on its own.
            with suppress(sqlite3.Error):
                syncs.release_lease(conn, holder)


def _create_playlist(conn: sqlite3.Connection, listed: PlaylistInfo, name: str | None) -> Playlist:
    """Adds the Bundle's Playlist under the name, or else the Bundle's own, refusing a name another Playlist has."""
    taken = conn.execute(
        "SELECT name FROM playlists WHERE name = ? COLLATE NOCASE", (name or listed.title,)
    ).fetchone()
    if taken is not None:
        # The name is this Library's own, never the Bundle's: the row is one the user named.
        raise PlaylistNameTaken(taken["name"])
    return playlists.create_playlist(conn, listed, name)


def _include(
    conn: sqlite3.Connection,
    playlist_id: int,
    position: int,
    rules: ExclusionRules,
    creator: ChannelInfo,
    video: dict[str, object],
) -> None:
    """Within a transaction: the Playlist includes the Bundle's Video, judged as a Playlist Sync's discovery judges
    one it includes.

    A Video not yet known is recorded as discovered and credited to its creator, and a creator not yet known
    becomes a Channel outside the Library; a Channel already known is not touched. A Video already known keeps
    its Channel, and is judged again by the code that discovery judges it with: the minimum length alone, which
    lifts an exclusion by its Channel's filters and no other. One that is done and searchable is not judged:
    nothing of an import reaches it, and its own next Sync judges it. A Video the Playlist already includes keeps
    the place it has, which a Sync's listing gave it.
    """
    row = conn.execute(
        "SELECT id, duration_seconds, pipeline_stage, excluded_reason FROM videos WHERE youtube_video_id = ?",
        (video["youtube_video_id"],),
    ).fetchone()
    if row is None:
        row = conn.execute(
            """
            INSERT INTO videos (channel_id, youtube_video_id, title, duration_seconds, excluded_reason, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                channels.credited_channel(conn, creator),
                video["youtube_video_id"],
                video["title"],
                video["duration_seconds"],
                exclusion(rules, cast(int, video["duration_seconds"]), None, included=True),
                db.now_iso(),
            ),
        ).fetchone()
    elif row["pipeline_stage"] != "done" or row["excluded_reason"] is not None:
        judge_included(conn, row, rules)
    conn.execute(
        """
        INSERT INTO playlist_videos (playlist_id, video_id, position) VALUES (?, ?, ?)
        ON CONFLICT (playlist_id, video_id) DO NOTHING
        """,
        (playlist_id, row["id"], position),
    )


def format_import(report: ImportReport) -> str:
    left_out = sum(report.left_out.values())
    counts = f"{report.added} Videos added, {report.already_indexed} already indexed, {left_out} left out"
    lines = [f"Imported {report.name}: {counts}."]
    lines += [f"  {reason}: {count}" for reason, count in report.left_out.items()]
    if not report.created:
        lines.append("It was already in the Library, and keeps its name and settings.")
    elif report.filters is not None and (arrived := _described(report.filters)):
        lines.append(f"It arrived with its filters: {arrived}.")
    since = "published since" if report.kind == "channel" else "added to the playlist since"
    lines += [
        "The Bundle's text came from whoever made the file, and is only as trustworthy as they are.",
        f"Next, start a Sync to pick up the Videos {since}: seek sync --{report.kind} {report.youtube_id}",
    ]
    return "\n".join(lines)


def _described(filters: ChannelFilters) -> str:
    """The date range and most-recent count in the web UI's words; empty when neither is set."""
    return ", ".join(
        part
        for part in (
            filters.published_after and f"published from {filters.published_after.isoformat()}",
            filters.published_before and f"published until {filters.published_before.isoformat()}",
            filters.most_recent and f"the {filters.most_recent} most recent",
        )
        if part
    )


@dataclass(frozen=True)
class _Bundle:
    """A Bundle being read. It is untrusted input, so every read goes through `rows` and every refusal names the
    file, by what it is `called`."""

    called: str
    conn: sqlite3.Connection

    def rows(self, sql: str, parameters: Sequence[object] = ()) -> list[sqlite3.Row]:
        try:
            return self.conn.execute(sql, parameters).fetchall()
        except sqlite3.Error as e:
            # Not a database at all, one without the table, or a virtual table this connection can't open.
            raise self.not_a_bundle() from e

    def not_a_bundle(self) -> SyncCommandError:
        return SyncCommandError(f"{self.called} is not a Seek Bundle")

    def damaged(self, what: str) -> SyncCommandError:
        return SyncCommandError(f"{self.called} is damaged or has been altered: {what}")


@contextmanager
def _open_bundle(path: Path, called: str) -> Iterator[_Bundle]:
    """The file as untrusted input: read-only, on a connection of its own that loads no extension and is never
    attached to the knowledge base's, with the SQL its schema embeds untrusted."""
    try:
        conn = sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True, autocommit=True)
    except sqlite3.Error as e:
        raise SyncCommandError(f"{called} is not a Seek Bundle") from e
    with closing(conn):
        conn.row_factory = sqlite3.Row
        bundle = _Bundle(called, conn)
        bundle.rows("PRAGMA trusted_schema = OFF")
        # Left open until the connection closes, so that what is written is what was checked: SQLite holds off
        # anyone changing the file between the two readings.
        bundle.rows("BEGIN")
        yield bundle


def _meta(bundle: _Bundle) -> sqlite3.Row:
    """The Bundle's one meta record, once the file is known to be a Bundle this build reads."""
    ((application_id,),) = bundle.rows("PRAGMA application_id")
    if application_id != APPLICATION_ID:
        raise bundle.not_a_bundle()
    # A Bundle is plain tables. A view or a virtual table under one of their names would have import run SQL, or a
    # module, of its maker's choosing.
    listed = bundle.rows("PRAGMA table_list")
    plain = {row["name"] for row in listed if (row["schema"], row["type"]) == ("main", "table")}
    # The version is read on its own and first: a later format may keep everything else another way.
    versions = bundle.rows("SELECT format_version FROM meta") if "meta" in plain else []
    if len(versions) != 1:
        raise bundle.not_a_bundle()
    ((version,),) = versions
    if isinstance(version, int) and version > FORMAT_VERSION:
        raise SyncCommandError(
            f"{bundle.called} was made by a newer Seek (Bundle format {version}, this build reads {FORMAT_VERSION}); "
            "upgrade Seek"
        )
    if version != FORMAT_VERSION:
        raise bundle.not_a_bundle()
    (meta,) = bundle.rows("SELECT embedding_model, embedding_dimension, kind FROM meta")
    # The model's name and dimension are quoted in a refusal, so they must be fit to print.
    described = _is_name(meta["embedding_model"]) and type(meta["embedding_dimension"]) is int
    kind = meta["kind"]
    if not (isinstance(kind, str) and kind in _TABLES and _TABLES[kind] <= plain and described):
        raise bundle.not_a_bundle()
    return meta


def _is_youtube_id(value: object) -> bool:
    return isinstance(value, str) and _YOUTUBE_ID.fullmatch(value) is not None


def _is_text(value: object) -> bool:
    """Whether the value is text no longer than a Sync stores. What it holds is not judged: a description, and
    the chapter titles cut from its lines, are kept as YouTube gave them."""
    return isinstance(value, str) and len(value) <= _TEXT_LENGTH


def _is_said(value: object) -> bool:
    """Whether the value is text as a Sync stores what was said: on one line."""
    return _is_text(value) and _LINE_BREAKS.search(cast(str, value)) is None


def _is_title(value: object) -> bool:
    """Whether a title is one Seek can list: a line of no great length with something in it to see."""
    return (
        isinstance(value, str)
        and len(value) <= _NAME_LENGTH
        and _CONTROLS.search(value) is None
        and any(unicodedata.category(character)[0] not in "CZ" for character in value)
    )


def _is_name(value: object) -> bool:
    """Whether a name is fit for import to print: a title with nothing in it that reorders the line."""
    return isinstance(value, str) and _is_title(value) and _REORDERING.search(value) is None


def _iso_date(value: object) -> date | None:
    """The date, when the value is one exactly as Seek writes it: listings parse it, and sort it as text."""
    try:
        parsed = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return parsed if parsed is not None and parsed.isoformat() == value else None


def _is_timestamp(value: object) -> bool:
    # A NUL is refused apart: Python reads a timestamp up to one and takes no notice of what follows it.
    if not isinstance(value, str) or _NUL in value:
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_seconds(value: object) -> bool:
    return isinstance(value, int | float) and math.isfinite(value)


def _channel(bundle: _Bundle) -> tuple[ChannelInfo, ChannelFilters]:
    """The Bundle's one Channel and the filters that travel with it, checked as the web API checks its own."""
    entries = bundle.rows(
        "SELECT youtube_channel_id, name, avatar_url, published_after, published_before, most_recent FROM channel"
    )
    if len(entries) != 1:
        raise bundle.damaged("it does not hold exactly one Channel")
    (entry,) = entries
    if not _is_youtube_id(entry["youtube_channel_id"]):
        raise bundle.damaged("its Channel has an id that is not a YouTube id")
    if not _is_name(entry["name"]):
        raise bundle.damaged("its Channel has a name that is empty, too long, or holds control characters")
    after, before = entry["published_after"], entry["published_before"]
    try:
        if (after is not None and _iso_date(after) is None) or (before is not None and _iso_date(before) is None):
            raise ValueError
        # The ranges, and the order of the two dates, are the ones the web API holds a Channel's filters to.
        body = FiltersBody(
            published_after=_iso_date(after),
            published_before=_iso_date(before),
            playlist_id=None,
            most_recent=entry["most_recent"],
        )
    except ValueError as e:
        raise bundle.damaged("its Channel has filters outside what Seek accepts") from e
    info = ChannelInfo(entry["youtube_channel_id"], entry["name"], _avatar(entry["avatar_url"]))
    return info, ChannelFilters(**body.model_dump())


def _avatar(value: object) -> str | None:
    """The avatar, when YouTube serves it. Any other is dropped: the Library page would load it from whatever
    server the Bundle's maker chose. So is one no URL of YouTube's could be: too long, or holding whitespace or a
    control character. The Channel shows initials until a Sync's listing supplies one."""
    if not (isinstance(value, str) and value.startswith(_AVATAR_HOSTS) and len(value) <= _AVATAR_LENGTH):
        return None
    if _CONTROLS.search(value) is not None or any(character.isspace() for character in value):
        return None
    return value


def _playlist(bundle: _Bundle) -> PlaylistInfo:
    """The Bundle's one Playlist, its id and name checked as a Channel's are."""
    entries = bundle.rows("SELECT youtube_playlist_id, name FROM playlist")
    if len(entries) != 1:
        raise bundle.damaged("it does not hold exactly one Playlist")
    (entry,) = entries
    if not _is_youtube_id(entry["youtube_playlist_id"]):
        raise bundle.damaged("its Playlist has an id that is not a YouTube id")
    if not _is_name(entry["name"]):
        raise bundle.damaged("its Playlist has a name that is empty, too long, or holds control characters")
    (count,) = bundle.rows("SELECT count(*) FROM videos")[0]
    return PlaylistInfo(entry["youtube_playlist_id"], entry["name"], count)


def _creators(bundle: _Bundle) -> dict[str, ChannelInfo]:
    """The creators a Playlist Bundle credits its Videos to, by YouTube channel id, each held to what the Channel
    of a Channel Bundle is: `seek list` and the Library page show a creator as they show a Channel."""
    creators: dict[str, ChannelInfo] = {}
    for row in bundle.rows("SELECT youtube_channel_id, name, avatar_url FROM creators ORDER BY rowid"):
        youtube_channel_id = row["youtube_channel_id"]
        if not _is_youtube_id(youtube_channel_id):
            raise bundle.damaged("one of its creators has an id that is not a YouTube id")
        if youtube_channel_id in creators:
            raise bundle.damaged(f"the creator {youtube_channel_id} is listed twice")
        if not _is_name(row["name"]):
            raise bundle.damaged(
                f"the creator {youtube_channel_id} has a name that is empty, too long, or holds control characters"
            )
        creators[youtube_channel_id] = ChannelInfo(youtube_channel_id, row["name"], _avatar(row["avatar_url"]))
    return creators


def _positions(bundle: _Bundle, videos: Collection[str]) -> dict[str, int]:
    """Each of the Bundle's Videos' place in its Playlist, by YouTube video id. Places need not be next to each
    other: the Videos that were not searchable stayed behind."""
    positions: dict[str, int] = {}
    for row in bundle.rows("SELECT youtube_video_id, position FROM playlist_videos ORDER BY rowid"):
        youtube_video_id, position = row["youtube_video_id"], row["position"]
        # A place given for a Video the Bundle does not list is ignored, as its Transcript would be.
        if youtube_video_id not in videos:
            continue
        if youtube_video_id in positions:
            raise bundle.damaged(f"the Video {youtube_video_id} is given two places in the Playlist")
        if type(position) is not int or position < 0:
            raise bundle.damaged(f"the Video {youtube_video_id} has a place in the Playlist that is not a whole number")
        positions[youtube_video_id] = position
    for youtube_video_id in videos:
        if youtube_video_id not in positions:
            raise bundle.damaged(f"the Video {youtube_video_id} has no place in the Playlist")
    return positions


def _videos(bundle: _Bundle, creators: Collection[str], uncredited: str) -> dict[str, dict[str, object]]:
    """The Bundle's Videos by YouTube id, in the order they were written, each checked to be what the knowledge
    base stores for a Video that is done. `creators` are the YouTube channel ids a Video may be credited to, and
    `uncredited` says what one credited to any other is credited to."""
    videos: dict[str, dict[str, object]] = {}
    for row in bundle.rows(
        """
        SELECT youtube_video_id, youtube_channel_id, title, duration_seconds, published_on, description, chapters,
               language
        FROM videos ORDER BY rowid
        """
    ):
        youtube_video_id = row["youtube_video_id"]
        # Checked first, so that every message after it can name the Video.
        if not _is_youtube_id(youtube_video_id):
            raise bundle.damaged("one of its Videos has an id that is not a YouTube id")
        video = f"the Video {youtube_video_id}"
        if youtube_video_id in videos:
            raise bundle.damaged(f"{video} is listed twice")
        if row["youtube_channel_id"] not in creators:
            raise bundle.damaged(f"{video} is credited to {uncredited}")
        # A title YouTube gave may wrap a number in a left-to-right embedding, so only the Channel's name, which
        # import prints, is held to `_is_name`.
        if not _is_title(row["title"]):
            raise bundle.damaged(f"{video} has a title that is empty, too long, or holds control characters")
        if type(row["duration_seconds"]) is not int or row["duration_seconds"] < 0:
            raise bundle.damaged(f"{video} has a length that is not a whole number of seconds")
        if _iso_date(row["published_on"]) is None:
            raise bundle.damaged(f"{video} has a publish date that is not a date")
        if not isinstance(row["description"], str):
            raise bundle.damaged(f"{video} has a description that is not text")
        if not _is_text(row["description"]):
            raise bundle.damaged(f"{video} has a description that is too long")
        chapters = _json(_CHAPTERS, row["chapters"])
        if chapters is None:
            raise bundle.damaged(f"{video} has chapters that are not a title, a start, and an end each")
        # A title may be empty, which is what a Sync stores for a chapter YouTube gave none.
        if not all(_is_text(chapter.title) for chapter in chapters):
            raise bundle.damaged(f"{video} has a chapter whose title is too long")
        if any(_NUL in text for text in (row["description"], *(chapter.title for chapter in chapters))):
            raise bundle.damaged(f"{video} has a description or a chapter title that holds a NUL character")
        if row["language"] != _LANGUAGE:
            raise bundle.damaged(f"{video} is not in English, and only English is ingested")
        videos[youtube_video_id] = {**dict(row), "chapters": _as_stored(chapters)}
    if not videos:
        # Export refuses to write one, so no Bundle of Seek's making is empty.
        raise bundle.damaged("it holds no Videos")
    return videos


def _json[T](adapter: TypeAdapter[list[T]], value: object) -> list[T] | None:
    """What the JSON holds, or None when it is not text in exactly the shape Seek stores."""
    if not isinstance(value, str):
        return None
    try:
        return adapter.validate_json(value)
    except ValidationError:
        return None


def _as_stored(items: Sequence[Chapter | Cue | SegmentCue]) -> str:
    """The JSON as Seek itself writes it, so the knowledge base never holds text another parser wrote."""
    return json.dumps([asdict(item) for item in items])


def _contents(
    bundle: _Bundle, youtube_video_id: str, dimension: int
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """The Video's Transcript and its Segments in order, each checked to be what the knowledge base stores."""
    transcripts = bundle.rows(
        "SELECT source, language, cues, fetched_at FROM transcripts WHERE youtube_video_id = ?", (youtube_video_id,)
    )
    if len(transcripts) != 1:
        raise bundle.damaged(f"the Video {youtube_video_id} does not have exactly one Transcript")
    (found,) = transcripts
    transcript = f"the Transcript of the Video {youtube_video_id}"
    if found["source"] not in _SOURCES:
        raise bundle.damaged(f"{transcript} does not come from YouTube's captions")
    if found["language"] != _LANGUAGE:
        raise bundle.damaged(f"{transcript} is not in English, and only English is ingested")
    lines = _json(_TRANSCRIPT_CUES, found["cues"])
    if lines is None:
        raise bundle.damaged(f"{transcript} does not give each of its lines a start, an end, and its text")
    if not all(_is_said(line.text) for line in lines):
        raise bundle.damaged(f"{transcript} has a line that is too long or not on one line")
    if any(_NUL in line.text for line in lines):
        raise bundle.damaged(f"{transcript} has a line that holds a NUL character")
    if not _is_timestamp(found["fetched_at"]):
        raise bundle.damaged(f"{transcript} was fetched at a time that is not a timestamp")
    rows = bundle.rows(
        """
        SELECT ordinal, start_seconds, end_seconds, text, chapter_title, context, cues, embedding
        FROM segments WHERE youtube_video_id = ? ORDER BY ordinal
        """,
        (youtube_video_id,),
    )
    if [row["ordinal"] for row in rows] != list(range(len(rows))):
        raise bundle.damaged(f"the Segments of the Video {youtube_video_id} are not numbered in order without gaps")
    # Segments are cut from the Transcript's lines. One with none is what blank captions leave, and has no Segments.
    if rows and not lines:
        raise bundle.damaged(f"{transcript} has no lines, though the Video has Segments")
    segment = f"a Segment of the Video {youtube_video_id}"
    segments = []
    for row in rows:
        text, embedding = row["text"], row["embedding"]
        if not (_is_seconds(row["start_seconds"]) and _is_seconds(row["end_seconds"])):
            raise bundle.damaged(f"{segment} has a start or an end that is not a number of seconds")
        # What was said, the context it is indexed under, and its chapter's title when it has one.
        if not (
            _is_said(text)
            and _is_text(row["context"])
            and (row["chapter_title"] is None or _is_text(row["chapter_title"]))
        ):
            raise bundle.damaged(f"{segment} has text that is too long or not on one line")
        if any(_NUL in value for value in (text, row["context"], row["chapter_title"] or "")):
            raise bundle.damaged(f"{segment} has text that holds a NUL character")
        cues = _json(_SEGMENT_CUES, row["cues"])
        # A Segment has a line at least, and search slices its text at each one's offset.
        if not cues or not all(0 <= cue.offset <= len(text) for cue in cues):
            raise bundle.damaged(f"{segment} does not give each of its lines a start time and an offset")
        if not isinstance(embedding, bytes):
            raise bundle.damaged(f"{segment} has no vector")
        if len(embedding) != dimension * 4:
            raise bundle.damaged(
                f"{segment} has a vector of {len(embedding)} bytes, not the {dimension * 4} that {dimension} "
                "dimensions take"
            )
        if not all(map(math.isfinite, struct.unpack(f"<{dimension}f", embedding))):
            raise bundle.damaged(f"{segment} has a vector with a value that is not a finite number")
        segments.append({**dict(row), "cues": _as_stored(cues)})
    return {**dict(found), "cues": _as_stored(lines)}, segments


def _left_out(
    channel: Channel, rules: ExclusionRules, video: dict[str, object], known: sqlite3.Row | None
) -> str | None:
    """Why the Bundle's Video is not to be filled in, if it is not: `known` is its row here, when it has one.

    A Video not yet known is judged by the rules that need only its own metadata: the minimum length and the
    Channel's date range. One they exclude is not added, and the next Sync discovers it as usual. The Channel's
    Playlist filter and most-recent count need a listing, so that Sync applies them.

    A Video already known is not judged again. One that is excluded stays so: this Seek's own Sync judged it with
    every filter. One a Playlist here includes was never excluded by the Channel's filters, so inclusion still wins.
    """
    if known is None:
        length, published_on = cast(int, video["duration_seconds"]), _iso_date(video["published_on"])
        return exclusion(rules, length, published_on, included=False)
    if known["channel_id"] != channel.id:
        # A Video keeps the Channel it is credited to, and its Transcript there is another creator's to index.
        return "Credited here to another Channel"
    return cast(str | None, known["excluded_reason"])


def _import_video(
    conn: sqlite3.Connection,
    channel_id: int,
    video: dict[str, object],
    transcript: dict[str, object],
    segments: list[dict[str, object]],
) -> None:
    """Within a transaction: the Video becomes done, with the Bundle's Transcript and its Segments as they were cut.

    A Video the knowledge base has, at whatever stage its own Syncs left it, keeps its Channel and takes
    everything else from the Bundle in place of what it had, any failure included. The Transcript is never cut
    again: this Seek's segmenter could give a different number of Segments than the vectors were made for. Each
    vector is filed under the id its Segment is given here, and the triggers keep the lexical index in step.

    The write holds the rule itself, whatever its caller decided: a Video that is done, excluded, or credited to
    a Channel other than the one given is never written over, and raises instead.
    """
    written = conn.execute(
        """
        INSERT INTO videos (channel_id, youtube_video_id, title, duration_seconds, published_on, description,
                            chapters, language, pipeline_stage, discovered_at)
        VALUES (:channel_id, :youtube_video_id, :title, :duration_seconds, :published_on, :description,
                :chapters, :language, 'done', :discovered_at)
        ON CONFLICT (youtube_video_id) DO UPDATE SET
            title = excluded.title, duration_seconds = excluded.duration_seconds,
            published_on = excluded.published_on, description = excluded.description, chapters = excluded.chapters,
            language = excluded.language, pipeline_stage = 'done', failure_stage = NULL, failure_reason = NULL,
            failure_permanent = NULL
        WHERE videos.channel_id = excluded.channel_id AND videos.pipeline_stage != 'done'
          AND videos.excluded_reason IS NULL
        RETURNING id
        """,
        {**video, "channel_id": channel_id, "discovered_at": db.now_iso()},
    ).fetchone()
    if written is None:
        raise RuntimeError(f"The Video {video['youtube_video_id']} is not one an import may fill in")
    (video_id,) = written
    conn.execute(
        """
        INSERT OR REPLACE INTO transcripts (video_id, source, language, cues, fetched_at)
        VALUES (:video_id, :source, :language, :cues, :fetched_at)
        """,
        {**transcript, "video_id": video_id},
    )
    # Whatever Segments a Sync of this Seek's own had cut go, and their vectors with them.
    conn.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
    for segment in segments:
        (segment_id,) = conn.execute(
            """
            INSERT INTO segments (video_id, start_seconds, end_seconds, text, chapter_title, context, cues)
            VALUES (:video_id, :start_seconds, :end_seconds, :text, :chapter_title, :context, :cues)
            RETURNING id
            """,
            {**segment, "video_id": video_id},
        ).fetchone()
        conn.execute(
            "INSERT INTO segment_vectors (segment_id, video_id, embedding) VALUES (?, ?, ?)",
            (segment_id, video_id, segment["embedding"]),
        )
