from mentor.ports import Chapter, Cue
from mentor.segmentation import Segment, SegmentCue, segment


def steady_cues(until: float, every: float = 5.0) -> list[Cue]:
    return [Cue(start=i * every, end=(i + 1) * every, text=f"line {i}") for i in range(round(until / every))]


def spans(segments: list[Segment]) -> list[tuple[float, float, str | None]]:
    return [(s.start, s.end, s.chapter_title) for s in segments]


def test_windows_of_up_to_90_seconds_overlap_by_15_seconds_at_cue_starts() -> None:
    segments = segment(steady_cues(until=300), chapters=[])

    assert spans(segments) == [(0, 90, None), (75, 165, None), (150, 240, None), (225, 300, None)]


def test_windows_overlap_by_at_least_15_seconds_when_cues_are_long() -> None:
    segments = segment(steady_cues(until=200, every=20), chapters=[])

    assert spans(segments) == [(0, 80, None), (60, 140, None), (120, 200, None)]


def test_a_short_final_window_starts_earlier_so_it_still_spans_60_seconds() -> None:
    segments = segment(steady_cues(until=200), chapters=[])

    assert spans(segments) == [(0, 90, None), (75, 165, None), (140, 200, None)]


def test_windows_never_cross_a_chapter_boundary_and_carry_the_chapter_title() -> None:
    chapters = [Chapter(title="Sawing", start=100, end=300), Chapter(title="Marking out", start=0, end=100)]

    segments = segment(steady_cues(until=300), chapters)

    assert spans(segments) == [
        (0, 90, "Marking out"),
        (40, 100, "Marking out"),
        (100, 190, "Sawing"),
        (175, 265, "Sawing"),
        (240, 300, "Sawing"),
    ]


def test_a_short_final_window_never_starts_so_early_that_it_exceeds_90_seconds() -> None:
    cues = [Cue(0, 10, "a"), Cue(10, 85, "b"), Cue(85, 100, "c"), Cue(100, 110, "d")]

    segments = segment(cues, chapters=[])

    assert spans(segments) == [(0, 85, None), (10, 100, None), (85, 110, None)]


def test_a_cue_running_past_a_chapter_start_is_cut_off_there() -> None:
    chapters = [Chapter(title="Glue-up", start=0, end=50), Chapter(title="Clamping", start=50, end=70)]

    segments = segment([Cue(0, 40, "spread glue"), Cue(40, 70, "close the joint")], chapters)

    assert spans(segments) == [(0, 50, "Glue-up")]


def test_cues_in_any_order_and_overlapping_captions_give_the_true_span() -> None:
    segments = segment([Cue(1, 3, "second"), Cue(0, 50, "first")], chapters=[])

    assert [(s.start, s.end, s.text) for s in segments] == [(0, 50, "first second")]


def test_cues_before_the_first_chapter_have_no_chapter_title() -> None:
    segments = segment(steady_cues(until=180), [Chapter(title="The build", start=30, end=180)])

    assert spans(segments) == [(0, 30, None), (30, 120, "The build"), (105, 180, "The build")]


def test_a_transcript_shorter_than_a_window_is_one_segment_and_an_empty_one_is_none() -> None:
    assert spans(segment(steady_cues(until=40), chapters=[])) == [(0, 40, None)]
    assert segment([], chapters=[]) == []


def test_a_cue_longer_than_a_window_is_a_segment_of_its_own() -> None:
    cues = [Cue(0, 5, "intro"), Cue(5, 125, "a very long demonstration"), Cue(125, 130, "outro")]

    segments = segment(cues, chapters=[])

    assert [s.text for s in segments] == ["intro", "a very long demonstration", "outro"]


def test_segment_text_joins_cleaned_cue_text_and_records_where_each_cue_starts() -> None:
    cues = [
        Cue(start=1.5, end=4.0, text="Mark the\nbaseline "),
        Cue(start=4.0, end=4.5, text="\n"),
        Cue(start=4.5, end=8.0, text="with a  cutting gauge"),
    ]

    [only] = segment(cues, chapters=[])

    assert only == Segment(
        start=1.5,
        end=8.0,
        text="Mark the baseline with a cutting gauge",
        chapter_title=None,
        cues=[SegmentCue(start=1.5, offset=0), SegmentCue(start=4.5, offset=18)],
    )
    assert only.text[18:] == "with a cutting gauge"
