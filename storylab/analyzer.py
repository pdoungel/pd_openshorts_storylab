from __future__ import annotations

import uuid
from typing import Optional
from pydantic import BaseModel, Field

from .evidence import extract_source_evidence
from .models import Evidence, Insight, SourceLocator, StoryAnalysis, StoryBuilder, Theory


class _LLMTheory(BaseModel):
    title: str
    claim: str
    evidence_indexes: list[int] = Field(default_factory=list)
    confidence: float = 0.5


class _LLMInsight(BaseModel):
    type: str = "fact"
    title: str
    text: str
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
    insights: list[_LLMInsight] = Field(default_factory=list)
    theories: list[_LLMTheory] = Field(default_factory=list)


def _fallback_analysis(title: str, transcript: str, evidence: list[Evidence]) -> StoryAnalysis:
    text = " ".join((transcript or "").split())
    summary = text[:1200] if text else f"Story Lab project: {title}. Add a transcript or source media to analyze the story."
    excerpts = [item.claim for item in evidence[:5]]
    ids = [item.id for item in evidence[:5]]
    grouped = [[item.id] for item in evidence[:5]]
    insights = [
        Insight(id=f"in_{uuid.uuid4().hex[:10]}", type="fact", title=item.label or "Source fact",
                text=item.claim, evidence_ids=[item.id], confidence=item.confidence, status="supported")
        for item in evidence[:5] if item.claim
    ]
    if evidence:
        insights.append(Insight(id=f"in_{uuid.uuid4().hex[:10]}", type="question",
                                title="Open research question",
                                text="What remains unsupported or ambiguous in the available material?",
                                evidence_ids=[item.id for item in evidence[:2]], confidence=0.5))
    fact_insights = [i for i in insights if i.type == "fact"]
    event_insights = [i for i in insights if i.type == "event"]
    question_insights = [i for i in insights if i.type == "question"]
    story = StoryBuilder(
        hook=fact_insights[0].text if fact_insights else summary[:300],
        context=" ".join(i.text for i in fact_insights[:3]) or summary[:600],
        timeline=[i.text for i in fact_insights[:5]],
        key_events=[i.text for i in event_insights[:5]] or excerpts,
        people=[i.text for i in insights if i.type in {"character", "relationship"}][:5],
        conflict="Identify the competing goals in the cited material before making an interpretive claim.",
        consequences=fact_insights[-1].text if fact_insights else "Use the cited record to explain what changed.",
        significance="Separate what the sources establish from the story's interpretation.",
        central_question=question_insights[0].text if question_insights else "What is the most useful question this material can answer?",
        interpretation="Keep interpretation visibly separate from source-established facts.",
        open_questions=[i.text for i in question_insights[:5]] or ["What remains unsupported or ambiguous in the available material?"],
        hook_evidence_ids=fact_insights[0].evidence_ids if fact_insights else ids[:1],
        context_evidence_ids=[eid for i in fact_insights[:3] for eid in i.evidence_ids] or ids[:2],
        timeline_evidence_ids=[i.evidence_ids for i in fact_insights[:5]],
        key_event_evidence_ids=[i.evidence_ids for i in event_insights[:5]] or grouped,
        people_evidence_ids=[i.evidence_ids for i in insights if i.type in {"character", "relationship"}][:5],
        conflict_evidence_ids=ids[:2], consequences_evidence_ids=fact_insights[-1].evidence_ids if fact_insights else ids[:2],
        significance_evidence_ids=ids[:2], central_question_evidence_ids=question_insights[0].evidence_ids if question_insights else ids[:2],
        interpretation_evidence_ids=ids[:2], open_question_evidence_ids=[i.evidence_ids for i in question_insights[:5]] or ([ids[:2]] if ids else []),
    )
    return StoryAnalysis(summary=summary, evidence=evidence, insights=insights, story=story)


def analyze_story(title: str, transcript: str = "", duration: Optional[float] = None,
                  sources: list[SourceLocator] | None = None, angle: str = "story",
                  kind: str = "movie", question: str = "") -> StoryAnalysis:
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
CENTRAL QUESTION: {question or "Choose the most useful question supported by the supplied material."}
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

