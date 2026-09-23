"""Voiceover-master visual matcher and contiguous EDL builder."""
from __future__ import annotations

import re

from .embeddings import rank_texts

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
    query = str(requirement.get("visual_query", ""))
    subject, action, environment, context = [], [], [], []

    for item in preferred:
        low = item.lower()
        if any(x in low for x in ("soldier", "person", "people", "man", "woman", "crowd", "vehicle", "building")):
            subject.append(item)
        elif any(x in low for x in ("walk", "march", "move", "cross", "run", "ride", "fight", "work", "carry")):
            action.append(item)
        elif any(x in low for x in ("hill", "mountain", "forest", "road", "village", "river", "city", "landscape", "jungle")):
            environment.append(item)
        else:
            context.append(item)

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
    context_values = _as_list(shot.get("tags")) + _as_list(shot.get("visual_style")) + [_text(shot)]
    context = _concept_overlap(concepts["context"], context_values)

    weighted = [
        ("subject", subject, 0.40),
        ("action", action, 0.25),
        ("environment", environment, 0.20),
        ("context", context, 0.15),
    ]
    active = [(score, weight) for name, score, weight in weighted if concepts[name]]
    return sum(score * weight for score, weight in active) / sum(weight for _, weight in active) if active else 0.0


def _match_type(score, concept_score):
    if concept_score >= 0.72 and score >= 0.72:
        return "direct"
    if concept_score >= 0.30 or score >= 0.48:
        return "related"
    return "contextual_fallback"


def rank(requirement, shots, topn=8):
    if not shots:
        return []

    query = requirement.get("visual_query", "")
    texts = [_text(s) for s in shots]
    rows = rank_texts(query, texts)
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
            "match_type": _match_type(final_score, concept_score),
            "method": method,
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:topn]


def _source_window(shot, duration, used_ranges=None):
    start = float(shot["start"])
    end = float(shot["end"])
    if end <= start or duration <= 0:
        return None

    used = sorted(used_ranges.get(shot["id"], [])) if used_ranges else []
    cursor = start
    for used_start, used_end in used:
        if used_end <= cursor:
            continue
        if used_start > cursor:
            break
        cursor = max(cursor, used_end)

    if cursor >= end:
        # Reuse is allowed; restart at the beginning when this shot is exhausted.
        cursor = start

    return cursor, min(end, cursor + duration)


def _clip(match, n, req, timeline_start, source_start, source_end, reused=False):
    duration = max(0.0, source_end - source_start)
    requested = max(0.001, float(n["end"]) - float(n["start"]))
    fit = min(1.0, duration / requested)
    reason = f"{match['match_type'].replace('_', ' ')} visual match"
    if reused:
        reason += "; reused footage after stronger unused shots were exhausted"

    return {
        "sequence": None,
        "timeline_start": round(timeline_start, 4),
        "timeline_end": round(timeline_start + duration, 4),
        "duration": round(duration, 4),
        "source_path": match["shot"]["video_path"],
        "source_start": round(source_start, 4),
        "source_end": round(source_end, 4),
        "source_duration": round(duration, 4),
        "narration_index": n["index"],
        "narration": n["text"],
        "description": match["shot"].get("description", ""),
        "visual_query": req.get("visual_query", ""),
        "score": round(0.85 * match["score"] + 0.15 * fit, 4),
        "match_method": match["method"],
        "match_type": match["match_type"],
        "concept_score": match["concept_score"],
        "duration_fit": round(fit, 4),
        "reused": reused,
        "reason": reason,
        "alternatives": [],
    }


def build_visual_edl(narrations, requirements, shots):
    """Build an EDL in narration order with no timeline gaps.

    The voiceover is the master clock. For every narration segment, the matcher
    first consumes unused strong visual shots, then reuses the best candidates
    if the library is shorter than the spoken duration. This guarantees that
    timeline order follows narration order rather than the arbitrary order of
    source files.
    """
    valid_shots = [s for s in shots if s.get("description")]
    if not valid_shots:
        raise RuntimeError("No successfully analyzed visual shots are available for matching.")

    ordered_narrations = sorted(
        narrations,
        key=lambda n: (float(n.get("start", 0)), int(n.get("index", 0))),
    )
    by_index = {r["narration_index"]: r for r in requirements}

    used_ids = set()
    used_ranges = {}
    edl = []

    for n in ordered_narrations:
        req = by_index.get(
            n["index"],
            {
                "narration_index": n["index"],
                "visual_query": n["text"],
                "preferred_visuals": [n["text"]],
            },
        )
        cursor = float(n["start"])
        remaining = max(0.0, float(n["end"]) - float(n["start"]))
        attempted = set()

        while remaining > 0.01:
            unused = [
                s for s in valid_shots
                if s["id"] not in used_ids and s["id"] not in attempted
            ]
            candidates = rank(req, unused, 8) if unused else []

            reused = False
            if not candidates:
                reusable = [s for s in valid_shots if s["id"] not in attempted]
                candidates = rank(req, reusable, 8)
                reused = True

            if not candidates:
                break

            match = candidates[0]
            shot = match["shot"]
            attempted.add(shot["id"])
            window = _source_window(shot, remaining, used_ranges)
            if not window:
                continue

            source_start, source_end = window
            duration = source_end - source_start
            if duration <= 0.01:
                continue

            clip = _clip(match, n, req, cursor, source_start, source_end, reused)
            clip["alternatives"] = [
                {
                    "shot_id": x["shot"]["id"],
                    "source_path": x["shot"]["video_path"],
                    "score": x["score"],
                    "match_type": x["match_type"],
                }
                for x in candidates[1:5]
            ]
            edl.append(clip)

            used_ids.add(shot["id"])
            used_ranges.setdefault(shot["id"], []).append((source_start, source_end))
            cursor += duration
            remaining -= duration

            # Once we are reusing, allow the same shot again only after trying
            # the other top candidates. Reset attempted when all candidates are
            # exhausted so a long narration can be fully covered.
            if reused and remaining > 0.01:
                attempted.clear()

        if remaining > 0.01:
            # This can only happen with unusable/zero-duration media. Fail loudly
            # rather than returning a misleadingly incomplete timeline.
            raise RuntimeError(
                f"Could not cover narration segment {n['index']} completely; "
                f"{remaining:.2f}s remains."
            )

    # Validate the final edit before returning it.
    expected = sorted(edl, key=lambda c: (c["timeline_start"], c["sequence"] or 0))
    previous_end = None
    for sequence, clip in enumerate(expected, 1):
        clip["sequence"] = sequence
        start = float(clip["timeline_start"])
        end = float(clip["timeline_end"])
        if end <= start:
            raise RuntimeError(f"Invalid zero-length EDL clip at sequence {sequence}.")
        if previous_end is not None and abs(start - previous_end) > 0.02:
            raise RuntimeError(
                f"EDL timeline gap detected before sequence {sequence}: "
                f"{previous_end:.3f}s → {start:.3f}s."
            )
        previous_end = end

    return expected
