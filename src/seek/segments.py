"""Segments and their vectors as Syncs advance Videos. Functions are blocking; run them through Database.run."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict

import sqlite_vec

from seek import videos
from seek.db import transaction
from seek.ports import Chapter, Cue
from seek.segmentation import segment
from seek.videos import StageOutcome


def passage_context(video_title: str, chapter_title: str | None) -> str:
    """What frames a Segment for the indexes: its Video's title and, when it has one, its chapter."""
    return video_title if chapter_title is None else f"{video_title} — {chapter_title}"


def passage_text(context: str, text: str) -> str:
    """The text a Segment is embedded and reranked as: its context, then the bare cue text."""
    return f"{context}\n{text}"


def record_segments(conn: sqlite3.Connection, video_id: int) -> StageOutcome:
    """Cuts the Video's Transcript into Segments, replacing any it had, and advances the stage.

    Replacing a Segment also removes its FTS5 row and its vector. Nothing is written for a Video that is gone or
    has been excluded meanwhile.
    """
    with transaction(conn):
        if (outcome := videos.standing(conn, video_id)) != "advanced":
            return outcome
        video = conn.execute("SELECT title, chapters FROM videos WHERE id = ?", (video_id,)).fetchone()
        transcript = conn.execute("SELECT cues FROM transcripts WHERE video_id = ?", (video_id,)).fetchone()
        if transcript is None:
            raise RuntimeError("The Video has no Transcript to segment")
        cues = [Cue(**c) for c in json.loads(transcript["cues"])]
        chapters = [Chapter(**c) for c in json.loads(video["chapters"] or "[]")]
        conn.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
        conn.executemany(
            """
            INSERT INTO segments (video_id, start_seconds, end_seconds, text, chapter_title, context, cues)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    video_id,
                    s.start,
                    s.end,
                    s.text,
                    s.chapter_title,
                    passage_context(video["title"], s.chapter_title),
                    json.dumps([asdict(c) for c in s.cues]),
                )
                for s in segment(cues, chapters)
            ],
        )
        videos.complete_stage(conn, video_id, "segmented")
        return outcome


def segment_texts(conn: sqlite3.Connection, video_id: int) -> list[tuple[int, str]]:
    """The Video's Segments as (id, passage text): what each is embedded as."""
    rows = conn.execute("SELECT id, context, text FROM segments WHERE video_id = ? ORDER BY id", (video_id,))
    return [(row["id"], passage_text(row["context"], row["text"])) for row in rows]


def record_embeddings(
    conn: sqlite3.Connection, video_id: int, vectors: Sequence[tuple[int, Sequence[float]]]
) -> StageOutcome:
    """Stores a vector for each of the Video's Segments, replacing any they had, and advances the stage.

    Nothing is written for a Video that is gone or has been excluded meanwhile. Raises if the vectors aren't for
    exactly the Video's current Segments.
    """
    with transaction(conn):
        if (outcome := videos.standing(conn, video_id)) != "advanced":
            return outcome
        segment_ids = [r["id"] for r in conn.execute("SELECT id FROM segments WHERE video_id = ?", (video_id,))]
        if sorted(segment_id for segment_id, _ in vectors) != sorted(segment_ids):
            raise RuntimeError("The Video's Segments changed while it was being embedded")
        # One delete per id: vec0 looks rows up by primary key, but would scan every vector for a subquery.
        conn.executemany("DELETE FROM segment_vectors WHERE segment_id = ?", [(i,) for i in segment_ids])
        conn.executemany(
            "INSERT INTO segment_vectors (segment_id, video_id, embedding) VALUES (?, ?, ?)",
            [(segment_id, video_id, sqlite_vec.serialize_float32(list(vector))) for segment_id, vector in vectors],
        )
        videos.complete_stage(conn, video_id, "embedded")
        return outcome
