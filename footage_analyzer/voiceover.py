"""Voiceover transcription for Footage Analyzer.

The voiceover is the master edit timeline.  Gemini 3.5 Transcribe is used
when available; local faster-whisper is a deterministic fallback.  This module
never leaves the job silently parked at 5%: every network operation has a
bounded timeout and a persisted progress heartbeat is emitted by the caller.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


def format_seconds(value: float | int | None) -> str:
    value = max(0.0, float(value or 0))
    minutes = int(value // 60)
    seconds = value - minutes * 60
    return f"{minutes:02d}:{seconds:04.1f}"


def _probe_duration(path: str | Path) -> float:
    """Read media duration quickly. Failure is non-fatal."""
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
            timeout=15,
        )
        return max(0.0, float(result.stdout.strip() or 0))
    except Exception:
        return 0.0


def _parse_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None

    text = str(value).strip().lower()
    if text.endswith("ms"):
        try:
            return float(text[:-2]) / 1000.0
        except ValueError:
            return None
    if text.endswith("s"):
        text = text[:-1].strip()

    parts = text.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(text)
    except (TypeError, ValueError):
        return None


def _plain(value: Any) -> Any:
    """Convert SDK/Pydantic objects into recursively walkable Python values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _plain(model_dump(mode="python"))
        except TypeError:
            try:
                return _plain(model_dump())
            except Exception:
                pass
        except Exception:
            pass

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _plain(to_dict())
        except Exception:
            pass

    if hasattr(value, "__dict__"):
        try:
            data = {k: v for k, v in vars(value).items() if not k.startswith("_")}
            # Attributes defined on the class (not the instance) are invisible to vars().
            for k in dir(value):
                if k.startswith("_") or k in data:
                    continue
                attr = getattr(value, k, None)
                if not callable(attr):
                    data[k] = attr
            return {k: _plain(v) for k, v in data.items()}
        except Exception:
            pass

    return value


def _extract_word_annotations(interaction: Any) -> list[dict]:
    """Extract Gemini word_info annotations from any SDK response shape."""
    root = _plain(interaction)
    words: list[dict] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            kind = str(value.get("type") or "").lower()
            if kind in {"word_info", "wordinfo", "word"}:
                text = str(value.get("text") or value.get("word") or "").strip()
                start = _parse_timestamp(
                    value.get("start_offset", value.get("start"))
                )
                end = _parse_timestamp(
                    value.get("end_offset", value.get("end"))
                )
                if text and start is not None and end is not None and end > start:
                    words.append({"word": text, "start": start, "end": end})
            for child in value.values():
                walk(child)
            return

        if isinstance(value, (list, tuple)):
            for child in value:
                walk(child)

    walk(root)

    # Some SDK versions expose the same annotation through multiple nested
    # representations. De-duplicate without losing ordering.
    unique: dict[tuple[str, float, float], dict] = {}
    for item in words:
        key = (item["word"], item["start"], item["end"])
        unique[key] = item

    result = list(unique.values())
    result.sort(key=lambda item: (item["start"], item["end"]))
    return result


def _words_to_segments(
    words: list[dict],
    max_duration: float = 8.0,
    max_words: int = 18,
) -> list[dict]:
    segments: list[dict] = []
    current: list[dict] = []

    for word in words:
        current.append(word)
        text = " ".join(item["word"] for item in current).strip()
        sentence_end = bool(re.search(r"[.!?][\"'”’)]*$", word["word"]))
        too_long = word["end"] - current[0]["start"] >= max_duration
        too_many = len(current) >= max_words

        if sentence_end or too_long or too_many:
            segments.append(
                {
                    "start": float(current[0]["start"]),
                    "end": float(current[-1]["end"]),
                    "text": text,
                    "words": current[:],
                }
            )
            current = []

    if current:
        segments.append(
            {
                "start": float(current[0]["start"]),
                "end": float(current[-1]["end"]),
                "text": " ".join(item["word"] for item in current).strip(),
                "words": current[:],
            }
        )

    return segments


