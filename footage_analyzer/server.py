"""Standalone FastAPI service for Footage Analyzer."""
from __future__ import annotations
import asyncio, os, shutil, time, uuid
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from .service import JobStore

BUILD_ID="footage-analyzer-mvp-2026-09-23-transcription-v2"
app=FastAPI(title="OpenShorts Footage Analyzer",version="2.0-footage-mvp")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=False,allow_methods=["*"],allow_headers=["*"])
store=JobStore()

_SKIP_DIRS={"$recycle.bin","system volume information","windows","program files",
            "program files (x86)","programdata","appdata","node_modules",".git","library"}


def _search_roots():
    env=os.getenv("FOOTAGE_SEARCH_ROOTS")
    if env:
        return [Path(p) for p in env.split(os.pathsep) if p.strip() and Path(p).is_dir()]
    if os.name=="nt":
        import string
        system=Path(os.environ.get("SystemDrive","C:")+"\\")
        drives=[Path(f"{d}:\\") for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
        # Walking the whole system drive is slow; on it only the user profile is searched.
        return [d for d in drives if d!=system]+[Path.home()]
    return [p for p in (Path("/Users"),Path("/Volumes")) if p.exists()]


def _find(roots, want_dir=None, want_file=None, size=None, timeout=12, limit=100):
    """Locate a folder or file under the search roots.

    macOS/Linux (including the Docker image) use the system `find`, which is what
    the original Mac-only implementation used and is far faster on large media
    volumes. Windows has no `find` equivalent, so it walks with Python.
    """
    if os.name!="nt" and shutil.which("find"):
        return _posix_find(roots, want_dir, want_file, size, timeout, limit)
    return _walk_find(roots, want_dir, want_file, size, timeout, limit)


def _posix_find(roots, want_dir=None, want_file=None, size=None, timeout=12, limit=100):
    import subprocess
    args=[]
    for root in roots:
        if want_dir:
            args += [str(root), "-type", "d", "-name", want_dir, "-print", "-prune"]
        else:
            args += [str(root), "-type", "f", "-name", want_file]
            if size is not None:
                args += ["-size", f"{size}c"]
            args += ["-print"]
    try:
        p=subprocess.run(["find", *args], capture_output=True, text=True, timeout=timeout, check=False)
        out=p.stdout
    except subprocess.TimeoutExpired as exc:
        out=exc.stdout.decode(errors="ignore") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    except OSError:
        return []
    return [Path(x) for x in out.splitlines() if x.strip()][:limit]


def _walk_find(roots, want_dir=None, want_file=None, size=None, timeout=12, limit=100):
    norm=os.path.normcase
    deadline=time.monotonic()+timeout
    hits=[]
    for root in roots:
        for dirpath,dirnames,filenames in os.walk(root, onerror=lambda e: None):
            if time.monotonic()>deadline or len(hits)>=limit:
                return hits
            dirnames[:]=[d for d in dirnames if not d.startswith((".","$")) and d.lower() not in _SKIP_DIRS]
            if want_dir:
                for d in [d for d in dirnames if norm(d)==norm(want_dir)]:
                    hits.append(Path(dirpath)/d)
                    dirnames.remove(d)
            if want_file:
                for f in filenames:
                    if norm(f)!=norm(want_file):
                        continue
                    p=Path(dirpath)/f
                    try:
                        if size is None or p.stat().st_size==size:
                            hits.append(p)
                    except OSError:
                        pass
    return hits

@app.get("/health")
def health():
    return {"ok":True,"service":"footage-analyzer","build_id":BUILD_ID,"pid":os.getpid(),
            "transcriber":os.getenv("FOOTAGE_TRANSCRIBER","gemini"),
            "gemini_transcribe_model":os.getenv("FOOTAGE_GEMINI_TRANSCRIBE_MODEL","gemini-3.5-transcribe")}


@app.post("/api/footage-analyzer/jobs")
async def create_job(footage_root: str=Form(...),voiceover: UploadFile|None=File(None),
                     script: str=Form(""),instruction: str=Form(""),visual_cues: str=Form(""),
                     render: bool=Form(True),aspect: str=Form("16:9"),fit: str=Form("blur")):
    _check_format(aspect,fit)
    root=Path(footage_root).expanduser()
    if not root.exists() or not root.is_dir():
        raise HTTPException(400,"Footage folder is not accessible to the analyzer.")
    has_voice=bool(voiceover and voiceover.filename)
    if not has_voice and not script.strip():
        raise HTTPException(400,"Provide a voiceover file or a script.")
    path=None
    if has_voice:
        incoming=store.root/"incoming"; incoming.mkdir(parents=True,exist_ok=True)
        path=incoming/f"{uuid.uuid4().hex}-{Path(voiceover.filename).name}"
        with path.open("wb") as f:
            shutil.copyfileobj(voiceover.file,f)
    # Wait briefly for the worker to persist its first real stage so clients
    # never remain stuck displaying the initial 0/1% starting state.
    job=store.create(str(path) if path else "",str(root),instruction,
                     script=script.strip(),visual_cues=visual_cues.strip(),render=render,
                     aspect=aspect,fit=fit)
    deadline=time.time()+2.0
    while time.time()<deadline:
        current=store.get(job["id"]) or job
        if int(current.get("update_seq",0))>0:
            return current
        await asyncio.sleep(0.05)
    return store.get(job["id"]) or job

@app.get("/api/footage-analyzer/index")
def index_status(root: str):
    p=Path(root).expanduser()
    if not p.exists() or not p.is_dir(): raise HTTPException(400,"Footage folder is not accessible.")
    from .indexer import media_files
    return {**store.cache_status(str(p)),"video_count":len(media_files(p))}

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

    search_roots=_search_roots()

    def file_matches(path, sample):
        try:
            return path.name == sample["name"] and path.is_file() and (
                sample["size"] is None or path.stat().st_size == sample["size"]
            )
        except OSError:
            return False

    match=None

    # Fast path when the browser supplied the selected folder name.
    if folder_name:
        candidates=_find(search_roots, want_dir=folder_name, timeout=8, limit=25)

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
        hits=_find(search_roots, want_file=probe["name"], size=probe["size"], timeout=15)

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
            raise HTTPException(503,"The analyzer cannot see any media roots. Set FOOTAGE_SEARCH_ROOTS or paste the folder path.")
        raise HTTPException(
            404,
            "The analyzer could not locate this folder on disk. Paste its full path instead "
            "(searched: " + ", ".join(str(p) for p in search_roots) + ")."
        )

    video_exts={".mp4",".mov",".mkv",".m4v",".webm",".avi",".mts",".m2ts",".ts"}
    video_count=0
    try:
        for p in match.rglob("*"):
            if p.is_file() and p.suffix.lower() in video_exts and not p.name.startswith("._"):
                video_count += 1
    except OSError:
        pass

    return {
        "path":str(match),
        "folder_name":match.name,
        "video_count":video_count,
        "source":"local_filesystem",
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

def _check_format(aspect,fit):
    from .render import SIZES
    if aspect not in SIZES: raise HTTPException(400,f"aspect must be one of {', '.join(SIZES)}")
    if fit not in {"blur","crop","pad"}: raise HTTPException(400,"fit must be blur, crop or pad")

@app.post("/api/footage-analyzer/jobs/{job_id}/render")
def rerender(job_id:str,payload: dict):
    aspect=str(payload.get("aspect") or "16:9"); fit=str(payload.get("fit") or "blur")
    _check_format(aspect,fit)
    try:
        return store.rerender(job_id,aspect,fit)
    except ValueError as exc:
        raise HTTPException(409,str(exc))

@app.get("/api/footage-analyzer/jobs/{job_id}/video")
def job_video(job_id:str, download: bool=False):
    job=store.get(job_id)
    if not job: raise HTTPException(404,"Job not found")
    path=Path(job.get("video_path") or "")
    if not job.get("video_path") or not path.exists(): raise HTTPException(409,"No rendered video for this job")
    return FileResponse(path,media_type="video/mp4",filename=f"{job_id}.mp4" if download else None)

@app.get("/api/footage-analyzer/jobs/{job_id}/metadata")
def job_metadata(job_id:str):
    job=store.get(job_id)
    if not job: raise HTTPException(404,"Job not found")
    if not job.get("metadata"): raise HTTPException(409,"Metadata is not ready")
    return job["metadata"]

@app.get("/api/footage-analyzer/jobs/{job_id}/edl/download")
def download_edl(job_id:str):
    job=store.get(job_id)
    if not job: raise HTTPException(404,"Job not found")
    if job["status"]!="complete": raise HTTPException(409,"Analysis is not complete")
    return FileResponse(store.root/job_id/"edl.json",filename=f"{job_id}-edl.json",media_type="application/json")
