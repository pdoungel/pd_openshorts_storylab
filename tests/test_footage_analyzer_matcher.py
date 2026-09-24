from footage_analyzer.matcher import build_visual_edl


def test_edl_follows_voiceover_order_and_covers_each_segment():
    narrations = [
        {"index": 0, "start": 0.0, "end": 3.0, "text": "soldiers march through hills"},
        {"index": 1, "start": 4.0, "end": 7.0, "text": "a village appears"},
    ]
    requirements = [
        {
            "narration_index": 0,
            "visual_query": "soldiers marching hills",
            "preferred_visuals": ["soldiers", "march", "hills"],
        },
        {
            "narration_index": 1,
            "visual_query": "village",
            "preferred_visuals": ["village", "buildings"],
        },
    ]
    shots = [
        {
            "id": "village",
            "video_path": "/footage/village.mp4",
            "start": 0.0,
            "end": 3.0,
            "description": "village buildings and people",
            "subjects": ["people"],
            "actions": ["stand"],
            "setting": ["village"],
            "tags": ["village"],
        },
        {
            "id": "soldiers",
            "video_path": "/footage/soldiers.mp4",
            "start": 10.0,
            "end": 13.0,
            "description": "soldiers marching through hills",
            "subjects": ["soldiers"],
            "actions": ["march"],
            "setting": ["hills"],
            "tags": ["marching"],
        },
    ]

    edl = build_visual_edl(narrations, requirements, shots)

    assert [c["narration_index"] for c in edl] == [0, 1]
    assert [c["sequence"] for c in edl] == [1, 2]
    assert [(c["timeline_start"], c["timeline_end"]) for c in edl] == [
        (0.0, 3.0),
        (4.0, 7.0),
    ]
    assert edl[0]["source_path"].endswith("soldiers.mp4")
    assert edl[1]["source_path"].endswith("village.mp4")
    assert all(c["timeline_end"] > c["timeline_start"] for c in edl)


def test_planner_fallback_covers_every_narration_without_api(monkeypatch):
    from footage_analyzer.planner import plan
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    narrations = [
        {"index": 0, "start": 0.0, "end": 1.0, "text": "a road through the hills"},
        {"index": 1, "start": 1.0, "end": 2.0, "text": "people walking"},
    ]
    result = plan(narrations)

    assert [r["narration_index"] for r in result] == [0, 1]
    assert all(r["visual_query"] for r in result)
