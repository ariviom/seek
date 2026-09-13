"""Cutting a Transcript into Segments, the unit of retrieval and citation."""

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate, groupby

from mentor.ports import Chapter, Cue

MAX_SECONDS = 90.0
MIN_SECONDS = 60.0
OVERLAP_SECONDS = 15.0


@dataclass(frozen=True)
class SegmentCue:
    start: float
    # Where the cue's text begins in the Segment's text, so a match can cite the cue's own time.
    offset: int


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str
    chapter_title: str | None
    cues: list[SegmentCue]


def segment(cues: Sequence[Cue], chapters: Sequence[Chapter]) -> list[Segment]:
    """Windows of up to 90 s starting at cue starts, overlapping by at least 15 s, never crossing a chapter start.

    A final window shorter than 60 s starts earlier instead, so a chapter's tail isn't a sliver. Blank cues are
    dropped.
    """
    spoken = sorted((c for c in cues if c.text.strip()), key=lambda c: c.start)
    ordered = sorted(chapters, key=lambda c: c.start)
    chapter_starts = [c.start for c in ordered]
    segments: list[Segment] = []
    # A cue belongs to the chapter it starts in; -1 is before the first chapter.
    for index, section in groupby(spoken, key=lambda cue: bisect_right(chapter_starts, cue.start) - 1):
        title = ordered[index].title if index >= 0 else None
        # A cue running past the next chapter's start is cut off there.
        limit = chapter_starts[index + 1] if index + 1 < len(ordered) else math.inf
        segments += _windows(list(section), title, limit)
    return segments


def _windows(cues: list[Cue], chapter_title: str | None, limit: float) -> list[Segment]:
    starts = [c.start for c in cues]
    windows: list[Segment] = []
    first, previous_first = 0, -1
    while True:
        last = first
        while last + 1 < len(cues) and cues[last + 1].end - starts[first] <= MAX_SECONDS:
            last += 1
        end = _end(cues[first : last + 1], limit)
        is_final = last == len(cues) - 1
        if is_final and windows and end - starts[first] < MIN_SECONDS:
            # Start earlier, but after the previous window's start and no more than 90 s before the end.
            earliest = next(k for k in range(previous_first + 1, first + 1) if end - starts[k] <= MAX_SECONDS)
            first = max(earliest, bisect_right(starts, end - MIN_SECONDS) - 1)
        windows.append(_window(cues[first : last + 1], chapter_title, limit))
        if is_final:
            return windows
        # The next window starts at the latest cue that still overlaps by 15 s, and always moves forward.
        overlapping = bisect_right(starts, end - OVERLAP_SECONDS, lo=first + 1, hi=last + 1) - 1
        previous_first, first = first, max(first + 1, overlapping)


def _end(cues: list[Cue], limit: float) -> float:
    # Captions can overlap, so an earlier cue may end last.
    return min(max(c.end for c in cues), limit)


def _window(cues: list[Cue], chapter_title: str | None, limit: float) -> Segment:
    texts = [" ".join(c.text.split()) for c in cues]
    offsets = accumulate((len(t) + 1 for t in texts[:-1]), initial=0)
    return Segment(
        start=cues[0].start,
        end=_end(cues, limit),
        text=" ".join(texts),
        chapter_title=chapter_title,
        cues=[SegmentCue(start=c.start, offset=o) for c, o in zip(cues, offsets, strict=True)],
    )
