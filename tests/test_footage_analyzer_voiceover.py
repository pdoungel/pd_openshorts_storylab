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


def test_word_annotation_with_missing_end_is_ignored():
    from footage_analyzer.voiceover import _extract_word_annotations

    interaction = {
        "annotations": [
            {"type": "word_info", "text": "broken", "start_offset": "1s"},
            {"type": "word_info", "text": "valid", "start_offset": "1.0s", "end_offset": "1.5s"},
        ]
    }
    words = _extract_word_annotations(interaction)
    assert words == [{"word": "valid", "start": 1.0, "end": 1.5}]


def test_extract_word_annotations_walks_sdk_style_objects():
    from footage_analyzer.voiceover import _extract_word_annotations

    class Word:
        type = "word_info"
        text = "hello"
        start_offset = "0.0s"
        end_offset = "0.4s"

    class Output:
        def __init__(self):
            self.annotations = [Word()]

    class Interaction:
        def __init__(self):
            self.outputs = [Output()]

    assert _extract_word_annotations(Interaction()) == [
        {"word": "hello", "start": 0.0, "end": 0.4}
    ]


def test_interaction_status_accepts_enum_like_status():
    from footage_analyzer.voiceover import _interaction_status

    class Status:
        value = "IN_PROGRESS"

    class Interaction:
        status = Status()

    assert _interaction_status(Interaction()) == "in_progress"
