"""Render an EDL plus its voiceover into a finished long-form MP4."""
from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}


def _size(aspect):
    if aspect not in SIZES:
        raise ValueError(f"Unsupported aspect {aspect}; use one of {', '.join(SIZES)}")
    return SIZES[aspect]


def _frame_filter(w, h, fit):
    if fit == "crop":
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    if fit == "pad":
        return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
    # Whole frame stays visible (screen text is never cropped); a blurred copy fills the rest.
    return (
        f"split[bgsrc][fgsrc];"
        f"[bgsrc]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=24:2,eq=brightness=-0.06[bg];"
        f"[fgsrc]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )


def timeline_spans(clips, total_duration):
    """Turn EDL clips into back-to-back spans covering 0..total_duration.

    Pauses between narration lines have no clip of their own, so the shot before
    a pause holds until the next line begins, and the first shot starts at 0.
    """
    ordered = sorted(clips, key=lambda c: float(c["timeline_start"]))
    spans = []
    for i, clip in enumerate(ordered):
        start = 0.0 if i == 0 else float(clip["timeline_start"])
        end = float(ordered[i + 1]["timeline_start"]) if i + 1 < len(ordered) else max(
            float(total_duration), float(clip["timeline_end"])
        )
        if end - start > 0.02:
            spans.append({"clip": clip, "start": start, "duration": end - start})
    return spans


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr.strip()[-600:]}")


def _encode_span(span, out, w, h, fps, fit):
    clip = span["clip"]
    frames = span["frames"]
    d = frames / fps
    vf = f"{_frame_filter(w, h, fit)},setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration={d:.3f}"
    _run([
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-ss", f"{float(clip['source_start']):.3f}", "-i", clip["source_path"],
        "-vf", vf, "-frames:v", str(frames), "-an",
        "-c:v", "libx264", "-preset", os.getenv("FOOTAGE_RENDER_PRESET", "veryfast"),
        "-crf", "20", "-pix_fmt", "yuv420p", "-video_track_timescale", "90000",
        str(out),
    ])


def render(result, voiceover_path, out_path, progress=None, aspect="16:9", fit="blur"):
    spans = timeline_spans(result["clips"], result.get("voiceover_duration", 0))
    if not spans:
        raise RuntimeError("Nothing to render: the EDL has no clips.")
    out = Path(out_path)
    parts_dir = out.parent / "render_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    w, h = _size(aspect)
    fps = int(os.getenv("FOOTAGE_RENDER_FPS", "30"))
    # Frame counts come from the absolute timeline so per-span rounding cannot drift from the audio.
    for s in spans:
        s["frames"] = round((s["start"] + s["duration"]) * fps) - round(s["start"] * fps)
    spans = [s for s in spans if s["frames"] > 0]
    parts = [parts_dir / f"{i:05d}.mp4" for i in range(len(spans))]

    done = 0
    workers = max(1, int(os.getenv("FOOTAGE_RENDER_WORKERS", "3")))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_encode_span, s, p, w, h, fps, fit) for s, p in zip(spans, parts)]
        for f in futures:
            f.result()
            done += 1
            if progress:
                progress(done, len(spans))

    concat = parts_dir / "concat.txt"
    concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    silent = parts_dir / "video.mp4"
    _run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
          "-i", str(concat), "-c", "copy", str(silent)])
    _run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(voiceover_path),
          "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
          "-shortest", "-movflags", "+faststart", str(out)])

    for p in parts_dir.iterdir():
        p.unlink()
    parts_dir.rmdir()
    return {"path": str(out), "spans": len(spans), "width": w, "height": h, "fps": fps, "aspect": aspect, "fit": fit}
