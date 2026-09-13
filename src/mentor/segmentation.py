"""Cutting a Transcript into Segments, the unit of retrieval and citation."""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import groupby

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
    """Windows of up to 90 s starting at cue starts, overlapping by about 15 s, never crossing a chapter start.

    A final window shorter than 60 s starts earlier instead, so a chapter's tail isn't a sliver. Cues are in
    time order; blank cues are dropped.
    """
    spoken = [c for c in cues if c.text.strip()]
    ordered = sorted(chapters, key=lambda c: c.start)
    starts = [c.start for c in ordered]
    segments: list[Segment] = []
    # A cue belongs to the chapter it starts in; -1 is before the first chapter.
    for index, section in groupby(spoken, key=lambda cue: bisect_right(starts, cue.start) - 1):
        segments += _windows(list(section), ordered[index].title if index >= 0 else None)
    return segments


def _windows(cues: list[Cue], chapter_title: str | None) -> list[Segment]:
    windows: list[Segment] = []
    first, previous_first = 0, -1
    while True:
        last = first
        while last + 1 < len(cues) and cues[last + 1].end - cues[first].start <= MAX_SECONDS:
            last += 1
        end = cues[last].end
        is_final = last == len(cues) - 1
        if is_final and windows and end - cues[first].start < MIN_SECONDS:
            pulled_back = bisect_right([c.start for c in cues], end - MIN_SECONDS) - 1
            first = max(previous_first + 1, pulled_back)
        windows.append(_window(cues[first : last + 1], chapter_title))
        if is_final:
            return windows
        # The next window starts at the first cue inside the overlap, but never past the next unseen cue.
        overlap_starts = (k for k in range(first + 1, last + 1) if cues[k].start >= end - OVERLAP_SECONDS)
        previous_first, first = first, next(overlap_starts, last + 1)


def _window(cues: list[Cue], chapter_title: str | None) -> Segment:
    texts = [" ".join(c.text.split()) for c in cues]
    offsets = [sum(len(t) + 1 for t in texts[:i]) for i in range(len(texts))]
    return Segment(
        start=cues[0].start,
        end=cues[-1].end,
        text=" ".join(texts),
        chapter_title=chapter_title,
        cues=[SegmentCue(start=c.start, offset=o) for c, o in zip(cues, offsets, strict=True)],
    )
