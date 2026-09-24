"""Gemini editorial rerank: pick the best shot per narration line from embedding candidates."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .matcher import rank
from .planner import _json

BATCH = 12
TOP_K = 8


def choose(narrations, requirements, shots, visual_cues="", progress=None):
    """Return {narration_index: [shot_id, ...]} in preferred order; {} when unavailable."""
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key or not shots or os.getenv("FOOTAGE_RERANK", "1") == "0":
        return {}
    from . import gemini

    by_index = {r["narration_index"]: r for r in requirements}
    items = []
    for n in narrations:
        req = by_index.get(n["index"], {"visual_query": n["text"], "preferred_visuals": [n["text"]]})
        cands = rank(req, shots, TOP_K)
        items.append({
            "narration_index": n["index"],
            "narration": n["text"],
            "seconds": round(float(n["end"]) - float(n["start"]), 1),
            "visual_intent": req.get("visual_query", ""),
            "candidates": [
                {
                    "shot_id": c["shot"]["id"],
                    "file": Path(c["shot"]["video_path"]).name,
                    "seconds": round(float(c["shot"]["duration"]), 1),
                    "visible": c["shot"].get("description", "")[:300],
                }
                for c in cands
            ],
        })

    picks = {}
    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
    for number, batch in enumerate(batches, 1):
        if progress:
            progress(number - 1, len(batches))
        prompt = (
            "You are a documentary editor choosing b-roll for a voiceover. For every narration line, "
            "rank its candidate shots from best to worst by how well what is VISIBLE illustrates the line. "
            "Prefer literal matches, then clearly related imagery, then mood/context. Avoid giving the same "
            "shot to consecutive lines when a comparable alternative exists. Use the user's visual cues as "
            "preferred alternatives when nothing literal fits.\n"
            f"Visual cues from the user: {visual_cues or 'none'}\n"
            "Return ONLY JSON: {\"picks\": [{\"narration_index\": int, \"ranked_shot_ids\": [str, ...]}]} "
            "using only the candidate shot_ids given for that line.\nLINES:\n"
            + json.dumps(batch, ensure_ascii=False)
        )
        try:
            data = _json(gemini.generate("rerank", prompt))
        except Exception as exc:
            print(f"[footage-analyzer] rerank batch {number} failed, keeping embedding order: {exc}", flush=True)
            continue
        allowed = {it["narration_index"]: {c["shot_id"] for c in it["candidates"]} for it in batch}
        for pick in data.get("picks", []) if isinstance(data, dict) else []:
            try:
                idx = int(pick.get("narration_index"))
            except (TypeError, ValueError):
                continue
            ids = [s for s in pick.get("ranked_shot_ids", []) if s in allowed.get(idx, ())]
            if ids:
                picks[idx] = ids
    if progress:
        progress(len(batches), len(batches))
    return picks
