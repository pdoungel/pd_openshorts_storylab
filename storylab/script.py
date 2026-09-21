from __future__ import annotations
import uuid
from .models import ScriptSection, StoryAnalysis
def build_script(analysis: StoryAnalysis) -> list[ScriptSection]:
    sections=[ScriptSection(id=f"sc_{uuid.uuid4().hex[:10]}",heading="Hook",narration=analysis.summary[:500],evidence_ids=[e.id for e in analysis.evidence[:2]])]
    for theme in analysis.themes[:5]: sections.append(ScriptSection(id=f"sc_{uuid.uuid4().hex[:10]}",heading=theme,narration=f"Explore how {theme} shapes the story and what the evidence reveals.",evidence_ids=[e.id for e in analysis.evidence[:3]]))
    for theory in analysis.theories[:5]: sections.append(ScriptSection(id=f"sc_{uuid.uuid4().hex[:10]}",heading=theory.title,narration=theory.claim,evidence_ids=theory.evidence_ids))
    sections.append(ScriptSection(id=f"sc_{uuid.uuid4().hex[:10]}",heading="Conclusion",narration="Return to the central question and distinguish documented evidence from interpretation.",evidence_ids=[e.id for e in analysis.evidence[-2:]]))
    return sections
