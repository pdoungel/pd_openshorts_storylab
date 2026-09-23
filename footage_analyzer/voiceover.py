"""Independent voiceover transcription backend."""
from pathlib import Path
import os
def transcribe(path, progress=None):
    from faster_whisper import WhisperModel
    model=WhisperModel(os.getenv("FOOTAGE_WHISPER_MODEL","small"),device=os.getenv("FOOTAGE_WHISPER_DEVICE","cpu"),compute_type=os.getenv("FOOTAGE_WHISPER_COMPUTE","int8"))
    segments,info=model.transcribe(str(Path(path).expanduser().resolve()),word_timestamps=True,vad_filter=True)
    if progress:
        progress(0, 0, "🎙️ Whisper model loaded — transcribing audio…")
    out=[]; text=[]
    duration=float(getattr(info, "duration", 0) or 0)
    for s in segments:
        t=str(s.text).strip()
        if progress:
            pct=int(min(100, max(0, (float(s.end) / duration * 100) if duration else 0)))
            progress(pct, duration, f"🎙️ Transcribing audio · {format_seconds(float(s.end))} / {format_seconds(duration)}")
        if not t: continue
        out.append({"start":float(s.start),"end":float(s.end),"text":t,"words":[{"word":w.word,"start":float(w.start),"end":float(w.end)} for w in (s.words or [])]})
        text.append(t)
    if progress:
        progress(100, duration, "🎙️ Audio transcription complete")
    return {"text":" ".join(text),"language":getattr(info,"language","en"),"segments":out}

def format_seconds(value):
    value=max(0.0,float(value or 0))
    minutes=int(value//60)
    seconds=value-minutes*60
    return f"{minutes:02d}:{seconds:04.1f}"
def sentence_segments(transcript):
    return [{"index":i,"start":float(s["start"]),"end":float(s["end"]),"text":" ".join(str(s["text"]).split()).strip()} for i,s in enumerate(transcript.get("segments",[])) if str(s.get("text","")).strip()]
