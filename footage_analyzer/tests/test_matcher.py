import pytest

from footage_analyzer.matcher import build_visual_edl


@pytest.fixture
def semantic_rank(monkeypatch):
    def fake_rank(query, texts, mode="hybrid", provider="auto"):
        # Deterministic semantic ordering for tests.
        rows = []
        for i, text in enumerate(texts):
            low = text.lower()
            score = 0.95 if "soldier" in low and "march" in low else 0.45
            rows.append((i, score, score, 0.0, "test-semantic"))
        return sorted(rows, key=lambda x: x[1], reverse=True)
    monkeypatch.setattr("footage_analyzer.matcher.rank_texts", fake_rank)


def test_visual_edl_uses_voiceover_clock_and_duration(semantic_rank):
    narration=[{"index":0,"start":0.0,"end":5.0,"text":"soldiers marching"}]
    requirements=[{"narration_index":0,"visual_query":"British colonial soldiers moving through mountainous terrain",
                   "preferred_visuals":["soldiers marching","hills"],"avoid":[],"rationale":""}]
    shots=[
        {"id":"a","video_path":"soldiers.mp4","start":10.0,"end":16.0,"duration":6.0,
         "description":"soldiers marching through a road","subjects":["soldiers"],"actions":["marching"],
         "setting":["road"],"tags":["military"]},
        {"id":"b","video_path":"village.mp4","start":0.0,"end":8.0,"duration":8.0,
         "description":"village houses","subjects":["houses"],"actions":[],"setting":["village"],"tags":[]},
    ]
    edl=build_visual_edl(narration,requirements,shots)
    assert len(edl)==1
    clip=edl[0]
    assert clip["timeline_start"]==0.0
    assert clip["timeline_end"]==5.0
    assert clip["source_path"]=="soldiers.mp4"
    assert clip["source_start"]==10.0
    assert clip["source_end"]==15.0
    assert clip["duration_fit"]==1.0
    assert clip["match_type"]=="direct"


def test_related_footage_can_fill_when_exact_visual_is_missing(semantic_rank):
    narration=[{"index":0,"start":0.0,"end":8.0,"text":"soldiers moved through the mountains"}]
    requirements=[{"narration_index":0,"visual_query":"soldiers moving through mountainous terrain",
                   "preferred_visuals":["soldiers moving","mountains"],"avoid":[],"rationale":""}]
    shots=[
        {"id":"soldiers","video_path":"soldiers.mp4","start":10.0,"end":13.0,"duration":3.0,
         "description":"soldiers marching on a road","subjects":["soldiers"],"actions":["marching"],
         "setting":["road"],"tags":["military"]},
        {"id":"hills","video_path":"hills.mp4","start":2.0,"end":7.0,"duration":5.0,
         "description":"people walking along a hill trail","subjects":["people"],"actions":["walking"],
         "setting":["hills"],"tags":["landscape"]},
    ]
    edl=build_visual_edl(narration,requirements,shots)
    assert len(edl)==2
    assert sum(x["duration"] for x in edl)==pytest.approx(8.0)
    assert edl[0]["source_path"]=="soldiers.mp4"
    assert edl[1]["source_path"]=="hills.mp4"
    assert edl[0]["timeline_start"]==0.0
    assert edl[1]["timeline_start"]==3.0


def test_short_shot_is_not_stretched_and_library_can_be_reused(semantic_rank):
    narration=[{"index":0,"start":0.0,"end":7.0,"text":"soldiers moving"}]
    requirements=[{"narration_index":0,"visual_query":"soldiers moving",
                   "preferred_visuals":["soldiers moving"],"avoid":[],"rationale":""}]
    shots=[{"id":"a","video_path":"soldiers.mp4","start":4.0,"end":6.0,"duration":2.0,
            "description":"soldiers walking","subjects":["soldiers"],"actions":["walking"],
            "setting":["road"],"tags":["military"]}]
    edl=build_visual_edl(narration,requirements,shots)
    assert sum(x["duration"] for x in edl)==pytest.approx(7.0)
    assert len(edl)>=2
    assert any("reused footage" in x["reason"] for x in edl)
