"""Persistent, resumable per-file footage shot indexer."""
from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path
from .cache import atomic_json, file_fingerprint

VIDEO_EXTS={".mp4",".mov",".mkv",".m4v",".webm",".avi"}
IGNORED_NAMES={".DS_Store"}
IGNORED_PREFIXES=("._",)

def media_files(root):
    base=Path(root).expanduser().resolve()
    return sorted(p for p in base.rglob("*") if p.is_file()
                  and p.name not in IGNORED_NAMES
                  and not p.name.startswith(IGNORED_PREFIXES)
                  and p.suffix.lower() in VIDEO_EXTS)

def probe_duration(path):
    r=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                      "-of","default=noprint_wrappers=1:nokey=1",str(path)],
                     capture_output=True,text=True,check=True)
    value=r.stdout.strip()
    if not value: raise RuntimeError("ffprobe returned no duration")
    return float(value)

def detect_scenes(path):
    try:
        from scenedetect import open_video,SceneManager
        from scenedetect.detectors import ContentDetector
        video=open_video(path); manager=SceneManager()
        manager.add_detector(ContentDetector()); manager.detect_scenes(video=video)
        return [(float(a.get_seconds()),float(b.get_seconds())) for a,b in manager.get_scene_list()],float(video.frame_rate)
    except Exception:
        duration=probe_duration(path)
        return [(0.0,duration)],0.0

def shot_id(path,start,end):
    return hashlib.sha1(("%s|%.6f|%.6f" % (Path(path).resolve(),start,end)).encode()).hexdigest()[:16]

def _load(path):
    if not path.exists(): return {}
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return {}

def build_index(root,output,max_files=None,progress=None):
    output_path=Path(output); manifest_path=output_path.with_name("file_manifest.json")
    previous=_load(manifest_path)
    old_index=_load(output_path)
    old_shots={s.get("id"):s for s in old_index.get("shots",[])}
    # A prior non-manifest index is treated as completed data, preserving existing analyses.
    if not previous:
        for s in old_index.get("shots",[]):
            previous.setdefault(str(Path(s["video_path"]).resolve()), {
                "fingerprint": None, "status":"complete", "shots":[s], "error":None
            })

    files=media_files(root)
    if max_files: files=files[:max_files]
    records=[]; stats={"total":len(files),"reused":0,"processed":0,"failed":0,"pending":0}
    seen=set()

    for number,path in enumerate(files,1):
        key=str(path.resolve()); seen.add(key)
        fp=file_fingerprint(path); entry=previous.get(key,{})
        unchanged=entry.get("fingerprint")==fp and entry.get("status")=="complete"
        # Old entries without fingerprints are reusable when they contain shots.
        legacy_reusable=entry.get("fingerprint") is None and entry.get("shots")
        if unchanged or legacy_reusable:
            shots=entry.get("shots") or [s for s in old_shots.values() if s.get("video_path")==key]
            records.extend(shots); stats["reused"]+=1
            if progress: progress(number-1,len(files),path.name,stats)
            continue

        entry={"fingerprint":fp,"status":"processing","shots":[],"error":None}
        previous[key]=entry
        atomic_json(manifest_path,previous)
        if progress: progress(number-1,len(files),path.name,stats)
        try:
            scenes,fps=detect_scenes(str(path))
            shots=[]
            for start,end in scenes:
                if end>start:
                    shots.append({"id":shot_id(path,start,end),"video_path":key,"start":start,
                                  "end":end,"duration":end-start,"fps":fps,
                                  "description":"","tags":[]})
            entry.update({"fingerprint":fp,"status":"complete","shots":shots,"error":None})
            previous[key]=entry
            atomic_json(manifest_path,previous)
            records.extend(shots); stats["processed"]+=1
        except Exception as exc:
            entry.update({"fingerprint":fp,"status":"failed","shots":[],"error":str(exc)})
            previous[key]=entry; stats["failed"]+=1
            atomic_json(manifest_path,previous)
            if progress: progress(number,len(files),f"Failed {path.name} · {exc}",stats)
            continue
        if progress: progress(number,len(files),path.name,stats)

    # Files removed from the folder are not deleted from history, so a temporary
    # unplug/reconnect cannot destroy completed analysis. They simply disappear
    # from this run's active shot set.
    active={k for k in seen}
    for key,entry in previous.items():
        if key not in active and entry.get("status")=="processing":
            entry["status"]="pending"
    index={"version":3,"root":str(Path(root).expanduser().resolve()),
           "shots":records,"files_seen":len(files),"files_skipped":stats["reused"],
           "stats":stats}
    atomic_json(output_path,index)
    return records
