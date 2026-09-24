"""YouTube title, description (with chapters) and tags for the finished video."""
from __future__ import annotations

import json
import os
import re

from .planner import _json


def _stamp(seconds):
    s = int(max(0, seconds))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _valid_chapters(chapters, duration):
    """YouTube needs the first chapter at 0:00, at least 3 chapters, each 10s or longer."""
    clean = []
    for ch in sorted(chapters, key=lambda c: float(c.get("start", 0))):
        try:
            start = float(ch.get("start", 0))
        except (TypeError, ValueError):
            continue
        title = " ".join(str(ch.get("title", "")).split())[:80]
        if not title or start >= duration:
            continue
        if clean and start - clean[-1]["start"] < 10:
            continue
        clean.append({"start": start, "title": title})
    if clean:
        clean[0]["start"] = 0.0
    if clean and duration - clean[-1]["start"] < 10:
        clean.pop()
    return clean if len(clean) >= 3 else []


def _fallback(narrations):
    text = " ".join(n["text"] for n in narrations)
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text)]
    tags = list(dict.fromkeys(w.lower() for w in words))[:15]
    first = narrations[0]["text"] if narrations else "Untitled video"
    return {"title": first[:95], "title_options": [first[:95]], "description": text[:4500],
            "chapters": [], "tags": tags, "hashtags": [], "provider": "fallback"}


def generate(narrations, clips, duration, instruction=""):
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        return _fallback(narrations)
    from . import gemini

    transcript = [{"t": round(float(n["start"]), 1), "text": n["text"]} for n in narrations]
    visuals = list(dict.fromkeys(c.get("description", "")[:120] for c in clips if c.get("description")))[:40]
    prompt = (
        "You package long-form YouTube videos. From this narrated video's timestamped transcript and "
        "a sample of the footage shown, write metadata that is truthful to the content.\n"
        "Return ONLY JSON with: title_options (5 titles, each under 70 characters, curiosity-driven, "
        "no clickbait lies, main keyword early), title (the best one), description (2-3 short "
        "paragraphs, keyword-rich, no chapter list, no hashtags), chapters (list of {start: seconds "
        "from the transcript, title: 2-6 words}, first at 0, at least 3 if the video is over 60s, "
        "spaced 10s or more), tags (15-25 search phrases, total under 450 characters), hashtags "
        "(3 without spaces, with #).\n"
        f"Video length: {round(duration)}s. Editorial direction: {instruction or 'none'}\n"
        f"TRANSCRIPT: {json.dumps(transcript, ensure_ascii=False)}\n"
        f"FOOTAGE SAMPLE: {json.dumps(visuals, ensure_ascii=False)}"
    )
    try:
        data = _json(gemini.generate("metadata", prompt))
    except Exception as exc:
        print(f"[footage-analyzer] metadata generation failed: {exc}", flush=True)
        return _fallback(narrations)

    chapters = _valid_chapters(data.get("chapters") or [], duration)
    tags, total = [], 0
    for tag in data.get("tags") or []:
        tag = " ".join(str(tag).replace(",", " ").split())
        if tag and total + len(tag) + 1 <= 480:
            tags.append(tag)
            total += len(tag) + 1
    hashtags = [h if h.startswith("#") else f"#{h}" for h in (str(x).replace(" ", "") for x in data.get("hashtags") or []) if h]
    description = str(data.get("description", "")).strip()
    if chapters:
        description += "\n\nChapters:\n" + "\n".join(f"{_stamp(c['start'])} {c['title']}" for c in chapters)
    if hashtags:
        description += "\n\n" + " ".join(hashtags[:3])
    options = [str(t).strip() for t in data.get("title_options") or [] if str(t).strip()]
    title = str(data.get("title") or (options[0] if options else "")).strip()[:100]
    return {"title": title, "title_options": options or [title], "description": description,
            "chapters": chapters, "tags": tags, "hashtags": hashtags[:3], "provider": "gemini"}
