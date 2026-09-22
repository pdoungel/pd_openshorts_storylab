from footage_analyzer.matcher import build_visual_edl

def test_visual_edl_uses_voiceover_clock_and_duration():
    narration=[{"index":0,"start":0.0,"end":5.0,"text":"soldiers marching"}]
    requirements=[{"narration_index":0,"visual_query":"soldiers marching","preferred_visuals":[],"avoid":[],"rationale":""}]
    shots=[
        {"id":"a","video_path":"soldiers.mp4","start":10.0,"end":16.0,"duration":6.0,
         "description":"soldiers marching through a road","subjects":["soldiers"],"actions":["marching"],"setting":["road"],"tags":["military"]},
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
