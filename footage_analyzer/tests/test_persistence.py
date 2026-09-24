from pathlib import Path

def test_index_resumes_and_skips_unchanged_files(tmp_path, monkeypatch):
    from footage_analyzer import indexer

    root=tmp_path/"footage"; root.mkdir()
    # Names sort in processing order: build_index walks files alphabetically.
    files=[root/"1-one.mp4",root/"2-two.mp4",root/"3-three.mp4"]
    for i,p in enumerate(files): p.write_bytes(bytes([i+1])*10)

    calls=[]
    def crash_after_first(path):
        calls.append(Path(path).name)
        if len(calls)==2:
            raise KeyboardInterrupt("simulated crash")
        return [(0.0,5.0)],24.0
    monkeypatch.setattr(indexer,"detect_scenes",crash_after_first)

    out=tmp_path/"index.json"
    try:
        indexer.build_index(str(root),str(out))
    except KeyboardInterrupt:
        pass

    manifest=(tmp_path/"file_manifest.json")
    assert manifest.exists()
    saved=__import__("json").loads(manifest.read_text())
    assert saved[str(files[0].resolve())]["status"]=="complete"
    assert saved[str(files[1].resolve())]["status"]=="processing"

    calls.clear()
    def record(path):
        calls.append(Path(path).name)
        return [(0.0,5.0)],24.0
    monkeypatch.setattr(indexer,"detect_scenes",record)
    rows=indexer.build_index(str(root),str(out))
    assert len(rows)==3
    assert str(files[0].resolve()) not in calls
    assert calls==["2-two.mp4","3-three.mp4"]

def test_clear_cache_does_not_touch_original_footage(tmp_path):
    from footage_analyzer.cache import cache_dir, clear_cache
    root=tmp_path/"footage"; root.mkdir()
    original=root/"clip.mp4"; original.write_bytes(b"original")
    work=tmp_path/"work"; cache=cache_dir(work,str(root)); cache.mkdir(parents=True)
    (cache/"visual_index.json").write_text("cache")
    result=clear_cache(work,str(root))
    assert result["cleared_bytes"]>0
    assert original.read_bytes()==b"original"
    assert not cache.exists()