def _normalise_segments(raw: list[dict] | None, duration: float) -> list[dict]:
    out: list[dict] = []

    for item in raw or []:
        if not isinstance(item, dict):
            continue

        text = str(item.get("text") or "").strip()
        start = _parse_timestamp(item.get("start"))
        end = _parse_timestamp(item.get("end"))
        if not text or start is None or end is None:
            continue

        start = max(0.0, float(start))
        end = min(float(duration or end), float(end))

        if end > start:
            out.append(
                {
                    "start": start,
                    "end": end,
                    "text": text,
                    "words": item.get("words", []) or [],
                }
            )

    out.sort(key=lambda item: (item["start"], item["end"]))

    cleaned: list[dict] = []
    for item in out:
        if cleaned and item["start"] < cleaned[-1]["end"]:
            item["start"] = cleaned[-1]["end"]
        if item["end"] > item["start"]:
            cleaned.append(item)

    return cleaned


def _load_model(model_name: str, device: str, compute_type: str, progress):
    """Load Whisper without making the UI look frozen."""
    progress(6, 0, f"🎙️ Loading local Whisper · {model_name}")

    result: dict[str, Any] = {"model": None, "error": None}

    def worker() -> None:
        try:
            from faster_whisper import WhisperModel

            cpu_threads = int(
                os.getenv(
                    "FOOTAGE_WHISPER_CPU_THREADS",
                    str(max(2, min(os.cpu_count() or 4, 8))),
                )
            )
            result["model"] = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                cpu_threads=cpu_threads,
            )
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(
        target=worker,
        daemon=True,
        name="footage-whisper-loader",
    )
    thread.start()

    heartbeat = 0
    while thread.is_alive():
        elapsed = heartbeat
        progress(
            min(9, 6 + heartbeat % 4),
            0,
            f"🎙️ Loading local Whisper · {model_name} · {elapsed}s",
        )
        heartbeat += 1
        thread.join(timeout=1.0)

    if result["error"] is not None:
        raise result["error"]
    if result["model"] is None:
        raise RuntimeError("Local Whisper failed to initialize.")

    progress(10, 0, f"🎙️ Local Whisper ready · {model_name}")
    return result["model"]


def _gemini_client():
    from google import genai

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is required for Gemini transcription.")
    return genai.Client(api_key=key)


def _upload_gemini_audio(client, path: str, progress, duration):
    """Upload with a watchdog so an SDK/network stall cannot freeze the job."""
    timeout_seconds = max(
        30, int(os.getenv("FOOTAGE_GEMINI_UPLOAD_TIMEOUT", "900"))
    )
    result: dict[str, Any] = {"file": None, "error": None}
    started = time.monotonic()

    progress(6, duration, f"☁️ Uploading voiceover · {Path(path).name}")

    def worker() -> None:
        try:
            result["file"] = client.files.upload(
                file=str(Path(path).expanduser().resolve())
            )
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(
        target=worker,
        daemon=True,
        name="footage-gemini-upload",
    )
    thread.start()

    while thread.is_alive():
        elapsed = int(time.monotonic() - started)
        if elapsed >= timeout_seconds:
            raise TimeoutError(
                f"Gemini voiceover upload exceeded {timeout_seconds}s."
            )

        # The SDK does not expose a portable upload-byte callback, so this is
        # intentionally a heartbeat rather than fake byte-level progress.
        progress(
            6 + (elapsed % 4),
            duration,
            f"☁️ Uploading voiceover · {Path(path).name} · {elapsed}s",
        )
        thread.join(timeout=1.0)

    if result["error"] is not None:
        raise result["error"]
    if result["file"] is None:
        raise RuntimeError("Gemini upload completed without returning a file.")

    progress(10, duration, f"☁️ Voiceover uploaded · {Path(path).name}")
    return result["file"]


