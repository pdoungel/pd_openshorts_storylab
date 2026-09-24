"""Durable per-footage-library cache used by Footage Analyzer."""
from __future__ import annotations
import hashlib, json, os, shutil, tempfile, time
from pathlib import Path

def replace_file(src, dst, attempts=20) -> None:
    # Windows refuses to replace a file another handle (a reader, antivirus, the
    # search indexer) has open; those locks are brief, so retry instead of failing.
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.05 * (i + 1))

def root_key(root: str) -> str:
    return hashlib.sha256(str(Path(root).expanduser().resolve()).encode()).hexdigest()[:24]

def atomic_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
            f.flush(); os.fsync(f.fileno())
        replace_file(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def file_fingerprint(path: Path) -> dict:
    st=path.stat()
    return {"size":int(st.st_size),"mtime_ns":int(st.st_mtime_ns)}

def cache_dir(workdir: Path, root: str) -> Path:
    return workdir/"library"/root_key(root)

def cache_size(path: Path) -> int:
    total=0
    if not path.exists(): return 0
    for p in path.rglob("*"):
        try:
            if p.is_file(): total += p.stat().st_size
        except OSError: pass
    return total

def human_size(n: int) -> str:
    value=float(n)
    for unit in ("B","KB","MB","GB","TB"):
        if value < 1024 or unit=="TB":
            return f"{int(value)} B" if unit=="B" else f"{value:.1f} {unit}"
        value/=1024
    return f"{value:.1f} TB"

def seed_from_job(cache: Path, job_dir: Path) -> None:
    cache.mkdir(parents=True,exist_ok=True)
    for name in ("footage_index.json","visual_index.json"):
        src=job_dir/name; dst=cache/name
        if src.exists() and not dst.exists():
            shutil.copy2(src,dst)

def clear_cache(workdir: Path, root: str) -> dict:
    path=cache_dir(workdir,root)
    size=cache_size(path)
    if path.exists(): shutil.rmtree(path)
    return {"cleared_bytes":size,"cleared_size":human_size(size),"path":str(path)}
