"""Semantic visual matcher and voiceover-master EDL builder.

The matcher treats planner output as visual intent rather than an exact phrase. It
scores subject/action/environment/context separately, relaxes requirements when
necessary, searches within indexed shots, and chains multiple shots to cover the
voiceover timeline.
"""
from __future__ import annotations

import math
import re

_TOKEN_RE = re.compile(r"[a-z0-9']+", re.I)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(x) for x in value if str(x).strip()]
    return [str(value)] if str(value).strip() else []


def _text(shot):
    fields = [
        shot.get("description", ""),
        " ".join(_as_list(shot.get("subjects"))),
        " ".join(_as_list(shot.get("actions"))),
        " ".join(_as_list(shot.get("setting"))),
        " ".join(_as_list(shot.get("visual_style"))),
        " ".join(_as_list(shot.get("tags"))),
    ]
    return " ".join(x for x in fields if x).strip()


def _tokens(value):
    return set(_TOKEN_RE.findall(str(value or "").lower()))


def _concept_overlap(terms, values):
    wanted = _tokens(terms)
    have = _tokens(" ".join(_as_list(values)))
    if not wanted:
        return 0.0
    return len(wanted & have) / len(wanted)


def _requirement_concepts(requirement):
    preferred = _as_list(requirement.get("preferred_visuals"))
    query = requirement.get("visual_query", "")
    # Gemini's planner normally puts concrete visual ideas in preferred_visuals.
    # Keep the query as a broad semantic fallback instead of requiring every word.
    subject, action, environment, context = [], [], [], []
    buckets = {"subject": subject, "action": action, "environment": environment, "context": context}
    for item in preferred:
        low = item.lower()
        target = (
            subject if any(x in low for x in ("soldier", "person", "people", "man", "woman", "crowd", "vehicle", "building"))
            else action if any(x in low for x in ("walk", "march", "move", "cross", "run", "ride", "fight", "work", "carry"))
            else environment if any(x in low for x in ("hill", "mountain", "forest", "road", "village", "river", "city", "landscape"))
            else context
        )
        target.append(item)
    # If the planner did not classify its ideas, let the broad query participate
    # in semantic ranking while keeping the explicit buckets available.
    return {
        "subject": subject,
        "action": action,
        "environment": environment,
        "context": context,
        "query": query,
    }


def _concept_score(requirement, shot):
    concepts = _requirement_concepts(requirement)
    subject = _concept_overlap(concepts["subject"], shot.get("subjects"))
    action = _concept_overlap(concepts["action"], shot.get("actions"))
    environment = _concept_overlap(concepts["environment"], shot.get("setting"))
    context_values = (
        _as_list(shot.get("tags"))
        + _as_list(shot.get("visual_style"))
        + [_text(shot)]
    )
    context = _concept_overlap(concepts["context"], context_values)

    # If a bucket is empty, redistribute its weight rather than penalising a shot.
    weighted = [("subject", subject, 0.40), ("action", action, 0.25),
                ("environment", environment, 0.20), ("context", context, 0.15)]
    active = [(score, weight) for name, score, weight in weighted if concepts[name]]
    if not active:
        return 0.0
    return sum(score * weight for score, weight in active) / sum(weight for _, weight in active)


def _match_type(score, concept_score, requirement, shot):
    if concept_score >= 0.72 and score >= 0.72:
        return "direct"
    if concept_score >= 0.30 or score >= 0.48:
        return "related"
    return "contextual_fallback"


def rank(requirement, shots, topn=5):
    from storylab.embeddings import rank_texts

    query = requirement.get("visual_query", "")
    texts = [_text(s) for s in shots]
    rows = rank_texts(query, texts, mode="hybrid", provider="auto")
    ranked = []
    for i, score, emb, lex, method in rows:
        shot = shots[i]
        concept_score = _concept_score(requirement, shot)
        final_score = 0.65 * score + 0.35 * concept_score
        ranked.append({
            "shot": shot,
            "score": round(final_score, 4),
            "embedding_score": round(emb, 4),
            "lexical_score": round(lex, 4),
            "concept_score": round(concept_score, 4),
            "match_type": _match_type(final_score, concept_score, requirement, shot),
            "method": method,
        })
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:topn]


def _candidate_range(shot, required, used_ranges=None):
    """Return the best available source window within a shot.

    Indexed shots may be long. Start from the shot's beginning unless a prior
    use left an available remainder; this keeps the source timeline deterministic.
    """
    start = float(shot["start"])
    end = float(shot["end"])
    if used_ranges:
        for used_start, used_end in used_ranges.get(shot["id"], []):
            if start < used_end <= end:
                start = used_end
    if start >= end:
        return None
    return start, min(end, start + required)


