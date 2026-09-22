"""Transparent baseline matcher and EDL builder."""
import re
STOP = {"the","a","an","and","or","to","of","in","on","for","with","from","that","this","is","was","are","were","it","its","as","by","at","be","has","have","had","into","their","they","we","our"}

def terms(text):
    return {x for x in re.findall(r"[a-z0-9]{3,}", text.lower()) if x not in STOP}

def score_shot(narration, shot):
    a = terms(narration.get("text", ""))
    b = terms((shot.get("description", "") + " " + " ".join(shot.get("tags", []))))
    lexical = len(a & b) / max(1, len(a))
    target = float(narration["end"]) - float(narration["start"])
    duration = float(shot.get("duration", 0))
    duration_fit = min(duration / max(target, 0.1), 1.0) if duration else 0.0
    return 0.7 * lexical + 0.3 * duration_fit

def rank(narration, shots, topn=5):
    ranked = sorted(shots, key=lambda s: score_shot(narration, s), reverse=True)[:topn]
    return [{"shot": s, "score": round(score_shot(narration, s), 4)} for s in ranked]

def build_edl(narrations, shots):
    used = set()
    edl = []
    for n in narrations:
        candidates = rank(n, [s for s in shots if s["id"] not in used], 10) or rank(n, shots, 5)
        if not candidates:
            continue
        best = candidates[0]
        shot = best["shot"]
        required = float(n["end"]) - float(n["start"])
        source_start = float(shot["start"])
        source_end = min(float(shot["end"]), source_start + required)
        reason = "best available shot is shorter than narration segment" if source_end - source_start < required else "duration-fit baseline; visual metadata not yet enriched"
        used.add(shot["id"])
        edl.append({"timeline_start": float(n["start"]), "timeline_end": float(n["end"]), "source_path": shot["video_path"], "source_start": source_start, "source_end": source_end, "narration_index": n["index"], "score": best["score"], "reason": reason, "alternatives": [{"shot_id": x["shot"]["id"], "score": x["score"]} for x in candidates[1:4]]})
    return edl