def _create_gemini_interaction(client, uploaded, model_name):
    config = {
        "transcription_config": {
            "mode": {
                "type": "verbatim",
                "timestamp_granularities": ["word"],
            }
        }
    }

    # Background execution avoids keeping one HTTP request open while Gemini
    # transcribes. The current Python SDK supports background=True and polling
    # with interactions.get().
    try:
        return client.interactions.create(
            model=model_name,
            input=[
                {
                    "type": "audio",
                    "uri": uploaded.uri,
                    "mime_type": uploaded.mime_type,
                }
            ],
            generation_config=config,
            background=True,
            timeout=60,
        )
    except Exception:
        # Some API deployments/models can reject background execution even
        # though the SDK supports it. Fall back to a bounded synchronous call.
        return client.interactions.create(
            model=model_name,
            input=[
                {
                    "type": "audio",
                    "uri": uploaded.uri,
                    "mime_type": uploaded.mime_type,
                }
            ],
            generation_config=config,
            timeout=max(
                60,
                int(os.getenv("FOOTAGE_GEMINI_SYNC_TIMEOUT", "180")),
            ),
        )


def _interaction_status(interaction: Any) -> str:
    status = getattr(interaction, "status", "")
    value = getattr(status, "value", status)
    return str(value or "").strip().lower().split(".")[-1]


def _wait_for_gemini_interaction(
    client,
    interaction,
    progress,
    duration,
    filename: str,
):
    interaction_id = getattr(interaction, "id", None)
    status = _interaction_status(interaction)

    if not interaction_id or status in {"completed", "failed", "cancelled"}:
        return interaction

    timeout_seconds = max(
        60, int(os.getenv("FOOTAGE_GEMINI_TRANSCRIBE_TIMEOUT", "1800"))
    )
    started = time.monotonic()
    next_heartbeat = 0

    while True:
        elapsed = int(time.monotonic() - started)
        if elapsed >= timeout_seconds:
            try:
                client.interactions.cancel(
                    id=interaction_id,
                    timeout=30,
                )
            except Exception:
                pass
            raise TimeoutError(
                f"Gemini transcription exceeded {timeout_seconds}s."
            )

        status = str(getattr(interaction, "status", "") or "").lower()

        if status == "completed":
            progress(20, duration, f"☁️ Gemini transcription complete · {filename}")
            return interaction

        if status in {"failed", "cancelled"}:
            detail = getattr(interaction, "error", None)
            raise RuntimeError(
                f"Gemini transcription {status}: {detail or 'no additional error details'}"
            )

        progress(
            min(19, 11 + next_heartbeat % 9),
            duration,
            f"☁️ Gemini transcribing · {filename} · {elapsed}s",
        )
        next_heartbeat += 1

        interaction = client.interactions.get(
            id=interaction_id,
            timeout=30,
        )
        time.sleep(2.0)


def _gemini_transcribe(path: str, progress, duration: float) -> dict:
    client = _gemini_client()
    filename = Path(path).name
    model_name = os.getenv(
        "FOOTAGE_GEMINI_TRANSCRIBE_MODEL",
        "gemini-3.5-transcribe",
    )

    uploaded = _upload_gemini_audio(client, path, progress, duration)

    progress(
        10,
        duration,
        f"☁️ Starting Gemini transcription · {filename}",
    )

    interaction = _create_gemini_interaction(
        client,
        uploaded,
        model_name,
    )

    interaction = _wait_for_gemini_interaction(
        client,
        interaction,
        progress,
        duration,
        filename,
    )

    words = _extract_word_annotations(interaction)
    if not words:
        raise RuntimeError(
            "Gemini completed transcription but returned no word-level timestamps."
        )

    segments = _normalise_segments(
        _words_to_segments(words),
        duration,
    )
    if not segments:
        raise RuntimeError(
            "Gemini returned word timestamps but no usable transcript segments."
        )

    output_text = str(
        getattr(interaction, "output_text", "") or ""
    ).strip()
    if not output_text:
        output_text = " ".join(item["text"] for item in segments)

    return {
        "text": output_text,
        "language": "auto",
        "segments": segments,
        "duration": float(duration or segments[-1]["end"]),
        "provider": "gemini-3.5-transcribe",
    }