def _reason(match, fit):
    label = match["match_type"].replace("_", " ")
    if fit < 1.0:
        return f"{label} visual match; source section is shorter than the narration segment"
    return f"{label} visual match with duration fit"


def build_visual_edl(narrations, requirements, shots):
    """Build a complete visual timeline using the voiceover clock.

    A narration segment can consume several footage sections. Unused footage is
    preferred, but a strong shot can be reused later when the library is small.
    """
    by_index = {r["narration_index"]: r for r in requirements}
    used_ids = set()
    used_ranges = {}
    edl = []

    for n in narrations:
        timeline_start = float(n["start"])
        timeline_end = float(n["end"])
        cursor = timeline_start
        required_total = max(0.0, timeline_end - timeline_start)
        req = by_index.get(
            n["index"],
            {"narration_index": n["index"], "visual_query": n["text"], "preferred_visuals": []},
        )
        remaining = required_total
        segment_clips = []
        attempted = set()

        while remaining > 0.01:
            available = [s for s in shots if s["id"] not in used_ids and s["id"] not in attempted]
            ranked = rank(req, available, 20) if available else []
            if not ranked:
                available = [s for s in shots if s["id"] not in attempted]
                ranked = rank(req, available, 20) if available else []
            if not ranked:
                break

            match = ranked[0]
            shot = match["shot"]
            attempted.add(shot["id"])
            source_window = _candidate_range(shot, remaining, used_ranges)
            if not source_window:
                continue
            source_start, source_end = source_window
            source_duration = max(0.0, source_end - source_start)
            if source_duration <= 0.01:
                continue

            fit = min(1.0, source_duration / max(remaining, 0.001))
            final_score = round(0.85 * match["score"] + 0.15 * fit, 4)
            clip = {
                "timeline_start": round(cursor, 4),
                "timeline_end": round(cursor + source_duration, 4),
                "duration": round(source_duration, 4),
                "source_path": shot["video_path"],
                "source_start": round(source_start, 4),
                "source_end": round(source_end, 4),
                "source_duration": round(source_duration, 4),
                "narration_index": n["index"],
                "narration": n["text"],
                "visual_query": req.get("visual_query", ""),
                "score": final_score,
                "match_method": match["method"],
                "match_type": match["match_type"],
                "concept_score": match["concept_score"],
                "duration_fit": round(fit, 4),
                "reason": _reason(match, fit),
                "alternatives": [
                    {
                        "shot_id": x["shot"]["id"],
                        "source_path": x["shot"]["video_path"],
                        "score": x["score"],
                        "match_type": x["match_type"],
                    }
                    for x in ranked[1:5]
                ],
            }
            segment_clips.append(clip)
            used_ids.add(shot["id"])
            used_ranges.setdefault(shot["id"], []).append((source_start, source_end))
            cursor += source_duration
            remaining -= source_duration

        # If all shots were consumed, permit reuse of the strongest candidate.
        if remaining > 0.01 and shots:
            ranked = rank(req, shots, 5)
            if ranked:
                match = ranked[0]
                shot = match["shot"]
                source_start = float(shot["start"])
                source_end = min(float(shot["end"]), source_start + remaining)
                source_duration = max(0.0, source_end - source_start)
                if source_duration > 0.01:
                    fit = min(1.0, source_duration / max(remaining, 0.001))
                    segment_clips.append({
                        "timeline_start": round(cursor, 4),
                        "timeline_end": round(cursor + source_duration, 4),
                        "duration": round(source_duration, 4),
                        "source_path": shot["video_path"],
                        "source_start": round(source_start, 4),
                        "source_end": round(source_end, 4),
                        "source_duration": round(source_duration, 4),
                        "narration_index": n["index"],
                        "narration": n["text"],
                        "visual_query": req.get("visual_query", ""),
                        "score": round(0.85 * match["score"] + 0.15 * fit, 4),
                        "match_method": match["method"],
                        "match_type": match["match_type"],
                        "concept_score": match["concept_score"],
                        "duration_fit": round(fit, 4),
                        "reason": _reason(match, fit) + "; reused footage because the available library was exhausted",
                        "alternatives": [],
                    })
                    remaining -= source_duration
                    cursor += source_duration

        edl.extend(segment_clips)

    return edl
