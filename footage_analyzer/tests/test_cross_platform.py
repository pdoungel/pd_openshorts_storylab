"""Behaviour that must hold identically on macOS, Linux and Windows."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _make_clip(path, seconds=2, size="320x240"):
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc=duration={seconds}:size={size}:rate=25", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


def _make_wav(path, seconds=3):
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={seconds}", str(path)],
        check=True,
    )


# --- folder resolution -------------------------------------------------------

def test_find_locates_folder_and_file_on_this_platform(tmp_path):
    from footage_analyzer.server import _find

    target = tmp_path / "media" / "My Footage"
    target.mkdir(parents=True)
    clip = target / "clip one.mp4"
    clip.write_bytes(b"x" * 123)

    dirs = _find([tmp_path], want_dir="My Footage", timeout=10)
    assert target in [Path(p) for p in dirs]

    files = _find([tmp_path], want_file="clip one.mp4", size=123, timeout=10)
    assert clip in [Path(p) for p in files]
    assert _find([tmp_path], want_file="clip one.mp4", size=999, timeout=10) == []


def test_walk_find_skips_system_and_hidden_folders(tmp_path):
    from footage_analyzer.server import _walk_find

    for parent in ("Library", ".cache", "AppData", "Projects"):
        (tmp_path / parent / "Footage").mkdir(parents=True)
    hits = [Path(p).parent.name for p in _walk_find([tmp_path], want_dir="Footage", timeout=10)]
    assert hits == ["Projects"]


def test_search_roots_env_override(tmp_path, monkeypatch):
    from footage_analyzer.server import _search_roots

    monkeypatch.setenv("FOOTAGE_SEARCH_ROOTS", os.pathsep.join([str(tmp_path), str(tmp_path / "missing")]))
    assert _search_roots() == [tmp_path]


def test_default_search_roots_match_platform(monkeypatch):
    from footage_analyzer.server import _search_roots

    monkeypatch.delenv("FOOTAGE_SEARCH_ROOTS", raising=False)
    roots = _search_roots()
    if os.name == "nt":
        assert Path.home() in roots
    else:
        assert all(str(p) in {"/Users", "/Volumes"} for p in roots)


# --- durable state -----------------------------------------------------------

def test_replace_file_retries_a_briefly_locked_target(tmp_path, monkeypatch):
    from footage_analyzer import cache

    src, dst = tmp_path / "a.tmp", tmp_path / "a.json"
    src.write_text("new")
    real_replace = os.replace
    failures = {"left": 2}

    def flaky(a, b):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError("[WinError 5] Access is denied")
        return real_replace(a, b)

    monkeypatch.setattr(cache.os, "replace", flaky)
    monkeypatch.setattr(cache.time, "sleep", lambda s: None)
    cache.replace_file(src, dst)
    assert dst.read_text() == "new"


def test_job_status_survives_concurrent_reads(tmp_path):
    import threading
    from footage_analyzer.service import JobStore

    store = JobStore(root=tmp_path)
    jid = "job1"
    (tmp_path / jid).mkdir()
    store.jobs[jid] = {"id": jid, "status": "processing", "update_seq": 0}
    store._save(store.jobs[jid])

    errors = []

    def reader():
        for _ in range(200):
            try:
                assert store.get(jid)["id"] == jid
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

    t = threading.Thread(target=reader)
    t.start()
    for i in range(200):
        store.update(jid, progress=i)
    t.join()
    assert not errors
    assert store.get(jid)["progress"] == 199


# --- rendering timeline ------------------------------------------------------

def test_timeline_spans_cover_whole_voiceover_without_gaps():
    from footage_analyzer.render import timeline_spans

    clips = [
        {"timeline_start": 0.4, "timeline_end": 3.0},
        {"timeline_start": 3.9, "timeline_end": 8.8},
        {"timeline_start": 10.1, "timeline_end": 11.6},
    ]
    spans = timeline_spans(clips, 12.5)
    assert spans[0]["start"] == 0.0
    for left, right in zip(spans, spans[1:]):
        assert abs(left["start"] + left["duration"] - right["start"]) < 1e-9
    assert abs(spans[-1]["start"] + spans[-1]["duration"] - 12.5) < 1e-9


def test_frame_grid_does_not_drift_over_many_cuts():
    from footage_analyzer.render import timeline_spans

    fps = 30
    clips = [{"timeline_start": i * 1.37, "timeline_end": i * 1.37 + 1.2} for i in range(500)]
    total = 500 * 1.37
    spans = timeline_spans(clips, total)
    frames = sum(round((s["start"] + s["duration"]) * fps) - round(s["start"] * fps) for s in spans)
    assert frames == round(total * fps)


@pytest.mark.parametrize("aspect,fit", [("9:16", "blur"), ("16:9", "pad"), ("1:1", "crop")])
@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_render_produces_requested_format_in_sync(tmp_path, aspect, fit):
    from footage_analyzer.render import render, SIZES

    clip = tmp_path / "wide clip.mp4"
    _make_clip(clip, seconds=2)
    voice = tmp_path / "voice.wav"
    _make_wav(voice, seconds=3)
    result = {
        "voiceover_duration": 3.0,
        "clips": [
            {"timeline_start": 0.0, "timeline_end": 1.5, "source_path": str(clip), "source_start": 0.0},
            {"timeline_start": 1.5, "timeline_end": 3.0, "source_path": str(clip), "source_start": 0.5},
        ],
    }
    out = tmp_path / "final.mp4"
    info = render(result, voice, out, aspect=aspect, fit=fit)
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,duration", "-of", "json", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"]) == SIZES[aspect] == (info["width"], info["height"])
    assert abs(float(video["duration"]) - 3.0) < 0.1
    assert abs(float(video["duration"]) - float(audio["duration"])) < 0.1
    assert not (tmp_path / "render_parts").exists()


# --- indexing ----------------------------------------------------------------

@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_single_shot_clip_is_indexed_as_one_shot(tmp_path):
    from footage_analyzer.indexer import detect_scenes

    clip = tmp_path / "steady.mp4"
    _make_clip(clip, seconds=2)
    scenes, _fps = detect_scenes(str(clip))
    assert len(scenes) == 1
    assert scenes[0][0] == 0.0 and scenes[0][1] > 1.5


# --- exports and metadata ----------------------------------------------------

def test_export_copies_video_with_readable_name_and_youtube_text(tmp_path, monkeypatch):
    from footage_analyzer.service import export_video

    monkeypatch.setenv("FOOTAGE_EXPORT_DIR", str(tmp_path / "exports"))
    src = tmp_path / "final.mp4"
    src.write_bytes(b"video")
    job = {"voiceover_original_name": "0123456789abcdef0123456789abcdef-my voice?.wav", "aspect": "9:16"}
    meta = {"title": "T", "title_options": ["T", "U"], "description": "D", "tags": ["a", "b"]}
    out = Path(export_video(str(src), job, meta))
    assert out.parent == tmp_path / "exports"
    assert out.name.startswith("my voice_") and "_9x16_" in out.name and out.suffix == ".mp4"
    text = out.with_suffix(".youtube.txt").read_text(encoding="utf-8")
    assert "TITLE\nT" in text and "TAGS\na, b" in text


def test_youtube_chapters_follow_youtube_rules():
    from footage_analyzer.metadata import _valid_chapters

    chapters = _valid_chapters(
        [{"start": 3, "title": "Intro"}, {"start": 8, "title": "Too close"},
         {"start": 20, "title": "Middle"}, {"start": 45, "title": "End"}, {"start": 58, "title": "Too late"}],
        duration=60,
    )
    assert [c["title"] for c in chapters] == ["Intro", "Middle", "End"]
    assert chapters[0]["start"] == 0.0
    assert _valid_chapters([{"start": 0, "title": "Only"}], duration=60) == []


def test_tts_chunks_respect_limit_and_keep_text():
    from footage_analyzer.tts import _chunks, MAX_CHARS

    script = "\n\n".join(("Sentence number %d is here. " % i) * 40 for i in range(6))
    chunks = _chunks(script)
    assert all(len(c) <= MAX_CHARS for c in chunks)
    assert " ".join(chunks).split() == script.split()
