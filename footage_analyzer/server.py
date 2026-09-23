"""Standalone FastAPI service for Footage Analyzer."""
from __future__ import annotations
import os, shutil, time
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from .service import JobStore

BUILD_ID="e1c4abb7d64dd366d164e78849a718cc6c84f6fb"
app=FastAPI(title="OpenShorts Footage Analyzer",version="2.0-footage-mvp")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
store=JobStore()

@app.get("/health")
def health():
    return {"ok":True,"service":"footage-analyzer","build_id":BUILD_ID,"pid":os.getpid(),
            "transcriber":os.getenv("FOOTAGE_TRANSCRIBER","gemini"),
            "gemini_transcribe_model":os.getenv("FOOTAGE_GEMINI_TRANSCRIBE_MODEL","gemini-3.5-transcribe")}


@app.post("/api/footage-analyzer/jobs")
async def create_job(voiceover: UploadFile=File(...),footage_root: str=Form(...),instruction: str=Form("")):
    root=Path(footage_root).expanduser()
    if not root.exists() or not root.is_dir():
        raise HTTPException(400,"Footage folder is not accessible inside the analyzer container.")
    if not voiceover.filename: raise HTTPException(400,"Voiceover file is required.")
    incoming=store.root/"incoming"; incoming.mkdir(parents=True,exist_ok=True)
    path=incoming/Path(voiceover.filename).name
    with path.open("wb") as f: shutil.copyfileobj(voiceover.file,f)
    # Wait briefly for the worker to persist its first real stage so clients
    # never remain stuck displaying the initial 0/1% starting state.
    job=store.create(str(path),str(root),instruction)
    deadline=time.time()+2.0
    while time.time()<deadline:
        current=store.get(job["id"]) or job
        if int(current.get("update_seq",0))>0:
            return current
        time.sleep(0.05)
    return store.get(job["id"]) or job

@app.get("/api/footage-analyzer/index")
def index_status(root: str):
    p=Path(root).expanduser()
    if not p.exists() or not p.is_dir(): raise HTTPException(400,"Footage folder is not accessible.")
    return store.cache_status(str(p))

@app.delete("/api/footage-analyzer/index")
def clear_index(root: str):
    p=Path(root).expanduser()
    if not p.exists() or not p.is_dir(): raise HTTPException(400,"Footage folder is not accessible.")
    return store.clear_cache(str(p))

@app.post("/api/footage-analyzer/resolve-folder")
async def resolve_folder(payload: dict):
    folder_name=str(payload.get("folder_name") or "").strip()
    samples=payload.get("samples") or []
    if not folder_name or folder_name in {".",".."} or "/" in folder_name or "\\" in folder_name:
        raise HTTPException(400,"Invalid footage folder name.")
    search_roots=[Path("/Users"),Path("/Volumes")]; skipped={".git","node_modules","__pycache__",".cache",".Trash"}
    candidates=[]; roots_seen=[]
    def onerror(_error): return None
    # Browser directory inputs do not expose a native path in standard Chromium/WebKit.
    # Resolve the selected folder against the Mac filesystem mounted into Docker.
    # Allow normal nested project/media folders instead of silently failing at depth 5.
    max_depth=12
    for root in search_roots:
        if not root.exists(): continue
        roots_seen.append(str(root)); root_depth=len(root.parts)
        for base,dirs,_files in os.walk(root,topdown=True,onerror=onerror,followlinks=False):
            base_path=Path(base); depth=len(base_path.parts)-root_depth
            if depth>=max_depth: dirs[:]=[]; continue
            dirs[:]=[d for d in dirs if d not in skipped and not d.startswith(".")]
            if folder_name in dirs:
                candidate=base_path/folder_name
                if candidate.is_dir():
                    candidates.append(candidate)
                    if len(candidates)>=100: break
        if len(candidates)>=100: break
    def matches_samples(candidate):
        if not samples: return True
        checked=0
        for item in samples[:20]:
            relative=str(item.get("relative_path") or "").replace("\\","/").strip("/")
            parts=Path(relative).parts
            if len(parts)<2 or parts[0]!=folder_name: continue
            target=candidate.joinpath(*parts[1:])
            if not target.is_file(): return False
            size=item.get("size")
            if size is not None and target.stat().st_size!=int(size): return False
            checked+=1
        return checked>0
    matches=[p for p in candidates if matches_samples(p)]
    if len(matches)==1:
        match=matches[0]; video_exts={".mp4",".mov",".mkv",".m4v",".webm",".avi"}
        video_count=sum(1 for p in match.rglob("*") if p.is_file() and p.suffix.lower() in video_exts)
        return {"path":str(match),"folder_name":folder_name,"video_count":video_count,"source":"mounted_mac_filesystem"}
    if len(matches)>1:
        raise HTTPException(409,{"message":"More than one matching folder was found. The analyzer needs an unambiguous folder.","candidates":[str(p) for p in matches[:10]]})
    if not roots_seen:
        raise HTTPException(503,"The analyzer container cannot see /Users or /Volumes. Check Docker Desktop filesystem permissions and mounted drives.")
    raise HTTPException(404,f"'{folder_name}' was selected in the browser, but the analyzer cannot find that folder under /Users or /Volumes. If it is on an external drive, make sure the drive is mounted and Docker Desktop can access /Volumes.")

@app.get("/api/footage-analyzer/jobs/{job_id}")
def job_status(job_id:str):
    job=store.get(job_id)
    if not job: raise HTTPException(404,"Job not found")
    return job

@app.get("/api/footage-analyzer/jobs/{job_id}/edl")
def job_edl(job_id:str):
    job=store.get(job_id)
    if not job: raise HTTPException(404,"Job not found")
    if job["status"]!="complete": raise HTTPException(409,"Analysis is not complete")
    return job["result"]

@app.get("/api/footage-analyzer/jobs/{job_id}/edl/download")
def download_edl(job_id:str):
    job=store.get(job_id)
    if not job: raise HTTPException(404,"Job not found")
    if job["status"]!="complete": raise HTTPException(409,"Analysis is not complete")
    return FileResponse(store.root/job_id/"edl.json",filename=f"{job_id}-edl.json",media_type="application/json")
