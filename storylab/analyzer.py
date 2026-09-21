from __future__ import annotations
import uuid
from typing import Optional
from pydantic import BaseModel, Field
from .evidence import normalize_evidence
from .models import Evidence, Theory, StoryAnalysis
class _LLMEvidence(BaseModel):
    start: float = 0; end: float = 1; label: str = "evidence"; claim: str = ""; detail: str = ""; confidence: float = 0.5
class _LLMTheory(BaseModel):
    title: str; claim: str; evidence_indexes: list[int] = Field(default_factory=list); confidence: float = 0.5
class _LLMAnalysis(BaseModel):
    summary: str; themes: list[str] = Field(default_factory=list); characters: list[str] = Field(default_factory=list); evidence: list[_LLMEvidence] = Field(default_factory=list); theories: list[_LLMTheory] = Field(default_factory=list)
def _fallback_analysis(title: str, transcript: str) -> StoryAnalysis:
    text = " ".join((transcript or "").split())
    return StoryAnalysis(summary=text[:1200] if text else f"Story Lab project: {title}. Add a transcript or source media to analyze the story.")
def analyze_story(title: str, transcript: str = "", duration: Optional[float] = None) -> StoryAnalysis:
    try:
        import llm_backend
        if not llm_backend.active(): return _fallback_analysis(title, transcript)
        prompt = f"""Analyze this film/episode material for documentary story analysis. TITLE: {title}. DURATION_SECONDS: {duration or 'unknown'}. TRANSCRIPT: {transcript[:120000]}
Return JSON matching the schema. Evidence MUST use absolute seconds only when the material contains reliable timestamps; otherwise return no evidence. Never invent timestamps. Theories must cite evidence indexes. Focus on themes, character arcs, narrative structure, foreshadowing, contradictions and motifs."""
        data, _ = llm_backend.generate_json(prompt, _LLMAnalysis)
        parsed = _LLMAnalysis.model_validate(data)
        evidence = [Evidence(id=f"ev_{uuid.uuid4().hex[:10]}", start=x.start, end=x.end, label=x.label, claim=x.claim, detail=x.detail, confidence=max(0,min(1,x.confidence))) for x in parsed.evidence]
        evidence = normalize_evidence(evidence, duration)
        theories = [Theory(id=f"th_{uuid.uuid4().hex[:10]}", title=x.title, claim=x.claim, evidence_ids=[evidence[i].id for i in x.evidence_indexes if 0 <= i < len(evidence)], confidence=max(0,min(1,x.confidence))) for x in parsed.theories]
        return StoryAnalysis(summary=parsed.summary, themes=parsed.themes, characters=parsed.characters, evidence=evidence, theories=theories)
    except Exception:
        return _fallback_analysis(title, transcript)
