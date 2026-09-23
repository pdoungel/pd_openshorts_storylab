"""Independent local footage shot indexer."""
from pathlib import Path
import hashlib,json,subprocess

VIDEO_EXTS={".mp4",".mov",".mkv",".m4v",".webm",".avi"}
IGNORED_NAMES={".DS_Store"}
IGNORED_PREFIXES=("._",)

def media_files(root):
    base=Path(root).expanduser().resolve()
    return sorted(
        p for p in base.rglob("*")
        if p.is_file()
        and p.name not in IGNORED_NAMES
        and not p.name.startswith(IGNORED_PREFIXES)
        and p.suffix.lower() in VIDEO_EXTS
    )

def probe_duration(path):
    r=subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration",
         "-of","default=noprint_wrappers=1:nokey=1",str(path)],
        capture_output=True,text=True,check=True
    )
    value=r.stdout.strip()
    if not value:
        raise RuntimeError("ffprobe returned no duration")
    return float(value)

def detect_scenes(path):
    try:
        from scenedetect import open_video,SceneManager
        from scenedetect.detectors import ContentDetector
        video=open_video(path)
        manager=SceneManager()
        manager.add_detector(ContentDetector())
        manager.detect_scenes(video=video)
        return [(float(a.get_seconds()),float(b.get_seconds())) for a,b in manager.get_scene_list()],float(video.frame_rate)
    except Exception:
        duration=probe_duration(path)
        return [(0.0,duration)],0.0

def shot_id(path,start,end):
    return hashlib.sha1(("%s|%.6f|%.6f" % (Path(path).resolve(),start,end)).encode()).hexdigest()[:16]

def build_index(root,output,max_files=None,progress=None):
    files=media_files(root)
    if max_files:
        files=files[:max_files]
    records=[]
    total=len(files)
    skipped=0
    for number,path in enumerate(files,1):
        if progress:
            progress(number-1,total,path.name)
        try:
            scenes,fps=detect_scenes(str(path))
            for start,end in scenes:
                if end>start:
                    records.append({
                        "id":shot_id(path,start,end),
                        "video_path":str(path),
                        "start":start,
                        "end":end,
                        "duration":end-start,
                        "fps":fps,
                        "description":"",
                        "tags":[]
                    })
        except Exception as exc:
            skipped+=1
            if progress:
                progress(number,total,f"Skipped {path.name} · {exc}")
            continue
        if progress:
            progress(number,total,path.name)
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(
        json.dumps({
            "version":2,
            "root":str(Path(root).expanduser().resolve()),
            "shots":records,
            "files_seen":total,
            "files_skipped":skipped
        },ensure_ascii=False,indent=2)
    )
    return records
