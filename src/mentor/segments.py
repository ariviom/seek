"""Segments and their vectors as Syncs advance Videos. Functions are blocking; run them through Database.run."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict

import sqlite_vec

from mentor import videos
from mentor.db import transaction
from mentor.ports import Chapter, Cue
from mentor.segmentation import segment


def record_segments(conn: sqlite3.Connection, video_id: int) -> bool:
    """Cuts the Video's Transcript into Segments, replacing any it had, and advances the stage.

    Replacing a Segment also removes its FTS5 row and its vector. False if the Video is gone.
    """
    with transaction(conn):
        video = conn.execute("SELECT chapters FROM videos WHERE id = ?", (video_id,)).fetchone()
        if video is None:
            return False
        transcript = conn.execute("SELECT cues FROM transcripts WHERE video_id = ?", (video_id,)).fetchone()
        if transcript is None:
            raise RuntimeError("The Video has no Transcript to segment")
        cues = [Cue(**c) for c in json.loads(transcript["cues"])]
        chapters = [Chapter(**c) for c in json.loads(video["chapters"] or "[]")]
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
        return videos.complete_stage(conn, video_id, "segmented")


def segment_texts(conn: sqlite3.Connection, video_id: int) -> list[tuple[int, str]]:
    """The Video's Segments as (id, text)."""
    rows = conn.execute("SELECT id, text FROM segments WHERE video_id = ? ORDER BY id", (video_id,))
    return [(row["id"], row["text"]) for row in rows]


def record_embeddings(
    conn: sqlite3.Connection, video_id: int, vectors: Sequence[tuple[int, Sequence[float]]]
) -> bool:
    """Stores a vector for each of the Video's Segments, replacing any they had, and advances the stage.

    False if the Video is gone. Raises if the vectors aren't for exactly the Video's current Segments.
    """
    with transaction(conn):
        row = conn.execute("SELECT channel_id FROM videos WHERE id = ?", (video_id,)).fetchone()
        if row is None:
            return False
        segment_ids = [r["id"] for r in conn.execute("SELECT id FROM segments WHERE video_id = ?", (video_id,))]
        if sorted(segment_id for segment_id, _ in vectors) != sorted(segment_ids):
            raise RuntimeError("The Video's Segments changed while it was being embedded")
        # One delete per id: vec0 looks rows up by primary key, but would scan every vector for a subquery.
        conn.executemany("DELETE FROM segment_vectors WHERE segment_id = ?", [(i,) for i in segment_ids])
        conn.executemany(
            "INSERT INTO segment_vectors (segment_id, channel_id, embedding) VALUES (?, ?, ?)",
            [
                (segment_id, row["channel_id"], sqlite_vec.serialize_float32(list(vector)))
                for segment_id, vector in vectors
            ],
        )
        return videos.complete_stage(conn, video_id, "embedded")
