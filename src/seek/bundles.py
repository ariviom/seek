"""`seek export` and `seek import`: one Channel's indexed Videos as a Bundle, a `.seek` file another Seek imports.

A Bundle is a single SQLite database in plain tables, so any SQLite reads it without extensions. Nothing in it is
keyed by a local id: Videos go by their YouTube ids and Segments by their order within the Video. Both commands run
in this process against the knowledge base, never through the server.
"""

import importlib.metadata
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from seek import channels, db
from seek.channels import ChannelFilters
from seek.config import Config
from seek.ports import ChannelInfo
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
    Transcripts written through it.
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
        # A rollback journal, never WAL: once committed, a Bundle is exactly one file.
        bundle.execute("PRAGMA journal_mode = DELETE")
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

    A Bundle is refused whole, before anything is written, when this build can't read it, when it was embedded
    with another model, or when the knowledge base already has its Channel or any of its Videos. Each Video is
    then committed on its own, so a running server's writes wait for one Video at most.
    """
    with _open_bundle(path) as bundle:
        meta = _meta(bundle, path)
        model, dimension = config.embedding_model, config.embedding_dimension
        if (meta["embedding_model"], meta["embedding_dimension"]) != (model, dimension):
            # Vectors from two models can't be compared, and a Bundle carries no way to embed its text again.
            raise SyncCommandError(
                f"{path} was embedded with {meta['embedding_model']} ({meta['embedding_dimension']} dimensions), "
                f"but this knowledge base uses {model} ({dimension} dimensions); a Bundle imports only into a "
                "knowledge base that uses the same embedding model"
            )
        entry = bundle.execute(
            "SELECT youtube_channel_id, name, avatar_url, published_after, published_before, most_recent FROM channel"
        ).fetchone()
        videos = bundle.execute(
            """
            SELECT youtube_video_id, title, duration_seconds, published_on, description, chapters, language
            FROM videos ORDER BY rowid
            """
        ).fetchall()
        _open_knowledge_base(config)
        with closing(db.connect(config.database_path)) as conn:
            if _known(conn, entry["youtube_channel_id"], [video["youtube_video_id"] for video in videos]):
                raise SyncCommandError(
                    f"This knowledge base already has the Channel {entry['name']!r} ({entry['youtube_channel_id']}) "
                    "or some of its Videos, in the Library or through a Playlist; importing into what it already "
                    "has is not supported yet"
                )
            filters = ChannelFilters(
                published_after=entry["published_after"] and date.fromisoformat(entry["published_after"]),
                published_before=entry["published_before"] and date.fromisoformat(entry["published_before"]),
                most_recent=entry["most_recent"],
            )
            info = ChannelInfo(entry["youtube_channel_id"], entry["name"], entry["avatar_url"])
            channel = channels.create_channel(conn, info, filters=filters)
            for video in videos:
                with db.transaction(conn):
                    _import_video(conn, bundle, channel.id, video)
    return ImportReport(channel.name, channel.youtube_channel_id, len(videos))


def format_import(report: ImportReport) -> str:
    return "\n".join(
        [
            f"Imported {report.channel_name}: {report.added} Videos added, searchable now.",
            "Next, start a Sync to pick up the Videos published since: "
            f"seek sync --channel {report.youtube_channel_id}",
        ]
    )


@contextmanager
def _open_bundle(path: Path) -> Iterator[sqlite3.Connection]:
    """The file as untrusted input: read-only, on a connection of its own that loads no extension and is never
    attached to the knowledge base's, with the SQL its schema embeds untrusted."""
    try:
        bundle = sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True, autocommit=True)
    except sqlite3.Error as e:
        raise _not_a_bundle(path) from e
    with closing(bundle):
        bundle.row_factory = sqlite3.Row
        bundle.execute("PRAGMA trusted_schema = OFF")
        yield bundle


def _not_a_bundle(path: Path) -> SyncCommandError:
    return SyncCommandError(f"{path} is not a Seek Bundle")


def _meta(bundle: sqlite3.Connection, path: Path) -> sqlite3.Row:
    """The Bundle's one meta record, once the file is known to be a Bundle this build reads."""
    try:
        (application_id,) = bundle.execute("PRAGMA application_id").fetchone()
        if application_id != APPLICATION_ID:
            raise _not_a_bundle(path)
        records: list[sqlite3.Row] = bundle.execute(
            "SELECT format_version, embedding_model, embedding_dimension FROM meta"
        ).fetchall()
    except sqlite3.Error as e:
        # Not a database at all, or one without the table.
        raise _not_a_bundle(path) from e
    if len(records) != 1:
        raise _not_a_bundle(path)
    version = records[0]["format_version"]
    if isinstance(version, int) and version > FORMAT_VERSION:
        raise SyncCommandError(
            f"{path} was made by a newer Seek (Bundle format {version}, this build reads {FORMAT_VERSION}); "
            "upgrade Seek"
        )
    if version != FORMAT_VERSION:
        raise _not_a_bundle(path)
    return records[0]


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


def _import_video(conn: sqlite3.Connection, bundle: sqlite3.Connection, channel_id: int, video: sqlite3.Row) -> None:
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
        {**dict(video), "channel_id": channel_id, "discovered_at": db.now_iso()},
    ).fetchone()
    transcript = bundle.execute(
        "SELECT source, language, cues, fetched_at FROM transcripts WHERE youtube_video_id = ?",
        (video["youtube_video_id"],),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO transcripts (video_id, source, language, cues, fetched_at)
        VALUES (:video_id, :source, :language, :cues, :fetched_at)
        """,
        {**dict(transcript), "video_id": video_id},
    )
    segments = bundle.execute(
        """
        SELECT start_seconds, end_seconds, text, chapter_title, context, cues, embedding
        FROM segments WHERE youtube_video_id = ? ORDER BY ordinal
        """,
        (video["youtube_video_id"],),
    )
    for segment in segments:
        (segment_id,) = conn.execute(
            """
            INSERT INTO segments (video_id, start_seconds, end_seconds, text, chapter_title, context, cues)
            VALUES (:video_id, :start_seconds, :end_seconds, :text, :chapter_title, :context, :cues)
            RETURNING id
            """,
            {**dict(segment), "video_id": video_id},
        ).fetchone()
        conn.execute(
            "INSERT INTO segment_vectors (segment_id, video_id, embedding) VALUES (?, ?, ?)",
            (segment_id, video_id, segment["embedding"]),
        )
