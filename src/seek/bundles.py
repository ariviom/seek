"""`seek export` and `seek import`: one Channel's indexed Videos as a Bundle, a `.seek` file another Seek imports.

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
import unicodedata
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from pydantic import ConfigDict, TypeAdapter, ValidationError

from seek import channels, db
from seek.channels import ChannelFilters
from seek.channels_api import FiltersBody
from seek.config import Config
from seek.ports import Chapter, ChannelInfo, Cue
from seek.segmentation import SegmentCue
from seek.sync_command import SyncCommandError, find_channel

# The ASCII bytes of "SEEK", kept in the SQLite header: how import tells a Bundle from any other SQLite file.
APPLICATION_ID = 0x5345454B
FORMAT_VERSION = 1
EXTENSION = ".seek"

# Vectors are the knowledge base's own bytes: little-endian float32, four per dimension.
_SCHEMA = """
    CREATE TABLE meta (
        format_version INTEGER NOT NULL,
        seek_version TEXT NOT NULL,
        embedding_model TEXT NOT NULL,
        embedding_dimension INTEGER NOT NULL,
        kind TEXT NOT NULL,
        exported_at TEXT NOT NULL
    );
    CREATE TABLE channel (
        youtube_channel_id TEXT NOT NULL,
        name TEXT NOT NULL,
        avatar_url TEXT,
        published_after TEXT,
        published_before TEXT,
        most_recent INTEGER
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


# The tables import reads.
_TABLES = {"meta", "channel", "videos", "transcripts", "segments"}
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
# Bidi embeddings, overrides, and isolates, which reorder the line a name is printed on. Other format characters
# stay: YouTube's names join emoji with one.
_REORDERING = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
# Where YouTube serves a channel's avatar from. The whole prefix is matched, so nothing later in the URL can name
# another server.
_AVATAR_HOSTS = ("https://yt3.ggpht.com/", "https://yt3.googleusercontent.com/")
# What a Sync accepts of a Transcript: YouTube's captions, in English.
_SOURCES = ("youtube_auto", "youtube_manual")
_LANGUAGE = "en"

# The JSON columns read strictly, as the shapes Seek stores: a key too many, or a number written as text, would
# break every search and listing that reads the row.
_AS_STORED = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
_CHAPTERS = TypeAdapter(list[Chapter], config=_AS_STORED)
_TRANSCRIPT_CUES = TypeAdapter(list[Cue], config=_AS_STORED)
_SEGMENT_CUES = TypeAdapter(list[SegmentCue], config=_AS_STORED)


@dataclass(frozen=True)
class ExportReport:
    # Where the Bundle was written.
    path: Path
    channel_name: str
    videos: int
    segments: int
    size_bytes: int
    # The Channel has a Playlist filter, which a Bundle never carries.
    playlist_filter_left_out: bool


@dataclass(frozen=True)
class ImportReport:
    channel_name: str
    youtube_channel_id: str
    # Videos that became searchable from the Bundle.
    added: int


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


def export_channel(config: Config, channel: str, path: Path) -> ExportReport:
    """Writes the Channel with this name or YouTube channel id to a Bundle at the path, adding `.seek` when the
    path lacks it.

    The Bundle holds the Channel's searchable Videos, Paused or not. It is read in one read transaction, so it is
    a consistent snapshot even while a Sync writes; no Sync lease is taken and no model is loaded.
    """
    if path.is_dir():
        raise SyncCommandError(f"{path} is a directory; give the file to write the Bundle to")
    destination = path if path.name.endswith(EXTENSION) else path.with_name(path.name + EXTENSION)
    _refuse_existing(destination)
    _open_knowledge_base(config)
    with closing(db.connect(config.database_path)) as conn:
        # Left open until the connection closes: every read below sees the knowledge base as it is now.
        conn.execute("BEGIN")
        found = find_channel(channels.list_channels(conn), channel)
        videos = conn.execute(
            """
            SELECT id, youtube_video_id, title, duration_seconds, published_on, description, chapters, language
            FROM videos WHERE channel_id = ? AND pipeline_stage = 'done' AND excluded_reason IS NULL ORDER BY id
            """,
            (found.id,),
        ).fetchall()
        if not videos:
            raise SyncCommandError(f"The Channel {found.name!r} has no indexed Videos to export")
        model = conn.execute("SELECT name, dimension FROM embedding_model").fetchone()
        # Written under another name and renamed once complete, so a `.seek` file is never half a Bundle.
        temporary, bundle = _new_bundle(destination)
        try:
            with closing(bundle):
                bundle.execute(
                    """
                    INSERT INTO meta (format_version, seek_version, embedding_model, embedding_dimension, kind,
                                      exported_at)
                    VALUES (?, ?, ?, ?, 'channel', ?)
                    """,
                    (FORMAT_VERSION, _seek_version(), model["name"], model["dimension"], db.now_iso()),
                )
                # The Playlist filter stays behind: it names a YouTube playlist every Sync of the recipient's would
                # have to list, and one they can't see would fail each of them.
                bundle.execute(
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
                segments = sum(_export_video(conn, bundle, found.youtube_channel_id, video) for video in videos)
                bundle.execute("COMMIT")
            # Again, since the write can take minutes and a rename replaces what is there without a word.
            _refuse_existing(destination)
            temporary.rename(destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    return ExportReport(
        destination,
        found.name,
        len(videos),
        segments,
        destination.stat().st_size,
        found.filters.playlist_id is not None,
    )


def _refuse_existing(destination: Path) -> None:
    if destination.exists():
        raise SyncCommandError(f"{destination} already exists; export never replaces a file")


def _new_bundle(destination: Path) -> tuple[Path, sqlite3.Connection]:
    """An empty Bundle under a temporary name beside the destination, inside a transaction for the caller to
    commit; returns that name with it.

    The file is created here, exclusively and under a name nobody can guess, and is readable by its owner alone:
    in a directory others can write to, a link planted where the Bundle was about to go would otherwise have the
    Transcripts written through it. SQLite opens it again by name, so a directory where another user can rename
    files (one that is writable by them and not sticky) is still no place to export to.
    """
    try:
        handle, name = tempfile.mkstemp(dir=destination.parent, prefix=f"{destination.name}.", suffix=".tmp")
        os.close(handle)
    except OSError as e:
        raise SyncCommandError(f"Could not write {destination}: {e}") from e
    temporary = Path(name)
    try:
        bundle = sqlite3.connect(temporary, autocommit=True)
        bundle.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        # No journal while writing: a failed export deletes the file anyway, and a journal would be a second file
        # at a name derived from this one. The mode is not stored, so the Bundle opens with a rollback journal,
        # never WAL, and is always exactly one file.
        bundle.execute("PRAGMA journal_mode = OFF")
        bundle.execute("BEGIN")
        bundle.executescript(_SCHEMA)
    except sqlite3.Error as e:
        temporary.unlink(missing_ok=True)
        raise SyncCommandError(f"Could not write {destination}: {e}") from e
    return temporary, bundle


def format_export(report: ExportReport) -> str:
    megabytes = report.size_bytes / 1_000_000
    size = f"{megabytes:.1f} MB" if megabytes >= 1 else f"{max(1, report.size_bytes // 1000)} KB"
    counts = f"{report.videos} Videos, {report.segments} Segments, {size}"
    lines = [
        f"Exported {report.channel_name} to {report.path}: {counts}.",
        "The file contains the creators' full Transcripts, so choose who you share it with.",
    ]
    if report.playlist_filter_left_out:
        lines.append(
            "The Channel's Playlist filter was left out, so the recipient's Syncs will bring in its other Videos."
        )
    return "\n".join(lines)


def _export_video(
    conn: sqlite3.Connection, bundle: sqlite3.Connection, youtube_channel_id: str, video: sqlite3.Row
) -> int:
    """Copies one Video, its Transcript, and its Segments with their vectors; returns how many Segments."""
    key = {"youtube_video_id": video["youtube_video_id"]}
    bundle.execute(
        """
        INSERT INTO videos (youtube_video_id, youtube_channel_id, title, duration_seconds, published_on,
                            description, chapters, language)
        VALUES (:youtube_video_id, :youtube_channel_id, :title, :duration_seconds, :published_on,
                :description, :chapters, :language)
        """,
        {**dict(video), "youtube_channel_id": youtube_channel_id},
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


def import_bundle(config: Config, path: Path) -> ImportReport:
    """Adds the Bundle's Channel to the Library, Active and checked daily, with its Videos searchable at once:
    nothing is fetched from YouTube and nothing embedded. Creates the knowledge base if there is none yet.

    A Bundle is untrusted input. It is refused whole, before anything is written, when this build can't read it,
    when it was embedded with another model, when anything in it is not what a Sync would have stored, or when the
    knowledge base already has its Channel or any of its Videos. Each Video is then committed on its own, so a
    running server's writes wait for one Video at most.
    """
    with _open_bundle(path) as bundle:
        meta = _meta(bundle)
        model, dimension = config.embedding_model, config.embedding_dimension
        if (meta["embedding_model"], meta["embedding_dimension"]) != (model, dimension):
            # Vectors from two models can't be compared, and a Bundle carries no way to embed its text again.
            raise SyncCommandError(
                f"{path} was embedded with {meta['embedding_model']} ({meta['embedding_dimension']} dimensions), "
                f"but this knowledge base uses {model} ({dimension} dimensions); a Bundle imports only into a "
                "knowledge base that uses the same embedding model"
            )
        info, filters = _channel(bundle)
        videos = _videos(bundle, info.channel_id)
        # Every Video is read before the first write: a refusal partway would leave the Library half-changed.
        for youtube_video_id in videos:
            _contents(bundle, youtube_video_id, dimension)
        _open_knowledge_base(config)
        with closing(db.connect(config.database_path)) as conn:
            if _known(conn, info.channel_id, list(videos)):
                raise SyncCommandError(
                    f"This knowledge base already has the Channel {info.name!r} ({info.channel_id}) "
                    "or some of its Videos, in the Library or through a Playlist; importing into what it already "
                    "has is not supported yet"
                )
            channel = channels.create_channel(conn, info, filters=filters)
            for youtube_video_id, video in videos.items():
                # Read again rather than kept since the check: a Channel's vectors run to a hundred megabytes.
                transcript, segments = _contents(bundle, youtube_video_id, dimension)
                with db.transaction(conn):
                    _import_video(conn, channel.id, video, transcript, segments)
    return ImportReport(channel.name, channel.youtube_channel_id, len(videos))


def format_import(report: ImportReport) -> str:
    return "\n".join(
        [
            f"Imported {report.channel_name}: {report.added} Videos added, searchable now.",
            "The Bundle's text came from whoever made the file, and is only as trustworthy as they are.",
            "Next, start a Sync to pick up the Videos published since: "
            f"seek sync --channel {report.youtube_channel_id}",
        ]
    )


@dataclass(frozen=True)
class _Bundle:
    """A Bundle being read. It is untrusted input, so every read goes through `rows` and every refusal names the
    file."""

    path: Path
    conn: sqlite3.Connection

    def rows(self, sql: str, parameters: Sequence[object] = ()) -> list[sqlite3.Row]:
        try:
            return self.conn.execute(sql, parameters).fetchall()
        except sqlite3.Error as e:
            # Not a database at all, one without the table, or a virtual table this connection can't open.
            raise self.not_a_bundle() from e

    def not_a_bundle(self) -> SyncCommandError:
        return SyncCommandError(f"{self.path} is not a Seek Bundle")

    def damaged(self, what: str) -> SyncCommandError:
        return SyncCommandError(f"{self.path} is damaged or has been altered: {what}")


@contextmanager
def _open_bundle(path: Path) -> Iterator[_Bundle]:
    """The file as untrusted input: read-only, on a connection of its own that loads no extension and is never
    attached to the knowledge base's, with the SQL its schema embeds untrusted."""
    try:
        conn = sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True, autocommit=True)
    except sqlite3.Error as e:
        raise SyncCommandError(f"{path} is not a Seek Bundle") from e
    with closing(conn):
        conn.row_factory = sqlite3.Row
        bundle = _Bundle(path, conn)
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
            f"{bundle.path} was made by a newer Seek (Bundle format {version}, this build reads {FORMAT_VERSION}); "
            "upgrade Seek"
        )
    if version != FORMAT_VERSION or not _TABLES <= plain:
        raise bundle.not_a_bundle()
    (meta,) = bundle.rows("SELECT embedding_model, embedding_dimension, kind FROM meta")
    # The model's name and dimension are quoted in a refusal, so they must be fit to print.
    described = _is_name(meta["embedding_model"]) and type(meta["embedding_dimension"]) is int
    if meta["kind"] != "channel" or not described:
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
    return isinstance(value, str) and _is_text(value) and _LINE_BREAKS.search(value) is None


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
    try:
        return isinstance(value, str) and datetime.fromisoformat(value) is not None
    except ValueError:
        return False


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
    avatar = entry["avatar_url"]
    # Any other avatar is dropped: the Library page would load it from whatever server the Bundle's maker chose.
    # The Channel shows initials until a Sync's listing supplies one.
    kept = avatar if isinstance(avatar, str) and avatar.startswith(_AVATAR_HOSTS) else None
    return ChannelInfo(entry["youtube_channel_id"], entry["name"], kept), ChannelFilters(**body.model_dump())


def _videos(bundle: _Bundle, youtube_channel_id: str) -> dict[str, dict[str, object]]:
    """The Bundle's Videos by YouTube id, in the order they were written, each checked to be what the knowledge
    base stores for a Video that is done."""
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
        if row["youtube_channel_id"] != youtube_channel_id:
            raise bundle.damaged(f"{video} is credited to a creator other than the Bundle's Channel")
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
        if row["language"] != _LANGUAGE:
            raise bundle.damaged(f"{video} is not in English, and only English is ingested")
        videos[youtube_video_id] = {**dict(row), "chapters": _as_stored(chapters)}
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
    segment = f"a Segment of the Video {youtube_video_id}"
    segments = []
    for row in rows:
        text, embedding = row["text"], row["embedding"]
        if not (_is_seconds(row["start_seconds"]) and _is_seconds(row["end_seconds"])):
            raise bundle.damaged(f"{segment} has a start or an end that is not a number of seconds")
        # What was said, the context it is indexed under, and its chapter's title when it has one.
        if not (
            isinstance(text, str)
            and _is_said(text)
            and _is_text(row["context"])
            and (row["chapter_title"] is None or _is_text(row["chapter_title"]))
        ):
            raise bundle.damaged(f"{segment} has text that is too long or not on one line")
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


def _known(conn: sqlite3.Connection, youtube_channel_id: str, youtube_video_ids: list[str]) -> bool:
    """Whether the knowledge base has the Channel, in the Library or outside it, or any of the Videos, whichever
    Channel they are credited to here."""
    if youtube_channel_id in channels.youtube_channel_ids(conn):
        return True
    found = conn.execute(
        "SELECT 1 FROM videos WHERE youtube_video_id IN (SELECT value FROM json_each(?)) LIMIT 1",
        (json.dumps(youtube_video_ids),),
    )
    return found.fetchone() is not None


def _import_video(
    conn: sqlite3.Connection,
    channel_id: int,
    video: dict[str, object],
    transcript: dict[str, object],
    segments: list[dict[str, object]],
) -> None:
    """Within a transaction: the Video arrives done, with the Bundle's Transcript and its Segments as they were cut.

    The Transcript is never cut again: this Seek's segmenter could give a different number of Segments than the
    vectors were made for. Each vector is filed under the id its Segment is given here, and the triggers keep the
    lexical index in step.
    """
    (video_id,) = conn.execute(
        """
        INSERT INTO videos (channel_id, youtube_video_id, title, duration_seconds, published_on, description,
                            chapters, language, pipeline_stage, discovered_at)
        VALUES (:channel_id, :youtube_video_id, :title, :duration_seconds, :published_on, :description,
                :chapters, :language, 'done', :discovered_at)
        RETURNING id
        """,
        {**video, "channel_id": channel_id, "discovered_at": db.now_iso()},
    ).fetchone()
    conn.execute(
        """
        INSERT INTO transcripts (video_id, source, language, cues, fetched_at)
        VALUES (:video_id, :source, :language, :cues, :fetched_at)
        """,
        {**transcript, "video_id": video_id},
    )
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
