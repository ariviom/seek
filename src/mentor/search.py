"""Hybrid search over Segments: vector and lexical hits, fused, reranked, and adjusted for recency."""

import asyncio
import json
import re
import sqlite3
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Literal

import sqlite_vec

from mentor.db import Database
from mentor.errors import NotFound
from mentor.ports import Embedder, Reranker
from mentor.ranking import Recency, fuse, matched_seconds, recency_score
from mentor.segmentation import SegmentCue
from mentor.segments import passage_text
from mentor.sources import watch_url

type PreferRecent = Literal["off", "gentle", "strong"]

# Hits taken from each of the vector and lexical searches, and fused hits passed to the reranker.
CANDIDATES = 50
# Segments of one Video among the results before others get a turn: adjacent windows overlap, so one passage
# would otherwise fill the top of the list on its own.
PER_VIDEO = 3


@dataclass(frozen=True)
class SearchResult:
    segment_id: int
    text: str
    start_seconds: float
    # The start of the cue that best matched the query; the Citation links here.
    matched_seconds: float
    video_id: int
    youtube_video_id: str
    video_title: str
    published_on: date
    chapter_title: str | None
    channel_name: str
    mentor_name: str
    score: float
    url: str


@dataclass(frozen=True)
class _Candidate:
    result: SearchResult
    # What the Segment was embedded as, for the reranker.
    passage: str


# Blocking: run through Database.run.
def _scope_channels(conn: sqlite3.Connection, group: int | str | None, mentor_ids: Sequence[int] | None) -> list[int]:
    """The indexed Channels a search covers: a Group's Mentors, the given Mentors, or every Mentor.

    A Group is given by id (an int) or by name (a str), so a Group named "12" is never confused with Group 12.
    """
    if group is not None:
        column = "id" if isinstance(group, int) else "name"
        found = conn.execute(f"SELECT id FROM mentor_groups WHERE {column} = ?", (group,)).fetchone()
        if found is None:
            raise NotFound(f"Mentor Group {group!r} not found")
        rows = conn.execute(
            """
            SELECT channels.id FROM channels
            JOIN mentor_group_members ON mentor_group_members.mentor_id = channels.mentor_id
            WHERE mentor_group_members.group_id = ? AND channels.indexed = 1
            """,
            (found["id"],),
        )
    elif mentor_ids is not None:
        # Bound as one JSON array, as groups.set_members does.
        ids = json.dumps(list(dict.fromkeys(mentor_ids)))
        existing = {
            row["id"]
            for row in conn.execute("SELECT id FROM mentors WHERE id IN (SELECT value FROM json_each(?))", (ids,))
        }
        if missing := [mentor_id for mentor_id in mentor_ids if mentor_id not in existing]:
            raise NotFound(f"Mentor {missing[0]} not found")
        rows = conn.execute(
            "SELECT id FROM channels WHERE indexed = 1 AND mentor_id IN (SELECT value FROM json_each(?))", (ids,)
        )
    else:
        rows = conn.execute("SELECT id FROM channels WHERE indexed = 1")
    return [row["id"] for row in rows]


# Blocking: run through Database.run.
def _candidates(
    conn: sqlite3.Connection, channel_ids: Sequence[int], query: str, query_vector: Sequence[float]
) -> list[_Candidate]:
    """The fused top vector and lexical hits within the Channels, best first and not yet scored."""
    in_channels = ", ".join("?" * len(channel_ids))
    # Scoped inside the KNN query, so a small Channel still gets its nearest Segments.
    nearest = conn.execute(
        f"""
        SELECT segment_id FROM segment_vectors
        WHERE embedding MATCH ? AND k = ? AND channel_id IN ({in_channels})
        ORDER BY distance
        """,
        (sqlite_vec.serialize_float32(list(query_vector)), CANDIDATES, *channel_ids),
    )
    rankings = [[row["segment_id"] for row in nearest]]
    # Any query word may match; quoting each word keeps FTS5 syntax in the query from being interpreted.
    # Segments are indexed once a Video is segmented, but only a done Video's are searchable.
    if words := re.findall(r"\w+", query):
        lexical = conn.execute(
            f"""
            SELECT segments.id FROM segments_fts
            JOIN segments ON segments.id = segments_fts.rowid
            JOIN videos ON videos.id = segments.video_id
            WHERE segments_fts MATCH ? AND videos.channel_id IN ({in_channels}) AND videos.pipeline_stage = 'done'
            ORDER BY bm25(segments_fts)
            LIMIT ?
            """,
            (" OR ".join(f'"{word}"' for word in words), *channel_ids, CANDIDATES),
        )
        rankings.append([row["id"] for row in lexical])
    fused = fuse(rankings, limit=CANDIDATES)
    rows = conn.execute(
        """
        SELECT segments.id, segments.text, segments.context, segments.start_seconds, segments.cues,
               segments.chapter_title, videos.id AS video_id, videos.youtube_video_id, videos.title, videos.published_on,
               channels.name AS channel_name, mentors.name AS mentor_name
        FROM segments
        JOIN videos ON videos.id = segments.video_id
        JOIN channels ON channels.id = videos.channel_id
        JOIN mentors ON mentors.id = channels.mentor_id
        WHERE segments.id IN (SELECT value FROM json_each(?)) AND videos.pipeline_stage = 'done'
        """,
        (json.dumps(fused),),
    )
    by_id = {row["id"]: _unscored(query, row) for row in rows}
    # A Segment replaced since the index lookups, or of a Video not yet done, is left out.
    return [by_id[segment_id] for segment_id in fused if segment_id in by_id]


