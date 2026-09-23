"""Independent voiceover transcription backend.

The analyzer treats the selected voiceover as the master timeline.  This module
keeps transcription visibly alive while the Whisper model is downloading/loading
and while audio is being decoded, instead of leaving the UI at 5% with no
explanation.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path


def _probe_duration(path):
    """Return audio duration without requiring Whisper to be loaded."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(Path(path).expanduser().resolve()),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return max(0.0, float(result.stdout.strip() or 0))
    except Exception:
        return 0.0


def _load_model(model_name, device, compute_type, progress):
    """Load Whisper in a background thread so import/download/load is observable."""
    # Importing faster-whisper/CTranslate2 can itself take noticeable time in a
    # cold Docker container, so never leave the UI at 5% during that import.
    progress(6, 0, f"🎙️ Loading Whisper runtime · {model_name}")
    started = time.monotonic()
    result = {"model": None, "error": None}

    def worker():
        try:
            from faster_whisper import WhisperModel
            cpu_threads = int(os.getenv("FOOTAGE_WHISPER_CPU_THREADS", str(max(2, min(os.cpu_count() or 4, 8)))))
            result["model"] = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                cpu_threads=cpu_threads,
            )
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=worker, daemon=True, name="whisper-model-loader")
    thread.start()

    heartbeat = 0
    while thread.is_alive():
        elapsed = int(time.monotonic() - started)
        progress(min(9, 6 + heartbeat % 4), 0,
                 f"🎙️ Loading Whisper model · {model_name} · {elapsed}s")
        heartbeat += 1
        thread.join(timeout=1.0)

    if result["error"] is not None:
        raise result["error"]
    if result["model"] is None:
        raise RuntimeError("Whisper model failed to load.")
    progress(10, 0, f"🎙️ Whisper model ready · {model_name}")
    return result["model"]

def transcribe(path, progress=None):
    model_name = os.getenv("FOOTAGE_WHISPER_MODEL", "base")
    device = os.getenv("FOOTAGE_WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("FOOTAGE_WHISPER_COMPUTE", "int8")
    duration = _probe_duration(path)

    def report(pct, message):
        if progress:
            progress(pct, duration, message)

    report(5, f"🎙️ Preparing audio · {Path(path).name}")
    model = _load_model(model_name, device, compute_type, progress)

    report(10, f"🎙️ Starting transcription · {Path(path).name}")
    # faster-whisper returns a lazy segment generator. The real inference happens
    # while iterating it, so progress must be emitted from inside this loop.
    segments, info = model.transcribe(
        str(Path(path).expanduser().resolve()),
        word_timestamps=True,
        vad_filter=True,
        beam_size=int(os.getenv("FOOTAGE_WHISPER_BEAM_SIZE", "1")),
        log_progress=False,
    )

    duration = float(getattr(info, "duration", 0) or duration or 0)
    out = []
    text = []
    last_report = 0.0

    for s in segments:
        now = time.monotonic()
        end = float(s.end)
        pct = int(min(100, max(0, (end / duration * 100) if duration else 10)))

        # Report every segment, and make sure long gaps between speech segments
        # still result in a useful visible update when the next segment arrives.
        if progress and (now - last_report >= 0.25 or pct >= 100):
            progress(
                10 + int(10 * pct / 100),
                duration,
                f"🎙️ Transcribing audio · {format_seconds(end)} / {format_seconds(duration)}",
            )
            last_report = now

        t = str(s.text).strip()
        if not t:
            continue

        out.append(
            {
                "start": float(s.start),
                "end": end,
                "text": t,
                "words": [
                    {
                        "word": w.word,
                        "start": float(w.start),
                        "end": float(w.end),
                    }
                    for w in (s.words or [])
                ],
            }
        )
        text.append(t)

    report(20, f"🎙️ Audio transcription complete · {Path(path).name}")
    return {
        "text": " ".join(text),
        "language": getattr(info, "language", "en"),
        "segments": out,
        "duration": duration,
    }


def format_seconds(value):
    value = max(0.0, float(value or 0))
    minutes = int(value // 60)
    seconds = value - minutes * 60
    return f"{minutes:02d}:{seconds:04.1f}"


def sentence_segments(transcript):
    return [
        {
            "index": i,
            "start": float(s["start"]),
            "end": float(s["end"]),
            "text": " ".join(str(s["text"]).split()).strip(),
        }
        for i, s in enumerate(transcript.get("segments", []))
        if str(s.get("text", "")).strip()
    ]
