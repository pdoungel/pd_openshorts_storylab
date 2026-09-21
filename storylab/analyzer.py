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
    central_question: str = ""
    interpretation: str = ""
    counterpoints: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    hook_evidence_indexes: list[int] = Field(default_factory=list)
    context_evidence_indexes: list[int] = Field(default_factory=list)
    timeline_evidence_indexes: list[list[int]] = Field(default_factory=list)
    key_event_evidence_indexes: list[list[int]] = Field(default_factory=list)
    people_evidence_indexes: list[list[int]] = Field(default_factory=list)
    conflict_evidence_indexes: list[int] = Field(default_factory=list)
    consequences_evidence_indexes: list[int] = Field(default_factory=list)
    significance_evidence_indexes: list[int] = Field(default_factory=list)
    central_question_evidence_indexes: list[int] = Field(default_factory=list)
    interpretation_evidence_indexes: list[int] = Field(default_factory=list)
    counterpoint_evidence_indexes: list[list[int]] = Field(default_factory=list)
    open_question_evidence_indexes: list[list[int]] = Field(default_factory=list)
    theories: list[_LLMTheory] = Field(default_factory=list)


def _fallback_analysis(title: str, transcript: str, evidence: list[Evidence]) -> StoryAnalysis:
    text = " ".join((transcript or "").split())
    summary = text[:1200] if text else f"Story Lab project: {title}. Add a transcript or source media to analyze the story."
    excerpts = [item.claim for item in evidence[:5]]
    ids = [item.id for item in evidence[:5]]
    grouped = [[item.id] for item in evidence[:5]]
    return StoryAnalysis(
        summary=summary, evidence=evidence,
        story=StoryBuilder(hook=summary[:300], context=summary[:600], timeline=excerpts, key_events=excerpts,
                           people=[], conflict="Identify the competing goals in the cited material before making an interpretive claim.",
                           consequences="Use the cited record to explain what changed.",
                           significance="Separate what the sources establish from the story's interpretation.",
                           central_question="What is the most useful question this material can answer?",
                           interpretation="Keep interpretation visibly separate from source-established facts.",
                           open_questions=["What remains unsupported or ambiguous in the available material?"],
                           hook_evidence_ids=ids[:1], context_evidence_ids=ids[:2],
                           timeline_evidence_ids=grouped, key_event_evidence_ids=grouped,
                           conflict_evidence_ids=ids[:2], consequences_evidence_ids=ids[:2],
                           significance_evidence_ids=ids[:2],
                           central_question_evidence_ids=ids[:2],
                           interpretation_evidence_ids=ids[:2],
                           open_question_evidence_ids=[ids[:2]] if ids else []),
    )


def analyze_story(title: str, transcript: str = "", duration: Optional[float] = None,
                  sources: list[SourceLocator] | None = None, angle: str = "story",
                  kind: str = "movie") -> StoryAnalysis:
    sources = sources or []
    evidence = extract_source_evidence(sources)
    material = transcript or "\n".join(source.text for source in sources)
    try:
        import llm_backend
        if not llm_backend.active():
            return _fallback_analysis(title, material, evidence)
        citations = "\n".join(f"[{index}] {item.supporting_text}" for index, item in enumerate(evidence[:60]))
        prompt = f"""Analyze this {kind} as a Story Lab research/writing project.
EDITORIAL ANGLE: {angle}
Adapt the analysis to the chosen lens:
- story: plot/structure, stakes, turning points, payoff
- why: answer a focused why-question using evidence and competing explanations
- theory: separate canon/source facts from hypotheses, supporting clues, and counterpoints
- character: motivations, relationships, development, and evidence
- theme: recurring ideas, motifs, conflicts, and evidence
- lore/worldbuilding: rules, history, factions, terminology, and gaps
- ending: ending setup/payoff, ambiguity, and interpretations
- adaptation: compare only supplied versions/sources
- review: distinguish observations from subjective evaluation
- documentary: factual narrative structure with explicit provenance
TITLE: {title}
SOURCE EXCERPTS:
{citations}

Return JSON matching the schema. Every story component must cite supplied excerpt indexes in its corresponding *_evidence_indexes field. Every theory must cite supplied excerpt indexes. Empty evidence lists are acceptable when the component is not established by the supplied sources. Do not invent facts, people, pages, or timestamps. Keep interpretation separate from source-established facts."""

        data, _ = llm_backend.generate_json(prompt, _LLMAnalysis)
        parsed = _LLMAnalysis.model_validate(data)
        theories = [Theory(id=f"th_{uuid.uuid4().hex[:10]}", title=item.title, claim=item.claim,
                           evidence_ids=[evidence[index].id for index in item.evidence_indexes if 0 <= index < len(evidence)],
                           confidence=max(0, min(1, item.confidence))) for item in parsed.theories]
        valid = lambda indexes: [evidence[i].id for i in indexes if 0 <= i < len(evidence)]
        grouped_valid = lambda groups: [valid(group) for group in groups]
        return StoryAnalysis(summary=parsed.summary, themes=parsed.themes, characters=parsed.characters, evidence=evidence, theories=theories,
                             story=StoryBuilder(
                                 hook=parsed.hook, context=parsed.context, timeline=parsed.timeline,
                                 key_events=parsed.key_events, people=parsed.people, conflict=parsed.conflict,
                                 consequences=parsed.consequences, significance=parsed.significance,
                                 central_question=parsed.central_question, interpretation=parsed.interpretation,
                                 counterpoints=parsed.counterpoints, open_questions=parsed.open_questions,
                                 hook_evidence_ids=valid(parsed.hook_evidence_indexes),
                                 context_evidence_ids=valid(parsed.context_evidence_indexes),
                                 timeline_evidence_ids=grouped_valid(parsed.timeline_evidence_indexes),
                                 key_event_evidence_ids=grouped_valid(parsed.key_event_evidence_indexes),
                                 people_evidence_ids=grouped_valid(parsed.people_evidence_indexes),
                                 conflict_evidence_ids=valid(parsed.conflict_evidence_indexes),
                                 consequences_evidence_ids=valid(parsed.consequences_evidence_indexes),
                                 significance_evidence_ids=valid(parsed.significance_evidence_indexes),
                                 central_question_evidence_ids=valid(parsed.central_question_evidence_indexes),
                                 interpretation_evidence_ids=valid(parsed.interpretation_evidence_indexes),
                                 counterpoint_evidence_ids=grouped_valid(parsed.counterpoint_evidence_indexes),
                                 open_question_evidence_ids=grouped_valid(parsed.open_question_evidence_indexes),
                             ))
    except Exception:
        return _fallback_analysis(title, material, evidence)