def _unscored(query: str, row: sqlite3.Row) -> _Candidate:
    cues = [SegmentCue(**cue) for cue in json.loads(row["cues"])]
    matched = matched_seconds(query, row["text"], cues, row["start_seconds"])
    result = SearchResult(
        segment_id=row["id"],
        text=row["text"],
        start_seconds=row["start_seconds"],
        matched_seconds=matched,
        video_id=row["video_id"],
        youtube_video_id=row["youtube_video_id"],
        video_title=row["title"],
        published_on=date.fromisoformat(row["published_on"]),
        chapter_title=row["chapter_title"],
        channel_name=row["channel_name"],
        mentor_name=row["mentor_name"],
        score=0.0,
        url=watch_url(row["youtube_video_id"], int(matched)),
    )
    return _Candidate(result, passage_text(row["context"], row["text"]))


class Search:
    def __init__(
        self,
        database: Database,
        embedder: Embedder,
        reranker: Reranker,
        temperature: float,
        recency: Mapping[PreferRecent, Recency | None],
    ) -> None:
        self._database = database
        self._embedder = embedder
        self._reranker = reranker
        self._temperature = temperature
        self._recency = recency

    async def search(
        self,
        query: str,
        *,
        group: int | str | None = None,
        mentor_ids: Sequence[int] | None = None,
        limit: int = 10,
        prefer_recent: PreferRecent = "gentle",
    ) -> list[SearchResult]:
        """The best Segments for the query within one scope: a Group, some Mentors, or (neither given) everything."""
        # Composed, so accented words typed in decomposed form still match the transcript's words.
        query = unicodedata.normalize("NFC", query)
        channel_ids = await self._database.run(lambda conn: _scope_channels(conn, group, mentor_ids))
        if not channel_ids:
            return []
        query_vector = await asyncio.to_thread(self._embedder.embed_query, query)
        candidates = await self._database.run(lambda conn: _candidates(conn, channel_ids, query, query_vector))
        if not candidates:
            return []
        reranked = await asyncio.to_thread(self._reranker.score, query, [c.passage for c in candidates])
        today = datetime.now(UTC).date()
        recency = self._recency[prefer_recent]
        scored = [
            replace(c.result, score=recency_score(logit, c.result.published_on, today, self._temperature, recency))
            for logit, c in zip(reranked, candidates, strict=True)
        ]
        # Stable: equal scores keep the fused order.
        scored.sort(key=lambda result: -result.score)
        return spread_across_videos(scored, limit)


def spread_across_videos(scored: Sequence[SearchResult], limit: int) -> list[SearchResult]:
    """The best `limit` results with at most PER_VIDEO from any one Video; the rest fill in only after every
    Video's best windows, so a scope with few Videos still gets a full list."""
    taken: dict[int, int] = {}
    within: list[SearchResult] = []
    overflow: list[SearchResult] = []
    for result in scored:
        if taken.get(result.video_id, 0) < PER_VIDEO:
            taken[result.video_id] = taken.get(result.video_id, 0) + 1
            within.append(result)
        else:
            overflow.append(result)
    return (within + overflow)[:limit]
