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
    """Resolve a browser-selected directory without an expensive filesystem walk.

    A normal browser deliberately does not expose the absolute Mac path.  When
    webkitRelativePath is present we use the selected folder name; when it is
    absent we locate one distinctive selected file first, then validate the
    remaining samples in that file's parent.  This keeps folder selection fast
    even when /Volumes contains large media libraries.
    """
    import subprocess

    raw_name=str(payload.get("folder_name") or "").strip()
    samples=payload.get("samples") or []
    folder_name=raw_name if raw_name and raw_name not in {".",".."} and "/" not in raw_name and "\\" not in raw_name else ""

    if not samples:
        raise HTTPException(400,"No footage files were supplied by the folder picker.")

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

    search_roots=[Path("/Users"),Path("/Volumes")]
    search_roots=[p for p in search_roots if p.exists()]

    def file_matches(path, sample):
        try:
            return path.name == sample["name"] and path.is_file() and (
                sample["size"] is None or path.stat().st_size == sample["size"]
            )
        except OSError:
            return False

    def run_find(args, timeout=12):
        try:
            p=subprocess.run(
                ["find", *args],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
            return [Path(x) for x in p.stdout.splitlines() if x.strip()]
        except (subprocess.TimeoutExpired, OSError):
            return []

    match=None

    # Fast path when the browser supplied the selected folder name.
    if folder_name:
        candidates=[]
        for root in search_roots:
            candidates.extend(run_find([str(root), "-type", "d", "-name", folder_name, "-print", "-prune"], timeout=8))
            if len(candidates)>25:
                break

        def candidate_score(candidate):
            score=0
            for sample in clean:
                rel=sample["relative_path"]
                parts=Path(rel).parts
                target=(candidate.joinpath(*parts[1:]) if len(parts)>=2 and parts[0]==folder_name
                        else candidate/sample["name"])
                if file_matches(target,sample):
                    score+=1
            return score

        scored=sorted(
            ((candidate_score(p),p) for p in candidates if p.is_dir()),
            key=lambda x:x[0], reverse=True
        )
        threshold=min(3,len(clean))
        winners=[p for score,p in scored if score>=threshold]
        if len(winners)==1:
            match=winners[0]
        elif len(winners)>1 and scored and scored[0][0]>scored[1][0]:
            match=scored[0][1]
        elif len(winners)>1:
            raise HTTPException(409,{
                "message":"More than one matching footage folder was found.",
                "candidates":[str(p) for p in winners[:10]],
            })

    # Fallback when the webview strips webkitRelativePath. Search for one
    # distinctive selected file instead of recursively walking every directory.
    if match is None:
        ranked=sorted(
            clean,
            key=lambda s:(len(s["name"]), s["size"] or -1),
            reverse=True
        )
        probe=ranked[0]
        find_args=[]
        for root in search_roots:
            find_args.extend([str(root), "-type", "f", "-name", probe["name"], "-size", f"{probe['size']}c", "-print"])
        hits=run_find(find_args, timeout=15) if probe["size"] is not None else []
        if not hits and probe["size"] is None:
            find_args=[]
            for root in search_roots:
                find_args.extend([str(root), "-type", "f", "-name", probe["name"], "-print"])
            hits=run_find(find_args, timeout=15)

        parents=[]
        for hit in hits[:100]:
            parent=hit.parent
            if parent not in parents:
                parents.append(parent)

        scored=[]
        for parent in parents:
            score=sum(1 for sample in clean if file_matches(parent/sample["name"],sample))
            if score>=min(3,len(clean)):
                scored.append((score,parent))

        scored.sort(key=lambda x:x[0],reverse=True)
        if scored:
            best_score=scored[0][0]
            best=[p for score,p in scored if score==best_score]
            if len(best)==1:
                match=best[0]
            else:
                raise HTTPException(409,{
                    "message":"More than one mounted folder matches the selected footage files.",
                    "candidates":[str(p) for p in best[:10]],
                })

    if match is None:
        if not search_roots:
            raise HTTPException(503,"The analyzer cannot see the Mac media roots. Check Docker Desktop File Sharing.")
        raise HTTPException(
            404,
            "The browser supplied the footage files, but the analyzer could not resolve their Mac folder. "
            "This can happen when the folder is outside /Users or /Volumes, or when Docker Desktop has not shared the drive."
        )

    video_exts={".mp4",".mov",".mkv",".m4v",".webm",".avi",".mts",".m2ts",".ts"}
    video_count=0
    try:
        for p in match.iterdir():
            if p.is_file() and p.suffix.lower() in video_exts:
                video_count+=1
    except OSError:
        pass

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
