from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .models import StoryProjectCreate, StoryBrief
from .service import store

router = APIRouter(prefix="/api/storylab", tags=["storylab"])


class AnalyzeRequest(BaseModel):
    transcript: str = Field(default="", max_length=500000)
    duration: float | None = Field(default=None, gt=0)


class TextSourceRequest(BaseModel):
    name: str = Field(default="source.txt", max_length=180)
    text: str = Field(min_length=1, max_length=500000)


class SceneRequest(BaseModel):
    scene_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    target_type: str
    target_id: str
    status: str
    note: str = Field(default="", max_length=5000)


def _project_or_404(action):
    try:
        return action().model_dump()
    except FileNotFoundError:
        raise HTTPException(404, "Story Lab project not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/projects")
async def list_projects():
    return {"projects": [project.model_dump() for project in store.list()]}


@router.post("/projects")
async def create_project(payload: StoryProjectCreate):
    return store.create(payload).model_dump()


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    return _project_or_404(lambda: store.get(project_id))




@router.post("/projects/{project_id}/brief")
async def update_brief(project_id: str, payload: StoryBrief):
    return _project_or_404(lambda: store.update_brief(project_id, payload))

@router.post("/projects/{project_id}/sources/text")
async def add_text_source(project_id: str, payload: TextSourceRequest):
    return _project_or_404(lambda: store.ingest_text(project_id, payload.text, payload.name))


@router.post("/projects/{project_id}/sources/upload")
async def upload_source(project_id: str, file: UploadFile = File(...), transcribe: bool = False):
    # Upload to a temporary file before the store copies it to its project-owned source area.
    suffix = Path(file.filename or "source.txt").suffix
    handle = tempfile.NamedTemporaryFile(prefix="storylab_", suffix=suffix, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            shutil.copyfileobj(file.file, handle)
        return _project_or_404(lambda: store.ingest(project_id, str(temporary), file.filename, transcribe))
    finally:
        await file.close()
        temporary.unlink(missing_ok=True)


@router.post("/projects/{project_id}/analyze")
async def analyze_project(project_id: str, payload: AnalyzeRequest):
    return _project_or_404(lambda: store.analyze(project_id, payload.transcript, payload.duration))


@router.post("/projects/{project_id}/scenes/search")
async def search_scenes(project_id: str, payload: SceneRequest):
    return _project_or_404(lambda: store.search_scenes(project_id, payload.evidence_ids))


@router.post("/projects/{project_id}/scenes/extract")
async def extract_scenes(project_id: str, payload: SceneRequest):
    return _project_or_404(lambda: store.extract_scenes(project_id, payload.scene_ids))


@router.post("/projects/{project_id}/review")
async def review_project(project_id: str, payload: ReviewRequest):
    return _project_or_404(lambda: store.review(project_id, payload.target_type, payload.target_id, payload.status, payload.note))


@router.post("/projects/{project_id}/visual-review")
async def review_visual(project_id: str, payload: ReviewRequest):
    return _project_or_404(lambda: store.review_visual(project_id, payload.target_id, payload.status, payload.note))


@router.post("/projects/{project_id}/render")
async def render_project(project_id: str):
    return _project_or_404(lambda: store.render(project_id))
