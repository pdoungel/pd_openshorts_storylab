"""Voiceover-first timeline extraction."""
from pathlib import Path
import json

def transcribe(path: str, local_only: bool = True) -> dict:
    p = str(Path(path).expanduser().resolve())
    try:
        from transcribe_backends import transcribe_media_local, transcribe_media
    except ImportError as exc:
        raise RuntimeError("Run footage_analyzer from the OpenShorts/Story Lab checkout.") from exc
    return transcribe_media_local(p) if local_only else transcribe_media(p)

def sentence_segments(transcript: dict) -> list[dict]:
    result = []
    for seg in transcript.get("segments", []):
        text = " ".join(str(seg.get("text", "")).split()).strip()
        if not text:
            continue
        result.append({"index": len(result), "start": float(seg["start"]), "end": float(seg["end"]), "text": text})
    return result

def save_transcript(transcript: dict, output: str):
    Path(output).write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
