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
