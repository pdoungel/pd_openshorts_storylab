"""Persistent sampled-frame visual enrichment."""
from __future__ import annotations
import json,os,subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from PIL import Image
from .cache import atomic_json

def _json(text):
    text=(text or "").strip()
    if text.startswith("```"): text=text.replace("```json","",1).replace("```","").strip()
    try: return json.loads(text)
    except Exception:
        a=text.find("{"); b=text.rfind("}")
        if a<0 or b<=a: raise ValueError("Gemini did not return valid JSON")
        return json.loads(text[a:b+1])

def sample_frames(path,start,end,count=4):
    duration=max(.01,float(end)-float(start)); frames=[]
    for i in range(count):
        t=float(start)+duration*((i+.5)/count)
        p=subprocess.run(["ffmpeg","-nostdin","-loglevel","error","-ss",str(t),"-i",path,"-frames:v","1","-vf","scale=640:-1","-f","image2pipe","-vcodec","png","pipe:1"],capture_output=True,check=True,timeout=90)
        frames.append(Image.open(BytesIO(p.stdout)).convert("RGB"))
    w=max(x.width for x in frames); h=max(x.height for x in frames)
    sheet=Image.new("RGB",(w*2,h*((len(frames)+1)//2)),"white")
    for i,im in enumerate(frames): sheet.paste(im,((i%2)*w,(i//2)*h))
    return sheet

def describe_shot(path,start,end):
    from google import genai
    key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key: raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY.")
    sheet=sample_frames(path,start,end)
    prompt=("Inspect every panel in this footage contact sheet. Return JSON with description, subjects, actions, setting, visual_style, text_visible, tags. "
            "Describe only visible evidence; do not infer identity, date, event, location, or historical facts.")
    last_error=None
    for attempt in range(2):
        try:
            client=genai.Client(api_key=key)
            r=client.models.generate_content(model=os.getenv("FOOTAGE_VISION_MODEL","gemini-2.5-flash"),contents=[prompt,sheet])
            data=_json(getattr(r,"text",""))
            break
        except Exception as exc:
            last_error=exc
            if "client has been closed" not in str(exc).lower() or attempt==1:
                raise
    else:
        raise last_error
    for k in ("subjects","actions","setting","visual_style","text_visible","tags"):
        v=data.get(k,[]); data[k]=v if isinstance(v,list) else [str(v)]
    data["description"]=str(data.get("description","")).strip()
    if not data["description"]: raise ValueError("Gemini returned an empty description")
    return data

def enrich_index(index_path,output_path,progress=None,limit=None):
    data=json.loads(Path(index_path).read_text(encoding="utf-8"))
    output=Path(output_path); manifest_path=output.with_name("visual_manifest.json")
    old={}
    if output.exists():
        try: old={s["id"]:s for s in json.loads(output.read_text(encoding="utf-8")).get("shots",[])}
        except Exception: old={}
    manifest={}
    if manifest_path.exists():
        try: manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception: manifest={}
    shots=data.get("shots",[])
    work=shots[:limit] if limit is not None else shots
    total=len(work); done=0; reused=0; failed=0
    pending=[]
    for shot in work:
        sid=shot["id"]; existing=old.get(sid,{})
        if existing.get("description"):
            shot.update(existing); reused+=1; done+=1
            if progress:
                progress(done,total,
                         f"{Path(shot["video_path"]).name} · {shot["start"]:.1f}–{shot["end"]:.1f}s",
                         {"reused":reused,"failed":failed})
        else:
            manifest[sid]={"status":"processing","video_path":shot["video_path"],
                           "start":shot["start"],"end":shot["end"]}
            pending.append(shot)
    atomic_json(manifest_path,manifest)

    workers=max(1,min(int(os.getenv("FOOTAGE_VISUAL_WORKERS","3")),6))
    def analyze(shot):
        return describe_shot(shot["video_path"],shot["start"],shot["end"])

    # Visual analysis is network-bound (frame extraction + Gemini request), so
    # process a few independent shots concurrently. Results are persisted after
    # every completed shot; a crash therefore never loses the completed work.
    if pending:
        with ThreadPoolExecutor(max_workers=workers,thread_name_prefix="visual-shot") as pool:
            futures={pool.submit(analyze,shot):shot for shot in pending}
            for future in as_completed(futures):
                shot=futures[future]; sid=shot["id"]
                try:
                    shot.update(future.result())
                    manifest[sid]={"status":"complete","video_path":shot["video_path"],
                                   "start":shot["start"],"end":shot["end"]}
                except Exception as exc:
                    failed+=1
                    manifest[sid]={"status":"failed","video_path":shot["video_path"],
                                   "start":shot["start"],"end":shot["end"],"error":str(exc)}
                done+=1
                atomic_json(manifest_path,manifest)
                data["shots"]=shots; data["version"]=4
                atomic_json(output,data)
                if progress:
                    progress(done,total,
                             f"{Path(shot["video_path"]).name} · {shot["start"]:.1f}–{shot["end"]:.1f}s",
                             {"reused":reused,"failed":failed})

    by_id={s["id"]:s for s in data.get("shots",[])}
    for sid,s in old.items():
        if s.get("description"): by_id.setdefault(sid,s)
    data["shots"]=list(by_id.values()); data["version"]=4
    atomic_json(output,data)
    return data
