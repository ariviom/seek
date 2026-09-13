"""Pure ranking steps of a search: fusing the vector and lexical hits, recency, and the matched cue."""

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import snowballstemmer

from mentor.segmentation import SegmentCue

RRF_K = 60

# Words too common to say which cue a query matched.
_COMMON_WORDS = frozenset(
    """
    a about an and are as at be but by can do does for from how i if in into is it its my of on or out so that
    the their then there these they this to up was we what when where which who why will with you your
    """.split()
)


def fuse(rankings: Sequence[Sequence[int]], limit: int) -> list[int]:
    """Reciprocal Rank Fusion of ranked id lists, best first; ties keep the order ids were first seen."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1 / (RRF_K + rank)
    return sorted(scores, key=lambda item: -scores[item])[:limit]


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    # Written this way so a very negative score doesn't overflow.
    return math.exp(x) / (1 + math.exp(x))


@dataclass(frozen=True)
class Recency:
    """How much newer Videos are preferred. Age takes a penalty that closes half its distance to max_penalty (a
    fraction of the score) every half-life, so old advice loses near-ties but never sinks below a clearly worse
    match."""

    half_life_days: int
    max_penalty: float


def recency_score(
    reranker_logit: float, published_on: date, today: date, temperature: float, recency: Recency | None
) -> float:
    """The reranker logit squashed into 0..1, less the Video's age penalty; None turns recency off.

    The temperature divides the logit first: a reranker's logits for relevant passages run high enough that a plain
    sigmoid would score them all alike.
    """
    score = _sigmoid(reranker_logit / temperature)
    if recency is None:
        return score
    age_days = max((today - published_on).days, 0)
    faded = 1 - math.pow(0.5, age_days / recency.half_life_days)
    return score * (1 - recency.max_penalty * faded)


def _terms(stem: Callable[[list[str]], list[str]], text: str) -> set[str]:
    return set(stem([w for w in re.findall(r"\w+", text.casefold()) if w not in _COMMON_WORDS]))


def matched_seconds(query: str, text: str, cues: Sequence[SegmentCue], start: float) -> float:
    """The start of the Segment cue sharing the most query terms (the earliest on a tie), else the Segment start."""
    # Porter stems, as the FTS5 index uses, so a cue that matched lexically also matches here.
    stem = snowballstemmer.stemmer("porter").stemWords
    wanted = _terms(stem, query)
    best_start, best_overlap = start, 0
    for cue, following in zip(cues, [*cues[1:], None], strict=True):
        cue_text = text[cue.offset : following.offset if following else len(text)]
        overlap = len(wanted & _terms(stem, cue_text))
        if overlap > best_overlap:
            best_start, best_overlap = cue.start, overlap
    return best_start
