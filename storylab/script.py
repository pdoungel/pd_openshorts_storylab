from __future__ import annotations

import uuid
from .models import Evidence, ScriptSection, StoryAnalysis, VisualSuggestion, VisualResearchItem


def _duration(text: str) -> float:
    return round(max(4.0, len(text.split()) / 2.5), 1)  # documentary narration at ~150 wpm


def _visuals(evidence: list[Evidence]) -> list[VisualSuggestion]:
    timed = [item for item in evidence if item.traceability == "source" and item.start is not None and item.end is not None]
    if timed:
        return [VisualSuggestion(description="Use the cited source moment with its original context.", material_type="source_backed", evidence_ids=[item.id for item in timed[:2]])]
    if evidence:
        return [VisualSuggestion(description="Use a clearly labelled contextual image or archival material; it does not depict the cited event.", material_type="contextual", evidence_ids=[item.id for item in evidence[:2]])]
    return [VisualSuggestion(description="Create an explanatory diagram or abstract transition; do not present it as source footage.", material_type="generated")]


def _section(heading: str, narration: str, evidence: list[Evidence]) -> ScriptSection:
    visuals = _visuals(evidence)
    research = [VisualResearchItem(id=f"vr_{uuid.uuid4().hex[:10]}", description=v.description, material_type=v.material_type, evidence_ids=v.evidence_ids, status="planned", notes=v.notes) for v in visuals]
    return ScriptSection(
        id=f"sc_{uuid.uuid4().hex[:10]}", heading=heading, narration=narration,
        evidence_ids=[item.id for item in evidence], visual_suggestions=visuals, visual_research=research,
        source_pages=sorted({item.page for item in evidence if item.page}),
        source_timestamps=[(item.start, item.end) for item in evidence if item.start is not None and item.end is not None],
        duration_seconds=_duration(narration),
    )


def _evidence_by_ids(analysis: StoryAnalysis, ids: list[str]) -> list[Evidence]:
    lookup = {item.id: item for item in analysis.evidence}
    return [lookup[item_id] for item_id in ids if item_id in lookup]


def _fallback_slice(evidence: list[Evidence], start: int, stop: int) -> list[Evidence]:
    return evidence[start:stop] if evidence else []


def build_script(analysis: StoryAnalysis, angle: str = "story", kind: str = "movie") -> list[ScriptSection]:
    """Build a reusable outline for any Story Lab format or editorial angle.

    Prefer the evidence IDs attached by the research/analyzer stage. The
    positional fallback keeps older projects readable after schema upgrades.
    """
    evidence = analysis.evidence
    story = analysis.story
    sections = []

    hook_evidence = _evidence_by_ids(analysis, story.hook_evidence_ids) or _fallback_slice(evidence, 0, 2)
    sections.append(_section("Hook", story.hook or analysis.summary[:500], hook_evidence))

    if story.context:
        context_evidence = _evidence_by_ids(analysis, story.context_evidence_ids) or _fallback_slice(evidence, 0, 3)
        sections.append(_section("Context", story.context, context_evidence))

    if angle == "why":
        plans = [
            ("The question", story.central_question or story.context, story.central_question_evidence_ids or story.context_evidence_ids),
            ("What the sources establish", story.context or analysis.summary, story.context_evidence_ids),
            ("The explanation", story.interpretation or story.conflict, story.interpretation_evidence_ids or story.conflict_evidence_ids),
            ("Counterpoints", " ".join(story.counterpoints) or "Test the explanation against contrary evidence.", [i for group in story.counterpoint_evidence_ids for i in group]),
            ("Implications", story.significance or story.consequences, story.significance_evidence_ids or story.consequences_evidence_ids),
        ]
    elif angle == "theory":
        plans = [
            ("The question", story.central_question or story.hook, story.central_question_evidence_ids or story.hook_evidence_ids),
            ("What is canon", story.context, story.context_evidence_ids),
            ("The theory", story.interpretation or story.significance, story.interpretation_evidence_ids or story.significance_evidence_ids),
            ("Evidence for and against", " ".join(story.counterpoints) or "Separate supporting clues from evidence that weakens the theory.", [i for group in story.counterpoint_evidence_ids for i in group] or story.significance_evidence_ids),
            ("What remains unknown", " ".join(story.open_questions) or "Mark unresolved points instead of presenting them as fact.", [i for group in story.open_question_evidence_ids for i in group]),
        ]
    elif angle == "character":
        plans = [
            ("Character setup", story.context or story.hook, story.context_evidence_ids or story.hook_evidence_ids),
            ("Motivation and stakes", story.conflict, story.conflict_evidence_ids),
            ("Turning points", " ".join(story.key_events[:5]), [i for group in story.key_event_evidence_ids for i in group]),
            ("Relationships", " ".join(story.people), [i for group in story.people_evidence_ids for i in group]),
            ("Character meaning", story.significance or story.interpretation, story.significance_evidence_ids or story.interpretation_evidence_ids),
        ]
    elif angle in {"theme", "lore", "worldbuilding"}:
        plans = [
            ("Setup", story.context or story.hook, story.context_evidence_ids or story.hook_evidence_ids),
            ("Evidence in the story", " ".join(story.key_events[:5]), [i for group in story.key_event_evidence_ids for i in group]),
            ("Patterns and meaning", story.interpretation or story.significance, story.interpretation_evidence_ids or story.significance_evidence_ids),
            ("Open questions", " ".join(story.open_questions) or "Identify gaps that require more source material.", [i for group in story.open_question_evidence_ids for i in group]),
        ]
    elif angle == "ending":
        plans = [
            ("What leads to the ending", story.context, story.context_evidence_ids),
            ("The final turning point", story.key_events[-1] if story.key_events else story.consequences, story.key_event_evidence_ids[-1] if story.key_event_evidence_ids else story.consequences_evidence_ids),
            ("What the ending establishes", story.consequences, story.consequences_evidence_ids),
            ("Possible interpretations", story.interpretation or story.significance, story.interpretation_evidence_ids or story.significance_evidence_ids),
            ("What remains ambiguous", " ".join(story.open_questions) or "Mark unresolved ambiguity.", [i for group in story.open_question_evidence_ids for i in group]),
        ]
    else:
        plans = [
            ("Context", story.context, story.context_evidence_ids or _fallback_slice(evidence, 0, 3)),
            ("Key development", " ".join(story.key_events[:5]), [i for group in story.key_event_evidence_ids for i in group]),
            ("Conflict and stakes", story.conflict, story.conflict_evidence_ids),
            ("Consequences", story.consequences, story.consequences_evidence_ids),
            ("Meaning / takeaway", story.significance or story.interpretation, story.significance_evidence_ids or story.interpretation_evidence_ids),
        ]

    for heading, narration, ids in plans:
        if narration:
            linked = _evidence_by_ids(analysis, ids if isinstance(ids, list) else [])
            if not linked:
                linked = _fallback_slice(evidence, 0, min(3, len(evidence)))
            sections.append(_section(heading, narration, linked))
    return sections
