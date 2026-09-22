"""Independent voiceover transcription backend."""
from pathlib import Path
import os
def transcribe(path):
    from faster_whisper import WhisperModel
    model=WhisperModel(os.getenv("FOOTAGE_WHISPER_MODEL","small"),device=os.getenv("FOOTAGE_WHISPER_DEVICE","cpu"),compute_type=os.getenv("FOOTAGE_WHISPER_COMPUTE","int8"))
    segments,info=model.transcribe(str(Path(path).expanduser().resolve()),word_timestamps=True,vad_filter=True)
    out=[]; text=[]
    for s in segments:
        t=str(s.text).strip()
        if not t: continue
        out.append({"start":float(s.start),"end":float(s.end),"text":t,"words":[{"word":w.word,"start":float(w.start),"end":float(w.end)} for w in (s.words or [])]})
        text.append(t)
    return {"text":" ".join(text),"language":getattr(info,"language","en"),"segments":out}
def sentence_segments(transcript):
    return [{"index":i,"start":float(s["start"]),"end":float(s["end"]),"text":" ".join(str(s["text"]).split()).strip()} for i,s in enumerate(transcript.get("segments",[])) if str(s.get("text","")).strip()]
