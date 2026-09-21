from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field
class StoryProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    kind: Literal["movie", "series", "anime", "episode"] = "movie"
    source_path: Optional[str] = None
    notes: str = Field(default="", max_length=5000)
class Evidence(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    label: str
    claim: str
    detail: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
class Theory(BaseModel):
    id: str
    title: str
    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
class Scene(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    title: str
    purpose: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    source_file: Optional[str] = None
    output_file: Optional[str] = None
class ScriptSection(BaseModel):
    id: str
    heading: str
    narration: str
    evidence_ids: list[str] = Field(default_factory=list)
class StoryAnalysis(BaseModel):
    summary: str
    themes: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    theories: list[Theory] = Field(default_factory=list)
class StoryProject(BaseModel):
    id: str
    title: str
    kind: str
    source_path: Optional[str] = None
    notes: str = ""
    status: Literal["draft", "analyzing", "analyzed", "error"] = "draft"
    created_at: str
    updated_at: str
    analysis: Optional[StoryAnalysis] = None
    scenes: list[Scene] = Field(default_factory=list)
    script: list[ScriptSection] = Field(default_factory=list)
    error: Optional[str] = None
