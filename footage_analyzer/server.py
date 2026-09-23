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
    """Resolve a browser-selected directory without depending on File.path.

    Chromium/WebKit directory inputs are allowed to omit a native filesystem
    path and, in some desktop clients, even omit webkitRelativePath.  The
    resolver therefore accepts file samples (name + size + relative path)
    and identifies the real mounted directory from the Mac filesystem.
    """
    raw_name=str(payload.get("folder_name") or "").strip()
    samples=payload.get("samples") or []
    folder_name=raw_name if raw_name and raw_name not in {".",".."} and "/" not in raw_name and "\\" not in raw_name else ""

    if not samples:
        raise HTTPException(400,"No footage files were supplied by the folder picker.")

    search_roots=[Path("/Users"),Path("/Volumes")]
    skipped={".git","node_modules","__pycache__",".cache",".Trash"}
    roots_seen=[str(p) for p in search_roots if p.exists()]

    # Normalise the browser sample list. Name/size are available even when
    # webkitRelativePath is not.
    clean=[]
    for item in samples[:20]:
        name=Path(str(item.get("name") or "")).name
        rel=str(item.get("relative_path") or "").replace("\\","/").strip("/")
        size=item.get("size")
        if not name:
            continue
        try:
            size=int(size) if size is not None else None
        except (TypeError, ValueError):
            size=None
        clean.append({"name":name,"relative_path":rel,"size":size})
    if not clean:
        raise HTTPException(400,"The folder picker returned no usable video file information.")

    max_depth=12
    candidates=[]

    def onerror(_error):
        return None

    def file_matches(path, sample):
        if path.name != sample["name"] or not path.is_file():
            return False
        return sample["size"] is None or path.stat().st_size == sample["size"]

    # Fast path: when the browser supplied a folder name, locate that folder
    # and verify several selected files against it.
    if folder_name:
        for root in search_roots:
            if not root.exists():
                continue
            root_depth=len(root.parts)
            for base,dirs,_files in os.walk(root,topdown=True,onerror=onerror,followlinks=False):
                base_path=Path(base)
                depth=len(base_path.parts)-root_depth
                if depth>=max_depth:
                    dirs[:]=[]
                    continue
                dirs[:]=[d for d in dirs if d not in skipped and not d.startswith(".")]
                if folder_name in dirs:
                    candidate=base_path/folder_name
                    if candidate.is_dir():
                        candidates.append(candidate)
                if len(candidates)>=100:
                    break
            if len(candidates)>=100:
                break

        def matches_named_folder(candidate):
            checked=0
            for sample in clean:
                rel=sample["relative_path"]
                parts=Path(rel).parts
                target=None
                if len(parts)>=2 and parts[0]==folder_name:
                    target=candidate.joinpath(*parts[1:])
                else:
                    target=candidate/sample["name"]
                if target and file_matches(target,sample):
                    checked+=1
                elif len(parts)>=2:
                    return False
            return checked >= min(3,len(clean))

        matches=[p for p in candidates if matches_named_folder(p)]
        if len(matches)==1:
            match=matches[0]
        elif len(matches)>1:
            raise HTTPException(409,{
                "message":"More than one matching footage folder was found.",
                "candidates":[str(p) for p in matches[:10]],
            })
        else:
            match=None
    else:
        match=None

    # Robust fallback: identify the folder from the actual selected files.
    # This handles the exact case where the browser reports 14 files but no
    # webkitRelativePath/folder name.
    if match is None:
        sample_subset=clean[:5]
        found_parents={}
        for root in search_roots:
            if not root.exists():
                continue
            root_depth=len(root.parts)
            for base,dirs,files in os.walk(root,topdown=True,onerror=onerror,followlinks=False):
                base_path=Path(base)
                depth=len(base_path.parts)-root_depth
                if depth>=max_depth:
                    dirs[:]=[]
                    continue
                dirs[:]=[d for d in dirs if d not in skipped and not d.startswith(".")]
                file_set=set(files)
                if not all(s["name"] in file_set for s in sample_subset):
                    continue
                score=0
                for sample in sample_subset:
                    target=base_path/sample["name"]
                    if file_matches(target,sample):
                        score+=1
                if score==len(sample_subset):
                    found_parents[str(base_path)]=score
                    if len(found_parents)>20:
                        break
            if len(found_parents)>20:
                break

        matches=[Path(p) for p in found_parents]
        if len(matches)==1:
            match=matches[0]
        elif len(matches)>1:
            # Prefer a directory containing more of the selected sample files.
            scored=[]
            for candidate in matches:
                score=sum(1 for s in clean if file_matches(candidate/s["name"],s))
                scored.append((score,candidate))
            scored.sort(key=lambda x:x[0],reverse=True)
            best_score= scored[0][0] if scored else 0
            best=[p for score,p in scored if score==best_score and score>=min(3,len(clean))]
            if len(best)==1:
                match=best[0]
            else:
                raise HTTPException(409,{
                    "message":"More than one mounted folder matches the selected footage files.",
                    "candidates":[str(p) for p in best[:10]],
                })

    if match is None:
        if not roots_seen:
            raise HTTPException(503,"The analyzer cannot see the Mac media roots. Check Docker Desktop File Sharing.")
        raise HTTPException(
            404,
            "The browser supplied the footage files, but the analyzer could not resolve their Mac folder. "
            "The folder may be outside /Users or /Volumes, or Docker Desktop may not have access to that drive."
        )

    video_exts={".mp4",".mov",".mkv",".m4v",".webm",".avi",".mts",".m2ts",".ts"}
    video_count=sum(1 for p in match.rglob("*") if p.is_file() and p.suffix.lower() in video_exts)
    return {
        "path":str(match),
        "folder_name":match.name,
        "video_count":video_count,
        "source":"mounted_mac_filesystem",
        "matched_samples":len(clean),
    }

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
