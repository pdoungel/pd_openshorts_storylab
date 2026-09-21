from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


class StoryBrief(BaseModel):
    """Editorial lens shared by every Story Lab project."""
    angle: Literal["story", "why", "theory", "character", "theme", "lore", "worldbuilding", "ending", "adaptation", "review", "documentary"] = "story"
    question: str = Field(default="", max_length=2000)
    audience: str = Field(default="", max_length=500)
    tone: str = Field(default="clear", max_length=120)
    spoiler_policy: Literal["none", "light", "full"] = "light"
    output_format: str = Field(default="long_form", max_length=80)
    target_duration_seconds: Optional[float] = Field(default=None, gt=0)


class StoryProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    kind: Literal["movie", "series", "anime", "episode", "documentary", "other"] = "movie"
    brief: StoryBrief = Field(default_factory=StoryBrief)
    source_path: Optional[str] = None
    notes: str = Field(default="", max_length=5000)


class TranscriptSegment(BaseModel):
    text: str = Field(min_length=1)
    start: Optional[float] = Field(default=None, ge=0)
    end: Optional[float] = Field(default=None, ge=0)
    page: Optional[int] = Field(default=None, ge=1)
    source_id: Optional[str] = None


class SourceLocator(BaseModel):
    """A source record. ``path`` is always a Story Lab-owned copy when uploaded."""
    id: str
    name: str
    kind: Literal["video", "audio", "pdf", "transcript", "text"]
    path: Optional[str] = None
    mime_type: Optional[str] = None
    page_count: Optional[int] = None
    duration: Optional[float] = Field(default=None, ge=0)
    text: str = ""
    segments: list[TranscriptSegment] = Field(default_factory=list)
    checksum: Optional[str] = None
    created_at: str


class Evidence(BaseModel):
    id: str
    # Raw model output may contain invalid timestamps; normalize_evidence() is the trust boundary.
    start: Optional[float] = None
    end: Optional[float] = None
    page: Optional[int] = Field(default=None, ge=1)
    source_id: Optional[str] = None
    label: str
    claim: str
    supporting_text: str = ""
    detail: str = ""  # compatibility with the first Story Lab vertical slice
    confidence: float = Field(default=0.5, ge=0, le=1)
    traceability: Literal["source", "derived", "unverified"] = "unverified"


class Theory(BaseModel):
    id: str
    title: str
    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class StoryBuilder(BaseModel):
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
    # Provenance for each generated story component. These IDs refer only to
    # evidence already present in StoryAnalysis.evidence.
    hook_evidence_ids: list[str] = Field(default_factory=list)
    context_evidence_ids: list[str] = Field(default_factory=list)
    timeline_evidence_ids: list[list[str]] = Field(default_factory=list)
    key_event_evidence_ids: list[list[str]] = Field(default_factory=list)
    people_evidence_ids: list[list[str]] = Field(default_factory=list)
    conflict_evidence_ids: list[str] = Field(default_factory=list)
    consequences_evidence_ids: list[str] = Field(default_factory=list)
    significance_evidence_ids: list[str] = Field(default_factory=list)
    central_question_evidence_ids: list[str] = Field(default_factory=list)
    interpretation_evidence_ids: list[str] = Field(default_factory=list)
    counterpoint_evidence_ids: list[list[str]] = Field(default_factory=list)
    open_question_evidence_ids: list[list[str]] = Field(default_factory=list)


class VisualResearchItem(BaseModel):
    id: str
    description: str
    material_type: Literal["source_backed", "archival", "contextual", "generated", "graphic"]
    evidence_ids: list[str] = Field(default_factory=list)
    source_id: Optional[str] = None
    asset_path: Optional[str] = None
    source_url: Optional[str] = None
    status: Literal["planned", "researching", "approved", "rejected"] = "planned"
    notes: str = ""


class VisualSuggestion(BaseModel):
    description: str
    material_type: Literal["source_backed", "contextual", "generated"]
    evidence_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class ScriptSection(BaseModel):
    id: str
    heading: str
    narration: str
    evidence_ids: list[str] = Field(default_factory=list)
    visual_suggestions: list[VisualSuggestion] = Field(default_factory=list)
    visual_research: list[VisualResearchItem] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    source_timestamps: list[tuple[float, float]] = Field(default_factory=list)
    duration_seconds: float = Field(default=0, ge=0)
    approved: bool = False


class ReviewItem(BaseModel):
    id: str
    target_type: Literal["evidence", "script", "render"]
    target_id: str
    status: Literal["pending", "approved", "changes_requested"] = "pending"
    note: str = ""
    updated_at: str


class RenderArtifact(BaseModel):
    id: str
    status: Literal["planned", "rendering", "rendered", "error"] = "planned"
    output_path: Optional[str] = None
    manifest_path: Optional[str] = None
    error: Optional[str] = None
    created_at: str


class Scene(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    title: str
    purpose: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    source_file: Optional[str] = None
    output_file: Optional[str] = None
    relevance: float = Field(default=1.0, ge=0, le=1)
    extraction_status: Literal["candidate", "extracted", "error"] = "candidate"


class StoryAnalysis(BaseModel):
    summary: str
    themes: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    theories: list[Theory] = Field(default_factory=list)
    story: StoryBuilder = Field(default_factory=StoryBuilder)


class StoryProject(BaseModel):
    id: str
    title: str
    kind: Literal["movie", "series", "anime", "episode", "documentary", "other"]
    brief: StoryBrief = Field(default_factory=StoryBrief)
    source_path: Optional[str] = None
    notes: str = ""
    status: Literal["draft", "ingested", "analyzing", "analyzed", "review", "approved", "rendered", "error"] = "draft"
    created_at: str
    updated_at: str
    sources: list[SourceLocator] = Field(default_factory=list)
    analysis: Optional[StoryAnalysis] = None
    scenes: list[Scene] = Field(default_factory=list)
    script: list[ScriptSection] = Field(default_factory=list)
    reviews: list[ReviewItem] = Field(default_factory=list)
    renders: list[RenderArtifact] = Field(default_factory=list)
    error: Optional[str] = None
