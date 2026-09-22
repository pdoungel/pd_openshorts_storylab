from pathlib import Path

def test_analyzer_modules_do_not_import_storylab():
    root=Path(__file__).parents[1]
    forbidden=("storylab","gemini_worker","transcribe_backends","scene_detection")
    for path in root.glob("*.py"):
        if path.name.startswith("test_"):
            continue
        text=path.read_text(encoding="utf-8")
        assert not any(("import "+x) in text or ("from "+x+" ") in text for x in forbidden), path.name

def test_voiceover_segments_preserve_master_clock():
    from footage_analyzer.voiceover import sentence_segments
    tr={"segments":[{"start":0.0,"end":2.5,"text":" First line "},{"start":2.5,"end":5.0,"text":"Second line"}]}
    rows=sentence_segments(tr)
    assert rows[0]["start"]==0.0 and rows[0]["end"]==2.5
    assert rows[1]["start"]==2.5 and rows[1]["end"]==5.0
