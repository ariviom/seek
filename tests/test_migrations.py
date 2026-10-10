import json
import sqlite3
from pathlib import Path

import pytest
from harness import running

from seek import db
from seek.app import create_app
from seek.config import Config
from seek.fakes import FakeChatEngine, FakeEmbedder, FakeReranker, FakeTranscriptSource

SCHEMA_8 = 8
SCHEMA_9 = 9
SCHEMA_13 = 13
SCHEMA_14 = 14


def tables(conn: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def user_version(conn: sqlite3.Connection) -> int:
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    return version


def foreign_keys_on(conn: sqlite3.Connection) -> bool:
    enabled: int = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    return enabled == 1


def citation(video_id: int, youtube_video_id: str) -> dict[str, object]:
    return {
        "video_id": video_id,
        "youtube_video_id": youtube_video_id,
        "seconds": 5,
        "video_title": "Sharpening chisels",
        "mentor_name": "Paul Wright",
        "channel_name": "Wood By Wright",
        "url": f"https://www.youtube.com/watch?v={youtube_video_id}&t=5s",
        "published_on": None,
    }


def schema_8_knowledge_base(path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """A knowledge base as Seek left it before the Channel model: a Mentor with two Channels in a Group, a Video
    with its Transcript, Segments, and vectors, a Conversation with a cited answer, and one whose Group is gone."""
    conn = db.connect(path)
    with pytest.MonkeyPatch.context() as pinned:
        pinned.setattr(db, "MIGRATIONS", db.MIGRATIONS[:SCHEMA_8])
        db.migrate(conn)
    db.ensure_embedding_model(conn, "fake-embedder", 4)
    conn.executescript(
        """
        INSERT INTO mentors (id, name) VALUES (7, 'Paul Wright');
        INSERT INTO channels (id, mentor_id, youtube_channel_id, name, indexed, published_after, most_recent)
            VALUES (3, 7, 'UC-wright', 'Wood By Wright', 1, '2024-01-01', 25),
                   (5, 7, 'UC-wright-vlog', 'Wright Vlogs', 0, NULL, NULL);
        INSERT INTO mentor_groups (id, name) VALUES (2, 'Woodworking');
        INSERT INTO mentor_group_members (group_id, mentor_id) VALUES (2, 7);
        INSERT INTO videos (id, channel_id, youtube_video_id, title, pipeline_stage, discovered_at)
            VALUES (11, 3, 'v-wright', 'Sharpening chisels', 'done', '2025-01-01T00:00:00+00:00');
        INSERT INTO transcripts (video_id, source, language, cues, fetched_at)
            VALUES (11, 'youtube_manual', 'en', '[]', '2025-01-01T00:00:00+00:00');
        INSERT INTO segments (id, video_id, start_seconds, end_seconds, text, cues, context)
            VALUES (21, 11, 0, 5, 'Sharpen the chisel', '[]', 'Sharpening chisels');
        INSERT INTO segment_vectors (segment_id, channel_id, embedding) VALUES (21, 3, '[0.1, 0.2, 0.3, 0.4]');
        INSERT INTO syncs (id, channel_id, status, queued_at, stage_counts) VALUES (4, 3, 'done', '2025-01-01', '{}');
        INSERT INTO conversations (id, group_id, group_name, model, claude_session_id, created_at, title)
            VALUES (9, 2, 'Woodworking', 'opus', 'session-1', '2025-02-01T00:00:00+00:00', 'Stones'),
                   (10, NULL, 'Leatherwork', NULL, NULL, '2025-02-02T00:00:00+00:00', NULL);
        INSERT INTO messages (conversation_id, role, content, created_at)
            VALUES (9, 'user', 'How fine a stone?', '2025-02-01T00:00:01+00:00');
        """
    )
    # One Citation to a Video still there, one to a Video removed since.
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, citations, created_at) VALUES (9, 'assistant', ?, ?, ?)",
        ("Fine.", json.dumps([citation(11, "v-wright"), citation(12, "v-gone")]), "2025-02-01T00:00:02+00:00"),
    )
    return conn


