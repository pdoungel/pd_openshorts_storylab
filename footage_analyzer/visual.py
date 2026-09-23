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


def describe_shot(path, start, end):
    from google import genai

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY.")

    sheet = sample_frames(path, start, end, count=int(os.getenv("FOOTAGE_VISUAL_FRAME_COUNT", "4")))
    prompt = (
        "Inspect every panel in this footage contact sheet. Return ONLY valid JSON with "
        "description, subjects, actions, setting, visual_style, text_visible, tags. "
        "Describe only visible evidence. Do not infer identity, date, event, location, "
        "historical facts, or anything not visible. Use short concrete phrases."
    )

    max_attempts = max(1, int(os.getenv("FOOTAGE_VISUAL_RETRIES", "3")))
    last_error = None
    for attempt in range(max_attempts):
        try:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=os.getenv("FOOTAGE_VISION_MODEL", "gemini-2.5-flash"),
                contents=[prompt, sheet],
            )
            data = _json(getattr(response, "text", ""))
            break
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            transient = (
                "429" in message or "rate" in message or "503" in message
                or "502" in message or "500" in message
                or "timeout" in message or "temporar" in message
                or "client has been closed" in message
            )
            if attempt + 1 >= max_attempts or not transient:
                raise
            time.sleep(min(8.0, 1.5 * (2 ** attempt)))
    else:
        raise last_error

    for key_name in ("subjects", "actions", "setting", "visual_style", "text_visible", "tags"):
        value = data.get(key_name, [])
        data[key_name] = value if isinstance(value, list) else [str(value)]

    data["description"] = str(data.get("description", "")).strip()
    if not data["description"]:
        raise ValueError("Gemini returned an empty visual description")
    return data


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

    def analyze(shot):
        return describe_shot(shot["video_path"], shot["start"], shot["end"])

    if pending:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="visual-shot") as pool:
            futures = {pool.submit(analyze, shot): shot for shot in pending}
            for future in as_completed(futures):
                shot = futures[future]
                sid = shot["id"]
                try:
                    shot.update(future.result())
                    manifest[sid] = {
                        "status": "complete",
                        "video_path": shot["video_path"],
                        "start": shot["start"],
                        "end": shot["end"],
                    }
                except Exception as exc:
                    failed += 1
                    manifest[sid] = {
                        "status": "failed",
                        "video_path": shot["video_path"],
                        "start": shot["start"],
                        "end": shot["end"],
                        "error": str(exc),
                    }

                done += 1
                atomic_json(manifest_path, manifest)
                data["shots"] = shots
                data["version"] = 5
                atomic_json(output, data)

                if progress:
                    name = Path(shot["video_path"]).name
                    progress(
                        done, total,
                        f"{name} · {shot['start']:.1f}–{shot['end']:.1f}s",
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
