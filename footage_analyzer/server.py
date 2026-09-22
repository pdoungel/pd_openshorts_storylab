"""Standalone FastAPI service for Footage Analyzer."""
from __future__ import annotations
import os, shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from .service import JobStore

app = FastAPI(title="OpenShorts Footage Analyzer", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
store = JobStore()

@app.get("/health")
def health():
    return {"ok": True, "service": "footage-analyzer"}

@app.post("/api/footage-analyzer/jobs")
async def create_job(voiceover: UploadFile = File(...), footage_root: str = Form(...),
                     instruction: str = Form("")):
    root = Path(footage_root).expanduser()
    if not root.exists() or not root.is_dir():
        raise HTTPException(400, "Footage folder is not accessible inside the analyzer container.")
    if not voiceover.filename:
        raise HTTPException(400, "Voiceover file is required.")
    incoming = store.root / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    path = incoming / Path(voiceover.filename).name
    with path.open("wb") as f:
        shutil.copyfileobj(voiceover.file, f)
    return store.create(str(path), str(root), instruction)



@app.post("/api/footage-analyzer/resolve-folder")
async def resolve_folder(payload: dict):
    """Resolve a Finder-selected folder to a path visible inside Docker."""
    folder_name = str(payload.get("folder_name") or "").strip()
    samples = payload.get("samples") or []
    if not folder_name or "/" in folder_name or "\\" in folder_name:
        raise HTTPException(400, "Invalid footage folder name.")
    candidates = []
    skipped = {".git", "node_modules", "__pycache__", ".cache", ".Trash"}
    for root in (Path("/Users"), Path("/Volumes")):
        if not root.exists(): continue
        for base, dirs, _files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skipped and not d.startswith(".")]
            if folder_name in dirs:
                candidates.append(Path(base) / folder_name)
                if len(candidates) >= 50: break
        if len(candidates) >= 50: break
    def matches_samples(candidate):
        if not samples: return True
        checked = 0
        for item in samples[:10]:
            parts = Path(str(item.get("relative_path") or "")).parts
            if len(parts) < 2 or parts[0] != folder_name: continue
            target = candidate.joinpath(*parts[1:])
            if not target.is_file(): return False
            size = item.get("size")
            if size is not None and target.stat().st_size != int(size): return False
            checked += 1
        return checked > 0
    matches = [p for p in candidates if matches_samples(p)]
    if len(matches) == 1: return {"path": str(matches[0]), "folder_name": folder_name}
    if len(matches) > 1: raise HTTPException(409, "More than one matching footage folder was found. Rename the footage folder so it is unique, then select it again.")
    raise HTTPException(404, "The selected folder could not be located under /Users or /Volumes. Make sure the folder is on a mounted Mac location.")

@app.get("/api/footage-analyzer/jobs/{job_id}")
def job_status(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job

@app.get("/api/footage-analyzer/jobs/{job_id}/edl")
def job_edl(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "complete":
        raise HTTPException(409, "Analysis is not complete")
    return job["result"]

@app.get("/api/footage-analyzer/jobs/{job_id}/edl/download")
def download_edl(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "complete":
        raise HTTPException(409, "Analysis is not complete")
    return FileResponse(store.root / job_id / "edl.json",
                        filename=f"{job_id}-edl.json",
                        media_type="application/json")