Return JSON matching the schema. Every story component must cite supplied excerpt indexes in its corresponding *_evidence_indexes field. Every insight and theory must cite supplied excerpt indexes. Empty evidence lists are acceptable when the component is not established by the supplied sources. Do not invent facts, people, pages, or timestamps. Keep interpretation separate from source-established facts."""

        data, _ = llm_backend.generate_json(prompt, _LLMAnalysis)
        parsed = _LLMAnalysis.model_validate(data)
        allowed_insight_types = {"fact", "interpretation", "question", "theory", "counterpoint", "theme", "lore", "character", "event", "relationship"}
        valid = lambda indexes: [evidence[i].id for i in indexes if 0 <= i < len(evidence)]
        insights = [Insight(id=f"in_{uuid.uuid4().hex[:10]}",
                           type=item.type if item.type in allowed_insight_types else "fact",
                           title=item.title, text=item.text,
                           evidence_ids=valid(item.evidence_indexes),
                           confidence=max(0, min(1, item.confidence))) for item in parsed.insights]
        theories = [Theory(id=f"th_{uuid.uuid4().hex[:10]}", title=item.title, claim=item.claim,
                           evidence_ids=valid(item.evidence_indexes),
                           confidence=max(0, min(1, item.confidence))) for item in parsed.theories]
        # Insights are the research layer that actively feeds the reusable story outline.
        facts = [i for i in insights if i.type == "fact"]
        interpretations = [i for i in insights if i.type in {"interpretation", "theory", "theme", "lore", "character"}]
        counterpoints = [i for i in insights if i.type == "counterpoint"]
        questions = [i for i in insights if i.type == "question"]
        grouped_valid = lambda groups: [valid(group) for group in groups]
        story = StoryBuilder(
            hook=parsed.hook or (facts[0].text if facts else ""),
            context=parsed.context or " ".join(i.text for i in facts[:3]),
            timeline=parsed.timeline or [i.text for i in facts[:5]],
            key_events=parsed.key_events or [i.text for i in insights if i.type == "event"][:5],
            people=parsed.people or [i.text for i in insights if i.type in {"character", "relationship"}][:5],
            conflict=parsed.conflict or (counterpoints[0].text if counterpoints else ""),
            consequences=parsed.consequences or (facts[-1].text if facts else ""),
            significance=parsed.significance or " ".join(i.text for i in interpretations[:2]),
            central_question=parsed.central_question or (questions[0].text if questions else question),
            interpretation=parsed.interpretation or " ".join(i.text for i in interpretations[:3]),
            counterpoints=parsed.counterpoints or [i.text for i in counterpoints[:5]],
            open_questions=parsed.open_questions or [i.text for i in questions[:5]],
            hook_evidence_ids=valid(parsed.hook_evidence_indexes) or (facts[0].evidence_ids if facts else []),
            context_evidence_ids=valid(parsed.context_evidence_indexes) or [eid for i in facts[:3] for eid in i.evidence_ids],
            timeline_evidence_ids=grouped_valid(parsed.timeline_evidence_indexes) or [i.evidence_ids for i in facts[:5]],
            key_event_evidence_ids=grouped_valid(parsed.key_event_evidence_indexes) or [i.evidence_ids for i in insights if i.type == "event"][:5],
            people_evidence_ids=grouped_valid(parsed.people_evidence_indexes) or [i.evidence_ids for i in insights if i.type in {"character", "relationship"}][:5],
            conflict_evidence_ids=valid(parsed.conflict_evidence_indexes) or (counterpoints[0].evidence_ids if counterpoints else []),
            consequences_evidence_ids=valid(parsed.consequences_evidence_indexes) or (facts[-1].evidence_ids if facts else []),
            significance_evidence_ids=valid(parsed.significance_evidence_indexes) or [eid for i in interpretations[:2] for eid in i.evidence_ids],
            central_question_evidence_ids=valid(parsed.central_question_evidence_indexes) or (questions[0].evidence_ids if questions else []),
            interpretation_evidence_ids=valid(parsed.interpretation_evidence_indexes) or [eid for i in interpretations[:3] for eid in i.evidence_ids],
            counterpoint_evidence_ids=grouped_valid(parsed.counterpoint_evidence_indexes) or [i.evidence_ids for i in counterpoints[:5]],
            open_question_evidence_ids=grouped_valid(parsed.open_question_evidence_indexes) or [i.evidence_ids for i in questions[:5]],
        )
        return StoryAnalysis(summary=parsed.summary, themes=parsed.themes, characters=parsed.characters, evidence=evidence, insights=insights, theories=theories,
                             story=story)
    except Exception:
        return _fallback_analysis(title, material, evidence)