def test_migration_9_keeps_channels_groups_and_conversations_and_drops_mentors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = schema_8_knowledge_base(tmp_path / "seek.db", monkeypatch)

    db.migrate(conn)

    assert user_version(conn) == len(db.MIGRATIONS)
    assert foreign_keys_on(conn)
    assert not {"mentors", "mentor_groups", "mentor_group_members"} & tables(conn)
    channels = conn.execute(
        "SELECT id, youtube_channel_id, name, indexed, published_after, most_recent FROM channels ORDER BY id"
    )
    assert [tuple(row) for row in channels] == [
        (3, "UC-wright", "Wood By Wright", 1, "2024-01-01", 25),
        (5, "UC-wright-vlog", "Wright Vlogs", 0, None, None),
    ]
    assert [tuple(row) for row in conn.execute("SELECT id, name FROM groups")] == [(2, "Woodworking")]
    members = conn.execute("SELECT group_id, channel_id FROM group_channels ORDER BY channel_id")
    assert [tuple(row) for row in members] == [(2, 3), (2, 5)]
    conversations = conn.execute(
        "SELECT id, group_id, channel_id, scope_kind, scope_name, model, claude_session_id, title FROM conversations"
    )
    assert [tuple(row) for row in conversations] == [
        (9, 2, None, "group", "Woodworking", "opus", "session-1", "Stones"),
        (10, None, None, "group", "Leatherwork", None, None, None),
    ]
    assert [tuple(row) for row in conn.execute("SELECT id, channel_id FROM videos")] == [(11, 3)]
    assert [tuple(row) for row in conn.execute("SELECT id, channel_id FROM syncs")] == [(4, 3)]
    assert [tuple(row) for row in conn.execute("SELECT segment_id, channel_id FROM segment_vectors")] == [(21, 3)]
    roles = conn.execute("SELECT role FROM messages WHERE conversation_id = 9 ORDER BY id")
    assert [row["role"] for row in roles] == ["user", "assistant"]
    conn.close()


def test_migration_9_names_each_citations_channel_by_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = schema_8_knowledge_base(tmp_path / "seek.db", monkeypatch)

    db.migrate(conn)

    kept, gone = json.loads(conn.execute("SELECT citations FROM messages WHERE role = 'assistant'").fetchone()[0])
    assert "mentor_name" not in kept and "mentor_name" not in gone
    assert (kept["channel_id"], kept["channel_name"]) == (3, "Wood By Wright")
    # A Video removed before the migration has no Channel to name.
    assert (gone["channel_id"], gone["youtube_video_id"]) == (None, "v-gone")
    conn.close()


def test_after_migration_9_deleting_a_channel_still_cascades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = schema_8_knowledge_base(tmp_path / "seek.db", monkeypatch)
    db.migrate(conn)

    conn.execute("DELETE FROM channels WHERE id = 3")

    # The tables that stayed reference the rebuilt channels table, and the Segment trigger still fires.
    assert conn.execute("SELECT count(*) FROM videos").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM syncs").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM segment_vectors").fetchone()[0] == 0
    assert [tuple(row) for row in conn.execute("SELECT group_id, channel_id FROM group_channels")] == [(2, 5)]
    conn.close()


def test_migration_9_frees_channel_ids_from_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = schema_8_knowledge_base(tmp_path / "seek.db", monkeypatch)

    db.migrate(conn)
    conn.execute("DELETE FROM channels WHERE id = 5")
    (new_id,) = conn.execute(
        "INSERT INTO channels (youtube_channel_id, name) VALUES ('UC-new', 'New') RETURNING id"
    ).fetchone()

    assert new_id > 5
    conn.close()


