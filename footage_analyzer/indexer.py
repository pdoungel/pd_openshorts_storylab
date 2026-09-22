"""Reusable local shot index for silent footage."""
from pathlib import Path
import hashlib
import json
import subprocess

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi"}

def media_files(root: str):
    root = Path(root).expanduser().resolve()
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS)

def probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())

def detect_scenes(path: str):
    try:
        from scene_detection import detect_scenes as existing_detector
    except ImportError as exc:
        raise RuntimeError("scene_detection.py from OpenShorts/Story Lab is required") from exc
    scenes, fps = existing_detector(path)
    return [(float(a.get_seconds()), float(b.get_seconds())) for a, b in scenes], float(fps)

def shot_id(path: str, start: float, end: float) -> str:
    return hashlib.sha1(f"{Path(path).resolve()}|{start:.6f}|{end:.6f}".encode()).hexdigest()[:16]

def build_index(root: str, output: str, max_files: int | None = None):
    files = media_files(root)
    if max_files:
        files = files[:max_files]
    records = []
    for n, path in enumerate(files, 1):
        print(f"[{n}/{len(files)}] {path}")
        try:
            scenes, fps = detect_scenes(str(path))
        except Exception as exc:
            print(f"  ! scene detection failed: {exc}")
            duration = probe_duration(path)
            scenes, fps = [(0.0, duration)], 0.0
        for start, end in scenes:
            if end <= start:
                continue
            records.append({"id": shot_id(path, start, end), "video_path": str(path), "start": start, "end": end, "duration": end - start, "fps": fps, "description": "", "tags": []})
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps({"version": 1, "shots": records}, indent=2), encoding="utf-8")
    print(f"Indexed {len(files)} videos -> {len(records)} shots")
    return records
