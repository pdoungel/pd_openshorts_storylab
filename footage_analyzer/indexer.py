"""Independent local footage shot indexer."""
from pathlib import Path
import hashlib,json,subprocess
VIDEO_EXTS={".mp4",".mov",".mkv",".m4v",".webm",".avi"}
def media_files(root):
    return sorted(p for p in Path(root).expanduser().resolve().rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
def probe_duration(path):
    r=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],capture_output=True,text=True,check=True)
    return float(r.stdout.strip())
def detect_scenes(path):
    try:
        from scenedetect import open_video,SceneManager
        from scenedetect.detectors import ContentDetector
        video=open_video(path); manager=SceneManager(); manager.add_detector(ContentDetector()); manager.detect_scenes(video=video)
        return [(float(a.get_seconds()),float(b.get_seconds())) for a,b in manager.get_scene_list()],float(video.frame_rate)
    except Exception:
        duration=probe_duration(path); return [(0.0,duration)],0.0
def shot_id(path,start,end):
    return hashlib.sha1(("%s|%.6f|%.6f" % (Path(path).resolve(),start,end)).encode()).hexdigest()[:16]
def build_index(root,output,max_files=None):
    files=media_files(root)
    if max_files: files=files[:max_files]
    records=[]
    for path in files:
        scenes,fps=detect_scenes(str(path))
        for start,end in scenes:
            if end>start:
                records.append({"id":shot_id(path,start,end),"video_path":str(path),"start":start,"end":end,"duration":end-start,"fps":fps,"description":"","tags":[]})
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps({"version":2,"root":str(Path(root).expanduser().resolve()),"shots":records},ensure_ascii=False,indent=2))
    return records