def test_migration_10_counts_no_completed_videos_for_the_syncs_already_recorded(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seek.db")
    with pytest.MonkeyPatch.context() as pinned:
        pinned.setattr(db, "MIGRATIONS", db.MIGRATIONS[:SCHEMA_9])
        db.migrate(conn)
    conn.executescript(
        """
        INSERT INTO channels (id, youtube_channel_id, name) VALUES (3, 'UC-wright', 'Wood By Wright');
        INSERT INTO syncs (id, channel_id, status, queued_at, stage_counts) VALUES (4, 3, 'done', '2025-01-01', '{}');
        """
    )

    db.migrate(conn)

    assert user_version(conn) == len(db.MIGRATIONS)
    assert [tuple(row) for row in conn.execute("SELECT id, completed_videos FROM syncs")] == [(4, 0)]
    conn.close()


def test_migration_14_credits_no_video_to_the_syncs_already_recorded(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seek.db")
    with pytest.MonkeyPatch.context() as pinned:
        pinned.setattr(db, "MIGRATIONS", db.MIGRATIONS[:SCHEMA_13])
        db.migrate(conn)
    conn.executescript(
        """
        INSERT INTO channels (id, youtube_channel_id, name) VALUES (3, 'UC-wright', 'Wood By Wright');
        INSERT INTO videos (id, channel_id, youtube_video_id, title, pipeline_stage, discovered_at)
            VALUES (11, 3, 'v-wright', 'Sharpening chisels', 'done', '2025-01-01T00:00:00+00:00');
        INSERT INTO syncs (id, channel_id, status, queued_at, stage_counts, completed_videos)
            VALUES (4, 3, 'done', '2025-01-01', '{}', 1);
        """
    )

    db.migrate(conn)

    assert user_version(conn) == len(db.MIGRATIONS)
    # A finished Sync keeps the count it recorded; no Video is credited to it, since none was recorded then.
    assert [tuple(row) for row in conn.execute(
        "SELECT id, completed_videos, failed_videos, remaining_videos, counted_from FROM syncs"
    )] == [(4, 1, 0, 0, 0)]
    assert [tuple(row) for row in conn.execute("SELECT id, completed_by_sync_id FROM videos")] == [(11, None)]
    conn.close()


def test_migrations_15_and_16_add_storyboards_and_let_frames_be_turned_off(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seek.db")
    with pytest.MonkeyPatch.context() as pinned:
        pinned.setattr(db, "MIGRATIONS", db.MIGRATIONS[:SCHEMA_14])
        db.migrate(conn)
    conn.executescript(
        """
        INSERT INTO channels (id, youtube_channel_id, name) VALUES (3, 'UC-wright', 'Wood By Wright');
        INSERT INTO videos (id, channel_id, youtube_video_id, title, pipeline_stage, discovered_at)
            VALUES (11, 3, 'v-wright', 'Sharpening chisels', 'done', '2025-01-01T00:00:00+00:00');
        INSERT INTO settings (key, value) VALUES ('engine', 'api'), ('model', 'deep');
        """
    )

    db.migrate(conn)

    assert user_version(conn) == len(db.MIGRATIONS)
    assert foreign_keys_on(conn)
    # No row for the Video ingested before frames were kept: it has no storyboard, honestly.
    assert conn.execute("SELECT count(*) FROM storyboards").fetchone()[0] == 0
    # The preferences already saved survive the settings rebuild, and the new one is allowed beside them.
    assert sorted(tuple(row) for row in conn.execute("SELECT key, value FROM settings")) == [
        ("engine", "api"), ("model", "deep")
    ]
    conn.execute("INSERT INTO settings (key, value) VALUES ('thumbnails', 'off')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO settings (key, value) VALUES ('thumbnails_elsewhere', 'off')")
    # A storyboard belongs to its Video and goes when it does.
    conn.execute(
        """
        INSERT INTO storyboards (video_id, columns, rows, width, height, fps, url_template, fragment_count, fetched_at)
        VALUES (11, 3, 3, 320, 180, 0.1, 'https://i.ytimg.com/sb/v/M{index}.jpg?sqp=s', 4, '2026-10-02T00:00:00+00:00')
        """
    )
    conn.execute("DELETE FROM videos WHERE id = 11")
    assert conn.execute("SELECT count(*) FROM storyboards").fetchone()[0] == 0
    conn.close()


def test_a_fresh_knowledge_base_runs_every_migration(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "seek.db")

    db.migrate(conn)

    assert user_version(conn) == len(db.MIGRATIONS)
    assert {"channels", "groups", "group_channels", "conversations", "messages", "videos", "syncs"} <= tables(conn)
    assert "mentors" not in tables(conn)
    assert foreign_keys_on(conn)
    conn.close()


def test_a_rebuild_that_leaves_orphans_is_rolled_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = db.connect(tmp_path / "seek.db")
    db.migrate(conn)

    def orphan(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO groups (id, name) VALUES (1, 'G')")
        conn.execute("INSERT INTO group_channels (group_id, channel_id) VALUES (1, 999)")

    monkeypatch.setattr(db, "MIGRATIONS", [*db.MIGRATIONS, orphan])

    with pytest.raises(RuntimeError, match="missing"):
        db.migrate(conn)

    assert user_version(conn) == len(db.MIGRATIONS) - 1
    assert conn.execute("SELECT count(*) FROM groups").fetchone()[0] == 0
    assert foreign_keys_on(conn)
    conn.close()


async def test_server_refuses_a_knowledge_base_from_a_newer_seek(config: Config, tmp_path: Path) -> None:
    config.data_dir.mkdir(parents=True)
    conn = sqlite3.connect(config.database_path)
    conn.execute("PRAGMA user_version = 999")
    conn.close()
    app = create_app(
        config, FakeTranscriptSource(), FakeEmbedder(), FakeReranker(), FakeChatEngine(), static_dir=tmp_path / "no-bundle"
    )

    with pytest.raises(RuntimeError, match="newer"):
        async with running(app):
            pass
