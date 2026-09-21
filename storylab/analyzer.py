from __future__ import annotations

import uuid
from typing import Optional
from pydantic import BaseModel, Field

from .evidence import extract_source_evidence
from .models import Evidence, SourceLocator, StoryAnalysis, StoryBuilder, Theory


class _LLMTheory(BaseModel):
    title: str
    claim: str
    evidence_indexes: list[int] = Field(default_factory=list)
    confidence: float = 0.5


class _LLMAnalysis(BaseModel):
    summary: str
    themes: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    hook: str = ""
    context: str = ""
    timeline: list[str] = Field(default_factory=list)
    key_events: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    conflict: str = ""
    consequences: str = ""
    significance: str = ""
    theories: list[_LLMTheory] = Field(default_factory=list)


def _fallback_analysis(title: str, transcript: str, evidence: list[Evidence]) -> StoryAnalysis:
    text = " ".join((transcript or "").split())
    summary = text[:1200] if text else f"Story Lab project: {title}. Add a transcript or source media to analyze the story."
    excerpts = [item.claim for item in evidence[:5]]
    return StoryAnalysis(
        summary=summary, evidence=evidence,
        story=StoryBuilder(hook=summary[:300], context=summary[:600], timeline=excerpts, key_events=excerpts,
                           people=[], conflict="Identify the competing goals in the cited material before making an interpretive claim.",
                           consequences="Use the cited record to explain what changed.",
                           significance="Separate what the sources establish from the documentary's interpretation."),
    )


def analyze_story(title: str, transcript: str = "", duration: Optional[float] = None,
                  sources: list[SourceLocator] | None = None) -> StoryAnalysis:
    sources = sources or []
    evidence = extract_source_evidence(sources)
    material = transcript or "\n".join(source.text for source in sources)
    try:
        import llm_backend
        if not llm_backend.active():
            return _fallback_analysis(title, material, evidence)
        citations = "\n".join(f"[{index}] {item.supporting_text}" for index, item in enumerate(evidence[:60]))
        prompt = f"""Analyze source material for a documentary. TITLE: {title}
SOURCE EXCERPTS:
{citations}

Return JSON matching the schema. Every theory must cite supplied excerpt indexes. Do not invent facts, people, pages, or timestamps. Build hook, context, timeline, key events, people, conflict, consequences, and significance from the supplied excerpts."""
        data, _ = llm_backend.generate_json(prompt, _LLMAnalysis)
        parsed = _LLMAnalysis.model_validate(data)
        theories = [Theory(id=f"th_{uuid.uuid4().hex[:10]}", title=item.title, claim=item.claim,
                           evidence_ids=[evidence[index].id for index in item.evidence_indexes if 0 <= index < len(evidence)],
                           confidence=max(0, min(1, item.confidence))) for item in parsed.theories]
        return StoryAnalysis(summary=parsed.summary, themes=parsed.themes, characters=parsed.characters, evidence=evidence, theories=theories,
                             story=StoryBuilder(hook=parsed.hook, context=parsed.context, timeline=parsed.timeline,
                                                key_events=parsed.key_events, people=parsed.people, conflict=parsed.conflict,
                                                consequences=parsed.consequences, significance=parsed.significance))
    except Exception:
        return _fallback_analysis(title, material, evidence)
