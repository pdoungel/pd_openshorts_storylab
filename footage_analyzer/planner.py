"""Narration-to-visual intent planning with a deterministic fallback."""
from __future__ import annotations

import json
import os


def _json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.replace("```json", "", 1).replace("```", "").strip()
    try:
        return json.loads(text)
    except Exception:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise ValueError("Gemini did not return valid JSON")


def _fallback(narrations):
    requirements = []
    for n in narrations:
        text = " ".join(str(n.get("text", "")).split()).strip()
        requirements.append({
            "narration_index": n["index"],
            "visual_query": text,
            "preferred_visuals": [text] if text else [],
            "avoid": [],
            "rationale": "Fallback visual intent derived directly from the narration.",
        })
    return requirements


def _normalise(requirements, narrations):
    by_index = {}
    for item in requirements or []:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("narration_index"))
        except Exception:
            continue
        by_index[idx] = {
            "narration_index": idx,
            "visual_query": str(item.get("visual_query", "")).strip(),
            "preferred_visuals": (
                item.get("preferred_visuals")
                if isinstance(item.get("preferred_visuals"), list)
                else [str(item.get("preferred_visuals"))] if item.get("preferred_visuals") else []
            ),
            "avoid": item.get("avoid", []) if isinstance(item.get("avoid", []), list) else [str(item.get("avoid"))],
            "rationale": str(item.get("rationale", "")).strip(),
        }

    fallback = {r["narration_index"]: r for r in _fallback(narrations)}
    return [by_index.get(n["index"], fallback[n["index"]]) for n in narrations]


def plan(narrations, instruction=""):
    payload = [
        {"index": n["index"], "start": n["start"], "end": n["end"], "text": n["text"]}
        for n in narrations
    ]

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        return _fallback(narrations)

    prompt = (
        "Convert every narration segment into visual intent for matching against real footage. "
        "Do not treat visual_query as an exact search string. Describe concrete visible subjects, "
        "actions, environments, objects, documents, maps and contextual imagery. Prefer related "
        "footage when exact footage is absent. Never invent evidence. Return ONLY valid JSON with "
        "a requirements array. Every input index MUST appear exactly once. Each requirement must "
        "contain narration_index, visual_query, preferred_visuals, avoid and rationale. "
        "Editorial direction: " + (instruction or "none") + "\nINPUT:\n" +
        json.dumps(payload, ensure_ascii=False)
    )

    try:
        from google import genai

        response = genai.Client(api_key=key).models.generate_content(
            model=os.getenv("FOOTAGE_PLANNER_MODEL", "gemini-3.6-flash"),
            contents=prompt,
        )
        data = _json(getattr(response, "text", ""))
        requirements = data.get("requirements", []) if isinstance(data, dict) else []
        return _normalise(requirements, narrations)
    except Exception:
        # Planning should improve matching, not make the entire edit impossible.
        # Visual analysis still remains the evidence-producing stage.
        return _fallback(narrations)
