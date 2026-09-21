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


def build_script(analysis: StoryAnalysis) -> list[ScriptSection]:
    evidence = analysis.evidence
    story = analysis.story
    sections = [_section("Hook", story.hook or analysis.summary[:500], evidence[:2])]
    if story.context:
        sections.append(_section("Context", story.context, evidence[:3]))
    for index, event in enumerate(story.key_events[:5] or analysis.themes[:5], 1):
        sections.append(_section(f"Key event {index}", event, evidence[index - 1:index + 2]))
    if story.conflict:
        sections.append(_section("Conflict", story.conflict, evidence[-3:]))
    if story.consequences:
        sections.append(_section("Consequences", story.consequences, evidence[-2:]))
    conclusion = story.significance or "Return to the central question and distinguish documented evidence from interpretation."
    sections.append(_section("Significance", conclusion, evidence[-2:]))
    return sections
