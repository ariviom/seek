"""Frames of a cited moment, cropped from the sheets of a Video's scrubber storyboard.

Frames are an index, not evidence: they say what was on screen around a Segment so a result can be recognised.
Nothing here downloads, stores, or reads an image; only the geometry and the sheets' shared URL are kept.

Functions are blocking; run them through Database.run.
"""

import json
import math
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from seek.db import now_iso
from seek.ports import Storyboard

# The most frames one strip asks for: five in search, three in the Sources column.
MAX_FRAMES = 5
# Absorbs the float division behind fps when the tile count is worked out from it.
_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Moment:
    """The frames one strip wants: `count` of them from `seconds` on, a storyboard interval apart."""

    video_id: int
    seconds: float
    count: int


@dataclass(frozen=True)
class Frame:
    """One tile of a sheet: the moment it shows, the sheet holding it, and where in that sheet's grid it sits."""

    seconds: float
    url: str
    column: int
    row: int


@dataclass(frozen=True)
class VideoFrames:
    # The grid every one of these frames is cropped out of.
    columns: int
    rows: int
    video_id: int
    # The moment asked for, echoed back: one Video can be asked about twice, once per run of its results.
    seconds: float
    frames: list[Frame]


def record(conn: sqlite3.Connection, video_id: int, storyboard: Storyboard | None) -> bool:
    """Within a transaction: stores the Video's storyboard geometry, or clears it when the Video has none.

    False when the Video is no longer there to store one for.

    A Video re-fetched without a storyboard loses the one it had: that template's signature is expiring, and a
    stale one renders as a tile nothing can tell from a frame. A Video deleted meanwhile stores nothing rather
    than failing on its missing parent, so a backfill outlives a Channel removed while it runs.
    """
    if storyboard is None:
        conn.execute("DELETE FROM storyboards WHERE video_id = ?", (video_id,))
        return True
    cursor = conn.execute(
        """
        INSERT OR REPLACE INTO storyboards
            (video_id, columns, rows, width, height, fps, url_template, fragment_count, fetched_at)
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM videos WHERE id = ?)
        """,
        (
            video_id,
            storyboard.columns,
            storyboard.rows,
            storyboard.width,
            storyboard.height,
            storyboard.fps,
            storyboard.url_template,
            storyboard.fragment_count,
            now_iso(),
            video_id,
        ),
    )
    return cursor.rowcount == 1


def frames_at(storyboard: Storyboard, duration_seconds: int | None, moment: Moment) -> list[Frame]:
    """The tiles from the moment on, one storyboard interval apart; fewer than asked for near the Video's end.

    A tile covers 1/fps seconds, so the moment's own tile leads and each later one follows it by that. The sheets
    run out at fragment_count, and their last sheet is only partly filled, so the Video's length decides the final
    tile: asking past it yields the frames that exist and no blank ones.

    fps is a frame count divided by the Video's real length, and duration_seconds is that length rounded, so their
    product lands a hair either side of the whole tile count. The lower end of the rounding is taken, with a
    tolerance for the division: being one tile short at the very end of a Video costs a frame nobody misses, while
    being one over paints an empty cell of a sheet that loaded perfectly well, which no onError can catch.
    """
    interval = 1 / storyboard.fps
    per_sheet = storyboard.columns * storyboard.rows
    last = per_sheet * storyboard.fragment_count - 1
    if duration_seconds is not None:
        last = min(last, math.ceil((duration_seconds - 0.5) * storyboard.fps - _TOLERANCE) - 1)
    first = int(max(moment.seconds, 0.0) // interval)
    frames = []
    for index in range(first, min(first + moment.count, last + 1)):
        sheet, cell = divmod(index, per_sheet)
        row, column = divmod(cell, storyboard.columns)
        frames.append(
            Frame(
                seconds=index * interval,
                url=storyboard.url_template.replace("{index}", str(sheet)),
                column=column,
                row=row,
            )
        )
    return frames


def read_frames(conn: sqlite3.Connection, moments: Sequence[Moment]) -> list[VideoFrames]:
    """The frames each moment asks for, leaving out any Video with no stored geometry and no frames to give.

    A Video of a Channel that is not indexed is left out too, as it is everywhere else.
    """
    rows = conn.execute(
        """
        SELECT storyboards.*, videos.duration_seconds
        FROM storyboards
        JOIN videos ON videos.id = storyboards.video_id
        JOIN channels ON channels.id = videos.channel_id
        WHERE channels.indexed = 1 AND storyboards.video_id IN (SELECT value FROM json_each(?))
        """,
        (_ids(moments),),
    )
    stored = {row["video_id"]: row for row in rows}
    found = []
    for moment in moments:
        row = stored.get(moment.video_id)
        if row is None:
            continue
        frames = frames_at(_storyboard(row), row["duration_seconds"], moment)
        if frames:
            found.append(VideoFrames(row["columns"], row["rows"], moment.video_id, moment.seconds, frames))
    return found


def missing(conn: sqlite3.Connection, channel_id: int | None) -> list[tuple[int, str]]:
    """The searchable Videos of the Channel, or of every Channel, with no storyboard stored yet, as discovered.

    Only a done Video of an indexed Channel can be cited, and read_frames serves only those, so no YouTube call is
    spent on any other; a Video still being ingested gets its geometry from its own extraction.
    """
    rows = conn.execute(
        """
        SELECT videos.id, videos.youtube_video_id FROM videos
        JOIN channels ON channels.id = videos.channel_id
        LEFT JOIN storyboards ON storyboards.video_id = videos.id
        WHERE storyboards.video_id IS NULL AND videos.pipeline_stage = 'done' AND channels.indexed = 1
          AND (?1 IS NULL OR videos.channel_id = ?1)
        ORDER BY videos.id
        """,
        (channel_id,),
    )
    return [(row["id"], row["youtube_video_id"]) for row in rows]


def _ids(moments: Sequence[Moment]) -> str:
    # Bound as one JSON array, as search's Channel ids are.
    return json.dumps(sorted({moment.video_id for moment in moments}))


def _storyboard(row: sqlite3.Row) -> Storyboard:
    return Storyboard(
        columns=row["columns"],
        rows=row["rows"],
        width=row["width"],
        height=row["height"],
        fps=row["fps"],
        url_template=row["url_template"],
        fragment_count=row["fragment_count"],
    )
