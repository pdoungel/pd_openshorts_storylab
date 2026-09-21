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


def build_script(analysis: StoryAnalysis) -> list[ScriptSection]:
    """Turn the reviewed story structure into a traceable documentary outline.

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

    events = story.key_events[:5] or analysis.themes[:5]
    for index, event in enumerate(events):
        ids = story.key_event_evidence_ids[index] if index < len(story.key_event_evidence_ids) else []
        event_evidence = _evidence_by_ids(analysis, ids) or _fallback_slice(evidence, index, index + 2)
        sections.append(_section(f"Key event {index + 1}", event, event_evidence))

    if story.conflict:
        conflict_evidence = _evidence_by_ids(analysis, story.conflict_evidence_ids) or evidence[-3:]
        sections.append(_section("Conflict", story.conflict, conflict_evidence))

    if story.consequences:
        consequence_evidence = _evidence_by_ids(analysis, story.consequences_evidence_ids) or evidence[-2:]
        sections.append(_section("Consequences", story.consequences, consequence_evidence))

    conclusion = story.significance or "Return to the central question and distinguish documented evidence from interpretation."
    significance_evidence = _evidence_by_ids(analysis, story.significance_evidence_ids) or evidence[-2:]
    sections.append(_section("Significance", conclusion, significance_evidence))
    return sections
