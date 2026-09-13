from datetime import date, timedelta

import pytest

from mentor.ranking import fuse, matched_seconds, recency_score
from mentor.segmentation import SegmentCue


def test_fusion_ranks_hits_found_by_both_searches_above_hits_found_by_one() -> None:
    assert fuse([[1, 2, 3], [3, 4]], limit=50) == [3, 1, 2, 4]


def test_fusion_scores_reciprocal_ranks_with_k_60() -> None:
    # 5 is second in both lists: 2 / 62 beats a lone 1 / 61, but not 1 / 61 + 1 / 63. Ties keep first-seen order.
    assert fuse([[1, 5, 2], [6, 5, 7]], limit=50) == [5, 1, 6, 2, 7]
    assert fuse([[1, 5, 2], [2, 5, 1]], limit=50) == [1, 2, 5]


def test_fusion_keeps_only_the_top_of_the_fused_list() -> None:
    assert fuse([list(range(40)), list(range(100, 140))], limit=50) == [
        n for pair in zip(range(25), range(100, 125), strict=True) for n in pair
    ]


def test_fusion_of_nothing_is_empty() -> None:
    assert fuse([[], []], limit=50) == []


TODAY = date(2026, 9, 13)


def test_recency_off_is_the_sigmoid_of_the_reranker_score() -> None:
    assert recency_score(0.0, TODAY - timedelta(days=5000), TODAY, half_life_days=None) == 0.5
    assert recency_score(2.0, TODAY, TODAY, half_life_days=None) == pytest.approx(0.8808, abs=1e-4)
    assert recency_score(-1000.0, TODAY, TODAY, half_life_days=None) == pytest.approx(0.0)
    assert recency_score(1000.0, TODAY, TODAY, half_life_days=None) == pytest.approx(1.0)


def test_recency_halves_the_score_every_half_life_of_age() -> None:
    assert recency_score(0.0, TODAY, TODAY, half_life_days=365) == 0.5
    assert recency_score(0.0, TODAY - timedelta(days=365), TODAY, half_life_days=365) == pytest.approx(0.25)
    assert recency_score(0.0, TODAY - timedelta(days=730), TODAY, half_life_days=365) == pytest.approx(0.125)


def test_a_video_dated_after_today_is_not_boosted() -> None:
    assert recency_score(0.0, TODAY + timedelta(days=2), TODAY, half_life_days=365) == 0.5


# Cues: "Mark the baseline" at offset 0, "then saw to the line" at 18, "and chop out the waste" at 39.
TEXT = "Mark the baseline then saw to the line and chop out the waste"
CUES = [SegmentCue(start=12.0, offset=0), SegmentCue(start=15.5, offset=18), SegmentCue(start=19.0, offset=39)]


def test_the_matched_cue_is_the_one_sharing_the_most_query_terms() -> None:
    assert matched_seconds("how do I saw and chop to a line", TEXT, CUES, start=12.0) == 15.5


def test_matching_ignores_case_word_endings_and_common_words() -> None:
    assert matched_seconds("CHOPPING", TEXT, CUES, start=12.0) == 19.0
    assert matched_seconds("sawed lines", TEXT, CUES, start=11.0) == 15.5
    assert matched_seconds("Baselines", TEXT, CUES, start=11.0) == 12.0
    # Counting "out", "and", and "the" would pick the last cue.
    assert matched_seconds("out and the line", TEXT, CUES, start=12.0) == 15.5


def test_the_earliest_cue_wins_a_tie() -> None:
    assert matched_seconds("baseline waste", TEXT, CUES, start=11.0) == 12.0


def test_without_overlap_the_match_is_the_segment_start() -> None:
    assert matched_seconds("sharpening a chisel", TEXT, CUES, start=11.0) == 11.0
