"""Independent voiceover transcription backend.

The analyzer treats the selected voiceover as the master timeline.  This module
keeps transcription visibly alive while the Whisper model is downloading/loading
and while audio is being decoded, instead of leaving the UI at 5% with no
explanation.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path
import json


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

def _parse_json(text):
    text=(text or "").strip()
    if text.startswith("```"):
        text=text.replace("```json","",1).replace("```","").strip()
    try: return json.loads(text)
    except Exception:
        left=text.find("{"); right=text.rfind("}")
        if left>=0 and right>left: return json.loads(text[left:right+1])
        left=text.find("["); right=text.rfind("]")
        if left>=0 and right>left: return json.loads(text[left:right+1])
        raise ValueError("Transcription service returned non-JSON output")

def _parse_timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    s = str(value).strip().lower()
    if s.endswith("ms"):
        try:
            return float(s[:-2]) / 1000.0
        except ValueError:
            return None
    if s.endswith("s"):
        s = s[:-1].strip()
    parts = s.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(s)
    except (TypeError, ValueError):
        return None


def _extract_word_annotations(interaction):
    words = []
    for step in getattr(interaction, "steps", []) or []:
        for content in getattr(step, "content", []) or []:
            for annotation in getattr(content, "annotations", []) or []:
                if getattr(annotation, "type", None) != "word_info":
                    continue
                text = str(getattr(annotation, "text", "") or "").strip()
                start = _parse_timestamp(getattr(annotation, "start_offset", None))
                end = _parse_timestamp(getattr(annotation, "end_offset", None))
                if text and start is not None and end is not None and end > start:
                    words.append({"word": text, "start": start, "end": end})
    words.sort(key=lambda item: (item["start"], item["end"]))
    return words


def _words_to_segments(words, max_duration=8.0, max_words=18):
    segments = []
    current = []
    for word in words:
        current.append(word)
        text = " ".join(x["word"] for x in current).strip()
        sentence_end = bool(re.search(r"[.!?][\"'”’)]*$", word["word"]))
        too_long = word["end"] - current[0]["start"] >= max_duration
        too_many = len(current) >= max_words
        if sentence_end or too_long or too_many:
            segments.append({
                "start": float(current[0]["start"]),
                "end": float(current[-1]["end"]),
                "text": text,
                "words": current[:],
            })
            current = []
    if current:
        segments.append({
            "start": float(current[0]["start"]),
            "end": float(current[-1]["end"]),
            "text": " ".join(x["word"] for x in current).strip(),
            "words": current[:],
        })
    return segments


def _normalise_segments(raw, duration):
    out = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        start = _parse_timestamp(item.get("start"))
        end = _parse_timestamp(item.get("end"))
        if not text or start is None or end is None:
            continue
        start = max(0.0, float(start))
        end = min(float(duration or end), float(end))
        if end > start:
            out.append({"start": start, "end": end, "text": text, "words": item.get("words", []) or []})
    out.sort(key=lambda item: (item["start"], item["end"]))
    cleaned = []
    for item in out:
        if cleaned and item["start"] < cleaned[-1]["end"]:
            item["start"] = cleaned[-1]["end"]
        if item["end"] > item["start"]:
            cleaned.append(item)
    return cleaned


def _generic_audio_json(client, uploaded, model_name):
    prompt = (
        "Transcribe this voiceover verbatim. Return ONLY valid JSON with a segments array. "
        "Each segment must have numeric start and end timestamps in seconds and text. "
        "Use natural spoken phrase/sentence boundaries. Do not summarize, translate, rewrite, "
        "or invent words."
    )
    response = client.models.generate_content(
        model=model_name,
        contents=[prompt, uploaded],
        config={"response_mime_type": "application/json"},
    )
    data = _parse_json(getattr(response, "text", ""))
    raw = data.get("segments", []) if isinstance(data, dict) else data
    return raw, str(data.get("language", "auto")) if isinstance(data, dict) else "auto"


def _gemini_transcribe(path, progress, duration):
    from google import genai

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is required for Gemini transcription.")

    model_name = os.getenv("FOOTAGE_GEMINI_TRANSCRIBE_MODEL", "gemini-3.5-transcribe")
    fallback = os.getenv("FOOTAGE_GEMINI_TRANSCRIBE_FALLBACK_MODEL", "gemini-3.8-flash")
    client = genai.Client(api_key=key)
    uploaded_result = {"file": None, "error": None}
    upload_started = time.monotonic()

    progress(6, duration, f"☁️ Uploading voiceover to Gemini · {Path(path).name}")

    def upload():
        try:
            uploaded_result["file"] = client.files.upload(file=str(Path(path).resolve()))
        except Exception as exc:
            uploaded_result["error"] = exc

    thread = threading.Thread(target=upload, daemon=True, name="gemini-audio-upload")
    thread.start()
    heartbeat = 0
    while thread.is_alive():
        elapsed = int(time.monotonic() - upload_started)
        progress(min(9, 6 + heartbeat % 4), duration,
                 f"☁️ Uploading voiceover to Gemini · {Path(path).name} · {elapsed}s")
        heartbeat += 1
        thread.join(timeout=1.0)
    if uploaded_result["error"] is not None:
        raise uploaded_result["error"]
    uploaded = uploaded_result["file"]
    progress(9, duration, f"☁️ Voiceover uploaded · Gemini is transcribing · {Path(path).name}")

    # Gemini 3.5 Transcribe provides word-level timestamps through the
    # Interactions API. This is the supported dedicated transcription path;
    # the old generate_content/audio_transcription_config combination is not.
    result = {}
    error = {}

    def call_transcriber():
        try:
            result["interaction"] = client.interactions.create(
                model=model_name,
                input=[{
                    "type": "audio",
                    "uri": uploaded.uri,
                    "mime_type": uploaded.mime_type,
                }],
                generation_config={
                    "transcription_config": {
                        "mode": {
                            "type": "verbatim",
                            "timestamp_granularities": ["word"],
                        }
                    }
                },
            )
        except Exception as exc:
            error["error"] = exc

    started = time.monotonic()
    thread = threading.Thread(target=call_transcriber, daemon=True, name="gemini-transcription")
    thread.start()
    heartbeat = 0
    while thread.is_alive():
        elapsed = int(time.monotonic() - started)
        progress(min(18, 10 + heartbeat % 9), duration,
                 f"☁️ Gemini transcribing · {Path(path).name} · {elapsed}s")
        heartbeat += 1
        thread.join(timeout=1.0)

    if "error" not in error:
        interaction = result.get("interaction")
        words = _extract_word_annotations(interaction)
        if words:
            segments = _words_to_segments(words)
            if segments:
                language = "auto"
                progress(20, duration, f"☁️ Gemini transcription complete · {len(segments)} segments")
                return {
                    "text": str(getattr(interaction, "output_text", "") or " ".join(s["text"] for s in segments)),
                    "language": language,
                    "segments": _normalise_segments(segments, duration),
                    "duration": duration,
                }

        # A completed interaction without word annotations is not sufficient
        # for a voiceover-master edit. Fall through to the timestamped JSON
        # fallback rather than fabricating timing.
        error["error"] = ValueError("Gemini Transcribe returned no word timestamp annotations.")

    # Generic Gemini audio fallback. It is useful when the dedicated
    # transcription endpoint is temporarily unavailable, while still requiring
    # explicit timestamps in the model output.
    if fallback:
        progress(10, duration, f"☁️ Gemini Transcribe unavailable · trying {fallback}")
        result.clear()
        error.clear()
        started = time.monotonic()

        def call_fallback():
            try:
                raw, language = _generic_audio_json(client, uploaded, fallback)
                result["raw"] = raw
                result["language"] = language
            except Exception as exc:
                error["error"] = exc

        thread = threading.Thread(target=call_fallback, daemon=True, name="gemini-audio-fallback")
        thread.start()
        heartbeat = 0
        while thread.is_alive():
            elapsed = int(time.monotonic() - started)
            progress(min(19, 10 + heartbeat % 10), duration,
                     f"☁️ Gemini fallback transcription · {Path(path).name} · {elapsed}s")
            heartbeat += 1
            thread.join(timeout=1.0)

        if "error" not in error:
            segments = _normalise_segments(result.get("raw"), duration)
            if segments:
                progress(20, duration, f"☁️ Gemini fallback transcription complete · {len(segments)} segments")
                return {
                    "text": " ".join(s["text"] for s in segments),
                    "language": result.get("language", "auto"),
                    "segments": segments,
                    "duration": duration,
                }

    raise RuntimeError(
        f"Gemini transcription failed: {error.get('error') or 'no timestamped transcript returned'}"
    )


def transcribe(path, progress=None):
    model_name=os.getenv("FOOTAGE_WHISPER_MODEL","base")
    device=os.getenv("FOOTAGE_WHISPER_DEVICE","cpu")
    compute_type=os.getenv("FOOTAGE_WHISPER_COMPUTE","int8")
    duration=_probe_duration(path)
    def report(pct,message):
        if progress: progress(pct,duration,message)
    report(5,f"🎙️ Preparing audio · {Path(path).name}")

    # Gemini is the reliable default for this desktop workflow: the same API key
    # already used for visual analysis can transcribe the uploaded voiceover,
    # including timestamps, without downloading a Whisper model into Docker.
    if os.getenv("FOOTAGE_TRANSCRIBER","gemini").lower()=="gemini":
        try:
            return _gemini_transcribe(path, progress, duration)
        except Exception as exc:
            if os.getenv("FOOTAGE_GEMINI_LOCAL_FALLBACK", "1").lower() not in {"1", "true", "yes"}:
                raise
            report(10, f"☁️ Gemini transcription unavailable · local Whisper fallback · {type(exc).__name__}")
    
    model=_load_model(model_name,device,compute_type,progress)
    report(10,f"🎙️ Starting transcription · {Path(path).name}")
    segments,info=model.transcribe(
        str(Path(path).expanduser().resolve()),
        word_timestamps=True,
        vad_filter=True,
        beam_size=int(os.getenv("FOOTAGE_WHISPER_BEAM_SIZE","1")),
        log_progress=False,
    )
    duration=float(getattr(info,"duration",0) or duration or 0)
    out=[]; text=[]; last_report=0.0
    for s in segments:
        now=time.monotonic(); end=float(s.end)
        pct=int(min(100,max(0,(end/duration*100) if duration else 10)))
        if progress and (now-last_report>=0.25 or pct>=100):
            progress(10+int(10*pct/100),duration,
                     f"🎙️ Transcribing audio · {format_seconds(end)} / {format_seconds(duration)}")
            last_report=now
        t=str(s.text).strip()
        if not t: continue
        out.append({"start":float(s.start),"end":end,"text":t,"words":[
            {"word":w.word,"start":float(w.start),"end":float(w.end)} for w in (s.words or [])
        ]})
        text.append(t)
    report(20,f"🎙️ Audio transcription complete · {Path(path).name}")
    return {"text":" ".join(text),"language":getattr(info,"language","en"),"segments":out,"duration":duration}
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
