"""Persistent sampled-frame visual enrichment."""
from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

from PIL import Image

from .cache import atomic_json


def _json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.replace("```json", "", 1).replace("```", "").strip()
    try:
        return json.loads(text)
    except Exception:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise ValueError("Gemini did not return valid JSON")


def sample_frames(path, start, end, count=4):
    duration = max(0.01, float(end) - float(start))
    frames = []
    for i in range(count):
        t = float(start) + duration * ((i + 0.5) / count)
        p = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-loglevel", "error",
                "-ss", str(t), "-i", path,
                "-frames:v", "1", "-vf", "scale=640:-1",
                "-f", "image2pipe", "-vcodec", "png", "pipe:1",
            ],
            capture_output=True,
            check=True,
            timeout=90,
        )
        if not p.stdout:
            raise RuntimeError(f"ffmpeg produced no frame at {t:.2f}s")
        frames.append(Image.open(BytesIO(p.stdout)).convert("RGB"))

    w = max(x.width for x in frames)
    h = max(x.height for x in frames)
    sheet = Image.new("RGB", (w * 2, h * ((len(frames) + 1) // 2)), "white")
    for i, im in enumerate(frames):
        sheet.paste(im, ((i % 2) * w, (i // 2) * h))
    return sheet


FIELDS = ("subjects", "actions", "setting", "visual_style", "text_visible", "tags")


def _clean(data):
    data = dict(data or {})
    for key_name in FIELDS:
        value = data.get(key_name, [])
        data[key_name] = value if isinstance(value, list) else [str(value)]
    data["description"] = str(data.get("description", "")).strip()
    if not data["description"]:
        raise ValueError("Gemini returned an empty visual description")
    return data


def describe_shots(shots):
    """Describe several shots in one Gemini request (one contact sheet per shot).

    Batching matters: free-tier keys allow ~20 requests per model per day, and a
    library has thousands of shots.
    """
    from . import gemini

    frame_count = int(os.getenv("FOOTAGE_VISUAL_FRAME_COUNT", "4"))
    contents = [
        "Each image below is a contact sheet of frames sampled from one footage shot, labelled "
        "with its shot_id. Inspect every panel. Return ONLY valid JSON: {\"shots\": [{\"shot_id\", "
        "\"description\", \"subjects\", \"actions\", \"setting\", \"visual_style\", \"text_visible\", "
        "\"tags\"}]} with one entry per shot_id. Describe only visible evidence. Do not infer "
        "identity, date, event, location, historical facts, or anything not visible. Use short "
        "concrete phrases; lists for everything except description."
    ]
    for shot in shots:
        contents.append(f"shot_id: {shot['id']}")
        contents.append(sample_frames(shot["video_path"], shot["start"], shot["end"], count=frame_count))

    data = _json(gemini.generate("vision", contents))
    entries = data.get("shots", []) if isinstance(data, dict) else data
    by_id = {str(e.get("shot_id")): e for e in entries or [] if isinstance(e, dict)}
    results = {}
    for shot in shots:
        try:
            results[shot["id"]] = _clean(by_id.get(shot["id"]))
        except Exception as exc:
            results[shot["id"]] = exc
    return results


def describe_shot(path, start, end):
    result = describe_shots([{"id": "shot", "video_path": path, "start": start, "end": end}])["shot"]
    if isinstance(result, Exception):
        raise result
    return result


def enrich_index(index_path, output_path, progress=None, limit=None):
    data = json.loads(Path(index_path).read_text(encoding="utf-8"))
    output = Path(output_path)
    manifest_path = output.with_name("visual_manifest.json")

    old = {}
    if output.exists():
        try:
            old = {
                s["id"]: s
                for s in json.loads(output.read_text(encoding="utf-8")).get("shots", [])
                if s.get("id")
            }
        except Exception:
            old = {}

    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

    shots = data.get("shots", [])
    work = shots[:limit] if limit is not None else shots
    total = len(work)
    done = 0
    reused = 0
    failed = 0
    pending = []

    for shot in work:
        sid = shot["id"]
        existing = old.get(sid, {})
        if existing.get("description"):
            shot.update(existing)
            reused += 1
            done += 1
            if progress:
                name = Path(shot["video_path"]).name
                progress(
                    done, total,
                    f"{name} · {shot['start']:.1f}–{shot['end']:.1f}s",
                    {"reused": reused, "failed": failed},
                )
        else:
            manifest[sid] = {
                "status": "processing",
                "video_path": shot["video_path"],
                "start": shot["start"],
                "end": shot["end"],
            }
            pending.append(shot)

    atomic_json(manifest_path, manifest)

    workers = max(1, min(int(os.getenv("FOOTAGE_VISUAL_WORKERS", "2")), 4))

    size = max(1, int(os.getenv("FOOTAGE_VISUAL_BATCH", "8")))
    batches = [pending[i:i + size] for i in range(0, len(pending), size)]

    def analyze(batch):
        try:
            return describe_shots(batch)
        except Exception as exc:
            return {shot["id"]: exc for shot in batch}

    if batches:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="visual-shot") as pool:
            futures = {pool.submit(analyze, batch): batch for batch in batches}
            for future in as_completed(futures):
                batch = futures[future]
                results = future.result()
                for shot in batch:
                    sid = shot["id"]
                    outcome = results.get(sid)
                    entry = {"video_path": shot["video_path"], "start": shot["start"], "end": shot["end"]}
                    if isinstance(outcome, dict):
                        shot.update(outcome)
                        manifest[sid] = {"status": "complete", **entry}
                    else:
                        failed += 1
                        manifest[sid] = {"status": "failed", **entry, "error": str(outcome)[:500]}
                    done += 1

                atomic_json(manifest_path, manifest)
                data["shots"] = shots
                data["version"] = 5
                atomic_json(output, data)

                if progress:
                    last = batch[-1]
                    progress(
                        done, total,
                        f"{Path(last['video_path']).name} · {len(batch)} shots per request",
                        {"reused": reused, "failed": failed},
                    )

    by_id = {s["id"]: s for s in data.get("shots", [])}
    for sid, s in old.items():
        if s.get("description"):
            by_id.setdefault(sid, s)

    data["shots"] = list(by_id.values())
    data["version"] = 5
    atomic_json(output, data)
    return data
