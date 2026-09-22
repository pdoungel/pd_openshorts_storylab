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
    """Resolve a browser-selected folder to the same path visible inside Docker."""
    folder_name = str(payload.get("folder_name") or "").strip()
    samples = payload.get("samples") or []
    if not folder_name or folder_name in {".", ".."} or "/" in folder_name or "\\" in folder_name:
        raise HTTPException(400, "Invalid footage folder name.")

    search_roots = [Path("/Users"), Path("/Volumes")]
    skipped = {".git", "node_modules", "__pycache__", ".cache", ".Trash"}
    candidates = []
    roots_seen = []

    def onerror(_error):
        return None

    for root in search_roots:
        if not root.exists():
            continue
        roots_seen.append(str(root))
        for base, dirs, _files in os.walk(root, topdown=True, onerror=onerror, followlinks=False):
            dirs[:] = [d for d in dirs if d not in skipped and not d.startswith(".")]
            if folder_name in dirs:
                candidate = Path(base) / folder_name
                if candidate.is_dir():
                    candidates.append(candidate)
                    if len(candidates) >= 100:
                        break
        if len(candidates) >= 100:
            break

    def matches_samples(candidate):
        if not samples:
            return True
        checked = 0
        for item in samples[:20]:
            relative = str(item.get("relative_path") or "").replace("\\", "/").strip("/")
            parts = Path(relative).parts
            if len(parts) < 2 or parts[0] != folder_name:
                continue
            target = candidate.joinpath(*parts[1:])
            if not target.is_file():
                return False
            size = item.get("size")
            if size is not None and target.stat().st_size != int(size):
                return False
            checked += 1
        return checked > 0

    matches = [p for p in candidates if matches_samples(p)]
    if len(matches) == 1:
        match = matches[0]
        video_exts = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi"}
        video_count = sum(1 for p in match.rglob("*") if p.is_file() and p.suffix.lower() in video_exts)
        return {"path": str(match), "folder_name": folder_name, "video_count": video_count, "source": "mounted_mac_filesystem"}
    if len(matches) > 1:
        raise HTTPException(409, {"message": "More than one matching folder was found. The analyzer needs an unambiguous folder.", "candidates": [str(p) for p in matches[:10]]})
    if not roots_seen:
        raise HTTPException(503, "The analyzer container cannot see /Users or /Volumes. Check Docker Desktop filesystem permissions and mounted drives.")
    raise HTTPException(404, f"'{folder_name}' was selected in the browser, but the analyzer cannot find that folder under /Users or /Volumes. If it is on an external drive, make sure the drive is mounted and Docker Desktop can access /Volumes.")

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