def _local_whisper_transcribe(
    path: str,
    progress,
    duration: float,
) -> dict:
    model_name = os.getenv("FOOTAGE_WHISPER_MODEL", "base")
    device = os.getenv("FOOTAGE_WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("FOOTAGE_WHISPER_COMPUTE", "int8")
    timeout_seconds = max(
        60, int(os.getenv("FOOTAGE_WHISPER_TIMEOUT", "7200"))
    )

    model = _load_model(
        model_name,
        device,
        compute_type,
        progress,
    )

    progress(10, duration, f"🎙️ Starting local transcription · {Path(path).name}")

    started = time.monotonic()
    segments, info = model.transcribe(
        str(Path(path).expanduser().resolve()),
        word_timestamps=True,
        vad_filter=True,
        beam_size=int(os.getenv("FOOTAGE_WHISPER_BEAM_SIZE", "1")),
        log_progress=False,
    )

    duration = float(getattr(info, "duration", 0) or duration or 0)
    output: list[dict] = []
    text: list[str] = []
    last_report = 0.0

    for segment in segments:
        if time.monotonic() - started >= timeout_seconds:
            raise TimeoutError(
                f"Local Whisper transcription exceeded {timeout_seconds}s."
            )

        end = float(segment.end)
        now = time.monotonic()
        pct = int(
            min(
                100,
                max(0, (end / duration * 100) if duration else 0),
            )
        )

        if now - last_report >= 0.25:
            progress(
                10 + int(10 * pct / 100),
                duration,
                f"🎙️ Transcribing audio · {format_seconds(end)} / {format_seconds(duration)}",
            )
            last_report = now

        segment_text = str(segment.text or "").strip()
        if not segment_text:
            continue

        words = []
        for word in segment.words or []:
            if word.start is None or word.end is None:
                continue
            words.append(
                {
                    "word": str(word.word),
                    "start": float(word.start),
                    "end": float(word.end),
                }
            )

        output.append(
            {
                "start": float(segment.start),
                "end": end,
                "text": segment_text,
                "words": words,
            }
        )
        text.append(segment_text)

    if not output:
        raise RuntimeError("Local Whisper did not detect any speech.")

    progress(
        20,
        duration,
        f"🎙️ Audio transcription complete · {Path(path).name}",
    )

    return {
        "text": " ".join(text),
        "language": getattr(info, "language", "auto"),
        "segments": output,
        "duration": duration,
        "provider": "faster-whisper",
    }


def transcribe(path: str, progress=None) -> dict:
    """Transcribe a voiceover with Gemini first and Whisper fallback."""
    emit = progress or (lambda *_args: None)
    filename = Path(path).name
    duration = _probe_duration(path)

    emit(5, duration, f"🎙️ Preparing audio · {filename}")

    requested = os.getenv("FOOTAGE_TRANSCRIBER", "gemini").strip().lower()

    # Gemini word timestamps have a documented 30-minute limitation. Route
    # longer files directly to Whisper instead of making a doomed API request.
    use_gemini = requested == "gemini" and 0 < duration <= 1800

    if use_gemini:
        try:
            emit(6, duration, f"☁️ Starting Gemini transcription · {filename}")
            return _gemini_transcribe(path, emit, duration)
        except Exception as exc:
            if os.getenv(
                "FOOTAGE_GEMINI_LOCAL_FALLBACK",
                "1",
            ).strip().lower() not in {"1", "true", "yes"}:
                raise

            emit(
                10,
                duration,
                f"☁️ Gemini transcription unavailable · switching to local Whisper · {type(exc).__name__}",
            )

    elif requested == "gemini" and duration > 1800:
        emit(
            10,
            duration,
            f"🎙️ Voiceover is {format_seconds(duration)} · local Whisper is required for this length",
        )

    return _local_whisper_transcribe(
        path,
        emit,
        duration,
    )


def sentence_segments(transcript: dict) -> list[dict]:
    return [
        {
            "index": index,
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": " ".join(str(segment["text"]).split()).strip(),
        }
        for index, segment in enumerate(transcript.get("segments", []))
        if str(segment.get("text", "")).strip()
    ]
