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


def _section(heading: str, narration: str, evidence: list[Evidence], insights=None) -> ScriptSection:
    visuals = _visuals(evidence)
    research = [VisualResearchItem(id=f"vr_{uuid.uuid4().hex[:10]}", description=v.description, material_type=v.material_type, evidence_ids=v.evidence_ids, status="planned", notes=v.notes) for v in visuals]
    insights = insights or []
    return ScriptSection(
        id=f"sc_{uuid.uuid4().hex[:10]}", heading=heading, narration=narration,
        evidence_ids=[item.id for item in evidence],
        insight_ids=[item.id for item in insights], visual_suggestions=visuals, visual_research=research,
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
    insights = analysis.insights
    sections = []

    def select_insights(types=None, limit=4):
        allowed = set(types or [])
        rows = [i for i in insights if not allowed or i.type in allowed]
        rows.sort(key=lambda i: (i.status == "approved", i.confidence), reverse=True)
        return rows[:limit]

    def drive(narration, ids, types=None):
        # Insights are provenance/review data, not narration copy. Earlier versions
        # appended every matching insight to the script, which duplicated source
        # material and could turn internal analysis instructions into narration.
        rows = select_insights(types)
        base_ids = list(ids or [])
        if base_ids:
            scoped = [row for row in rows if set(row.evidence_ids).intersection(base_ids)]
            rows = scoped or rows
        ids = list(dict.fromkeys(base_ids + [eid for row in rows for eid in row.evidence_ids]))
        if not narration.strip() and rows:
            narration = " ".join(row.text for row in rows[:3]).strip()
        return narration.strip(), ids, rows

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
            ("Counterpoints", " ".join(story.counterpoints), [i for group in story.counterpoint_evidence_ids for i in group]),
            ("Implications", story.significance or story.consequences, story.significance_evidence_ids or story.consequences_evidence_ids),
        ]
    elif angle == "theory":
        plans = [
            ("The question", story.central_question or story.hook, story.central_question_evidence_ids or story.hook_evidence_ids),
            ("What is canon", story.context, story.context_evidence_ids),
            ("The theory", story.interpretation or story.significance, story.interpretation_evidence_ids or story.significance_evidence_ids),
            ("Evidence for and against", " ".join(story.counterpoints), [i for group in story.counterpoint_evidence_ids for i in group] or story.significance_evidence_ids),
            ("What remains unknown", " ".join(story.open_questions), [i for group in story.open_question_evidence_ids for i in group]),
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
            ("Open questions", " ".join(story.open_questions), [i for group in story.open_question_evidence_ids for i in group]),
        ]
    elif angle == "ending":
        plans = [
            ("What leads to the ending", story.context, story.context_evidence_ids),
            ("The final turning point", story.key_events[-1] if story.key_events else story.consequences, story.key_event_evidence_ids[-1] if story.key_event_evidence_ids else story.consequences_evidence_ids),
            ("What the ending establishes", story.consequences, story.consequences_evidence_ids),
            ("Possible interpretations", story.interpretation or story.significance, story.interpretation_evidence_ids or story.significance_evidence_ids),
            ("What remains ambiguous", " ".join(story.open_questions), [i for group in story.open_question_evidence_ids for i in group]),
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
        selected_types = {
                "The question": {"question"},
                "What the sources establish": {"fact", "event"},
                "The explanation": {"interpretation", "theory"},
                "Counterpoints": {"counterpoint"},
                "Implications": {"theme", "lore"},
                "What is canon": {"fact", "lore", "event"},
                "The theory": {"theory", "interpretation"},
                "Evidence for and against": {"fact", "counterpoint", "theory"},
                "What remains unknown": {"question"},
                "Motivation and stakes": {"character", "relationship"},
                "Turning points": {"event", "fact"},
                "Relationships": {"relationship", "character"},
                "Character meaning": {"character", "theme"},
                "Patterns and meaning": {"theme", "lore", "interpretation"},
                "Open questions": {"question"},
                "Possible interpretations": {"interpretation", "theory"},
                "What remains ambiguous": {"question"},
                "Meaning / takeaway": {"theme", "interpretation"},
        }.get(heading, {"fact", "event"})
        narration, ids, selected_insights = drive(narration, ids if isinstance(ids, list) else [], selected_types)
        if narration:
            linked = _evidence_by_ids(analysis, ids if isinstance(ids, list) else [])
            if not linked:
                linked = _fallback_slice(evidence, 0, min(3, len(evidence)))
            sections.append(_section(heading, narration, linked, selected_insights))
    return sections
