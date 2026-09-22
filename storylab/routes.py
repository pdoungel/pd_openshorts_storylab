from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .models import StoryProjectCreate, StoryBrief, StoryBuilder
from .service import store
from .tts import narration_text, narration_srt

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
    query: str = Field(default="", max_length=2000)
    context_seconds: float = Field(default=3.0, ge=0, le=30)
    max_results: int = Field(default=12, ge=1, le=40)
    search_mode: str = Field(default="hybrid", pattern="^(hybrid|embedding|lexical)$")
    embedding_provider: str = Field(default="local", pattern="^(local|auto|sentence-transformers)$")


class SceneSelectionRequest(BaseModel):
    scene_ids: list[str] = Field(default_factory=list)


class YouTubePackageRequest(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = None
    category_id: str | None = Field(default=None, max_length=10)
    language: str | None = Field(default=None, max_length=20)
    privacy_status: str | None = Field(default=None, pattern="^(private|unlisted|public)$")
    made_for_kids: bool | None = None
    contains_synthetic_media: bool | None = None
    thumbnail_path: str | None = None
    publish_at: str | None = None


class VoiceoverRequest(BaseModel):
    profile_id: str = Field(min_length=1, max_length=200)


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

@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    try:
        store.delete(project_id)
        return {"deleted": True, "project_id": project_id}
    except FileNotFoundError:
        raise HTTPException(404, "Story Lab project not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))




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
    return _project_or_404(lambda: store.search_scenes(project_id, payload.evidence_ids, payload.query, payload.context_seconds, payload.max_results, payload.search_mode, payload.embedding_provider))


@router.post("/projects/{project_id}/scenes/extract")
async def extract_scenes(project_id: str, payload: SceneRequest):
    return _project_or_404(lambda: store.extract_scenes(project_id, payload.scene_ids))


@router.post("/projects/{project_id}/scenes/select")
async def select_scenes(project_id: str, payload: SceneSelectionRequest):
    return _project_or_404(lambda: store.select_scenes(project_id, payload.scene_ids))


@router.post("/projects/{project_id}/youtube")
async def update_youtube_package(project_id: str, payload: YouTubePackageRequest):
    from .youtube import build_youtube_package
    def action():
        project = store.get(project_id)
        package = project.youtube or build_youtube_package(project)
        updates = payload.model_dump(exclude_none=True)
        project.youtube = package.model_copy(update=updates)
        return store.save(project)
    return _project_or_404(action)


@router.post("/projects/{project_id}/story")
async def update_story(project_id: str, payload: StoryBuilder):
    return _project_or_404(lambda: store.update_story(project_id, payload))


@router.post("/projects/{project_id}/review")
async def review_project(project_id: str, payload: ReviewRequest):
    return _project_or_404(lambda: store.review(project_id, payload.target_type, payload.target_id, payload.status, payload.note))


@router.post("/projects/{project_id}/visual-review")
async def review_visual(project_id: str, payload: ReviewRequest):
    return _project_or_404(lambda: store.review_visual(project_id, payload.target_id, payload.status, payload.note))


@router.get("/voicebox/status")
async def voicebox_status():
    return store.voicebox_status()


@router.get("/voicebox/profiles")
async def voicebox_profiles():
    try:
        return {"profiles": store.voicebox_profiles()}
    except Exception as exc:
        raise HTTPException(503, str(exc))


@router.post("/projects/{project_id}/narration/prepare")
async def prepare_project_narration(project_id: str):
    return _project_or_404(lambda: store.prepare_narration(project_id))


@router.post("/projects/{project_id}/voiceover")
async def generate_project_voiceover(project_id: str, payload: VoiceoverRequest):
    return _project_or_404(lambda: store.generate_voiceover(project_id, payload.profile_id))


@router.post("/projects/{project_id}/narration/audio/upload")
async def upload_narration_audio(
    project_id: str,
    file: UploadFile = File(...),
    section_id: str | None = Form(default=None),
    combined: bool = Form(default=False),
):
    suffix = Path(file.filename or "narration.wav").suffix or ".wav"
    handle = tempfile.NamedTemporaryFile(prefix="storylab_narration_", suffix=suffix, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            shutil.copyfileobj(file.file, handle)
        return _project_or_404(lambda: store.upload_narration_audio(
            project_id, str(temporary), section_id=section_id, combined=combined
        ))
    finally:
        await file.close()
        temporary.unlink(missing_ok=True)


@router.post("/projects/{project_id}/render")
async def render_project(project_id: str):
    return _project_or_404(lambda: store.render(project_id))


@router.get("/projects/{project_id}/download/render")
async def download_render(project_id: str):
    try:
        project = store.get(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Story Lab project not found")
    if not project.renders:
        raise HTTPException(404, "No Story Lab render is available.")
    artifact = project.renders[-1]
    if artifact.status != "rendered" or not artifact.output_path:
        raise HTTPException(409, "The latest Story Lab render is not ready.")
    path = Path(artifact.output_path).resolve()
    root = store.root.resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "Rendered file is not available.")
    return FileResponse(str(path), media_type="video/mp4", filename=f"{project.title[:80]}.mp4")


@router.get("/projects/{project_id}/download/narration")
async def download_narration(project_id: str):
    try:
        project = store.get(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Story Lab project not found")
    from fastapi.responses import Response
    return Response(
        content=narration_text(project),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{project.title[:80]}.narration.txt"'},
    )


@router.get("/projects/{project_id}/download/narration-audio")
async def download_narration_audio(project_id: str):
    try:
        project = store.get(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Story Lab project not found")
    if not project.voiceover or project.voiceover.status not in {"generated", "manual"} or not project.voiceover.audio_path:
        raise HTTPException(404, "Generated narration audio is not available.")
    path = Path(project.voiceover.audio_path).resolve()
    root = store.root.resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "Generated narration audio is not available.")
    return FileResponse(str(path), media_type="audio/wav", filename=f"{project.title[:80]}.narration.wav")


@router.get("/projects/{project_id}/download/narration-srt")
async def download_narration_srt(project_id: str):
    try:
        project = store.get(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Story Lab project not found")
    from fastapi.responses import Response
    return Response(
        content=narration_srt(project),
        media_type="application/x-subrip",
        headers={"Content-Disposition": f'attachment; filename="{project.title[:80]}.narration.srt"'},
    )


@router.get("/projects/{project_id}/download/metadata")
async def download_metadata(project_id: str):
    try:
        project = store.get(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Story Lab project not found")
    if not project.youtube:
        raise HTTPException(404, "Story Lab publishing metadata is not available.")
    import json
    payload = json.dumps(project.youtube.model_dump(), ensure_ascii=False, indent=2)
    from fastapi.responses import Response
    return Response(content=payload, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{project.title[:80]}.metadata.json"'})


@router.get("/projects/{project_id}/scenes/{scene_id}/file")
async def download_scene(project_id: str, scene_id: str):
    try:
        project = store.get(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Story Lab project not found")
    scene = next((item for item in project.scenes if item.id == scene_id), None)
    if not scene or not scene.output_file:
        raise HTTPException(404, "Scene clip is not available.")
    path = Path(scene.output_file).resolve()
    root = store.root.resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "Scene clip is not available.")
    return FileResponse(str(path), media_type="video/mp4", filename=f"{scene.id}.mp4")
