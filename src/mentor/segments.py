"""Segments and their vectors as Syncs advance Videos. Functions are blocking; run them through Database.run."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict

import sqlite_vec

from mentor.db import transaction
from mentor.ports import Chapter, Cue
from mentor.segmentation import segment


def record_segments(conn: sqlite3.Connection, video_id: int) -> bool:
    """Cuts the Video's Transcript into Segments, replacing any it had, and advances the stage.

    Replacing a Segment also removes its FTS5 row and its vector. False if the Video is gone.
    """
    with transaction(conn):
        row = conn.execute(
            "SELECT videos.chapters, transcripts.cues FROM videos JOIN transcripts ON transcripts.video_id = videos.id"
            " WHERE videos.id = ?",
            (video_id,),
        ).fetchone()
        if row is None:
            return False
        cues = [Cue(**c) for c in json.loads(row["cues"])]
        chapters = [Chapter(**c) for c in json.loads(row["chapters"] or "[]")]
        conn.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
        conn.executemany(
            """
            INSERT INTO segments (video_id, start_seconds, end_seconds, text, chapter_title, cues)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (video_id, s.start, s.end, s.text, s.chapter_title, json.dumps([asdict(c) for c in s.cues]))
                for s in segment(cues, chapters)
            ],
        )
        conn.execute("UPDATE videos SET pipeline_stage = 'segmented' WHERE id = ?", (video_id,))
        return True


def segment_texts(conn: sqlite3.Connection, video_id: int) -> list[tuple[int, str]]:
    """The Video's Segments as (id, text), in time order."""
    rows = conn.execute("SELECT id, text FROM segments WHERE video_id = ? ORDER BY start_seconds, id", (video_id,))
    return [(row["id"], row["text"]) for row in rows]


def record_embeddings(
    conn: sqlite3.Connection, video_id: int, vectors: Sequence[tuple[int, Sequence[float]]]
) -> bool:
    """Stores vectors for the Video's Segments, replacing any they had, and advances the stage.

    False if the Video is gone. A vector whose Segment has gone is not stored.
    """
    with transaction(conn):
        row = conn.execute("SELECT channel_id FROM videos WHERE id = ?", (video_id,)).fetchone()
        if row is None:
            return False
        # One delete per id: vec0 looks rows up by primary key, but would scan every vector for a subquery.
        conn.executemany(
            "DELETE FROM segment_vectors WHERE segment_id = ?",
            conn.execute("SELECT id FROM segments WHERE video_id = ?", (video_id,)).fetchall(),
        )
        conn.executemany(
            """
            INSERT INTO segment_vectors (segment_id, channel_id, embedding)
            SELECT id, ?, ? FROM segments WHERE id = ? AND video_id = ?
            """,
            [
                (row["channel_id"], sqlite_vec.serialize_float32(list(vector)), segment_id, video_id)
                for segment_id, vector in vectors
            ],
        )
        conn.execute("UPDATE videos SET pipeline_stage = 'embedded' WHERE id = ?", (video_id,))
        return True
