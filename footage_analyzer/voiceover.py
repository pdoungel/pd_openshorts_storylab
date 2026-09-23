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
    if isinstance(value,(int,float)): return float(value)
    s=str(value or "").strip()
    parts=s.split(":")
    try:
        if len(parts)==3: return int(parts[0])*3600+int(parts[1])*60+float(parts[2])
        if len(parts)==2: return int(parts[0])*60+float(parts[1])
        return float(s)
    except Exception: return None

def _gemini_transcribe(path, progress, duration):
    from google import genai
    from google.genai import types
    key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key: raise RuntimeError("GEMINI_API_KEY is required for Gemini transcription.")
    model_name=os.getenv("FOOTAGE_GEMINI_TRANSCRIBE_MODEL","gemini-3.5-transcribe")
    progress(6,duration,f"☁️ Uploading voiceover to Gemini Transcribe · {Path(path).name}")
    client=genai.Client(api_key=key)
    uploaded=client.files.upload(file=str(Path(path).resolve()))
    progress(9,duration,f"☁️ Voiceover uploaded · Gemini is transcribing · {Path(path).name}")
    config=types.GenerateContentConfig(
        audio_transcription_config=types.AudioTranscriptionConfig(
            word_timestamp=True,
        )
    )
    prompt=(
        "Transcribe this voiceover verbatim. Return ONLY valid JSON. "
        "Use this exact shape: {\"language\":\"en\",\"segments\":[{\"start\":0.0,\"end\":2.5,\"text\":\"...\"}]}."
        " Timestamps must be seconds from the beginning of the audio. "
        "Create one segment for each natural spoken phrase/sentence. "
        "Do not summarize, translate, rewrite, or invent words. Preserve the spoken language."
    )
    started=time.monotonic()
    result={}
    error={}
    def call():
        try:
            response=client.models.generate_content(model=model_name,contents=[uploaded,prompt],config=config)
            result["response"]=response
        except Exception as exc: error["error"]=exc
    thread=threading.Thread(target=call,daemon=True,name="gemini-transcription")
    thread.start()
    heartbeat=0
    while thread.is_alive():
        elapsed=int(time.monotonic()-started)
        progress(min(19,10+heartbeat%10),duration,
                 f"☁️ Gemini transcribing · {Path(path).name} · {elapsed}s")
        heartbeat+=1
        thread.join(timeout=1.0)
    if "error" in error: raise error["error"]
    response=result.get("response")
    if response is None: raise RuntimeError("Gemini transcription returned no response.")
    data=_parse_json(getattr(response,"text",""))
    raw=data.get("segments",[]) if isinstance(data,dict) else data
    if not isinstance(raw,list): raise ValueError("Gemini transcription JSON has no segments list.")
    out=[]; full=[]
    for item in raw:
        text=str(item.get("text","")).strip() if isinstance(item,dict) else ""
        start=_parse_timestamp(item.get("start")) if isinstance(item,dict) else None
        end=_parse_timestamp(item.get("end")) if isinstance(item,dict) else None
        if not text or start is None or end is None or end<=start: continue
        out.append({"start":start,"end":end,"text":text,"words":[]})
        full.append(text)
    if not out: raise ValueError("Gemini returned no usable timestamped speech segments.")
    progress(20,duration,f"☁️ Gemini transcription complete · {len(out)} segments")
    return {"text":" ".join(full),"language":str(data.get("language","auto")) if isinstance(data,dict) else "auto","segments":out,"duration":duration}

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
        return _gemini_transcribe(path,progress,duration)

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
