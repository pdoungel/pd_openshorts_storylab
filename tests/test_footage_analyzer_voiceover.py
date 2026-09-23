from footage_analyzer.voiceover import _normalise_segments, _parse_timestamp, _words_to_segments


def test_parse_timestamp_accepts_seconds_and_offsets():
    assert _parse_timestamp("1.25s") == 1.25
    assert _parse_timestamp("1250ms") == 1.25
    assert _parse_timestamp("01:02.5") == 62.5


def test_word_annotations_are_grouped_into_editable_segments():
    words = [
        {"word": "The", "start": 0.0, "end": 0.2},
        {"word": "forces", "start": 0.21, "end": 0.5},
        {"word": "arrived.", "start": 0.51, "end": 0.9},
        {"word": "They", "start": 1.2, "end": 1.4},
        {"word": "marched.", "start": 1.41, "end": 1.8},
    ]
    segments = _words_to_segments(words)
    assert len(segments) == 2
    assert segments[0]["start"] == 0.0
    assert segments[0]["end"] == 0.9
    assert segments[1]["text"] == "They marched."


def test_overlapping_segments_are_clamped_in_voiceover_order():
    segments = _normalise_segments(
        [
            {"start": 0, "end": 2, "text": "first"},
            {"start": 1.5, "end": 3, "text": "second"},
        ],
        3,
    )
    assert [(s["start"], s["end"]) for s in segments] == [(0.0, 2.0), (2.0, 3.0)]
