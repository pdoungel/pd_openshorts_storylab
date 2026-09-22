"""Visual enrichment for indexed shots using representative frames + Gemini Vision."""
from __future__ import annotations
import io, json, os, subprocess
from pathlib import Path
from PIL import Image, ImageDraw

def _frame(path: str, seconds: float) -> Image.Image:
    cmd = ["ffmpeg","-nostdin","-ss",str(max(0.0,seconds)),"-i",path,"-frames:v","1","-vf","scale=640:-2","-f","image2pipe","-vcodec","png","-"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=60)
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")

def contact_sheet(path: str, start: float, end: float) -> Image.Image:
    d=max(0.05,end-start); times=[start+d*0.2,start+d*0.5,start+d*0.8]
    frames=[_frame(path,t) for t in times]; w=640; h=max(x.height for x in frames)
    sheet=Image.new("RGB",(w,h*3),"white"); draw=ImageDraw.Draw(sheet)
    for i,im in enumerate(frames):
        sheet.paste(im,(0,i*h)); draw.rectangle((0,i*h,180,i*h+24),fill="black"); draw.text((6,i*h+5),f"frame {i+1}",fill="white")
    return sheet

def _client():
    from google import genai
    key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key: raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY.")
    return genai.Client(api_key=key)

def describe_shot(path: str, start: float, end: float, model: str|None=None) -> dict:
    client=_client(); sheet=contact_sheet(path,start,end)
    prompt=("You are indexing footage for a documentary editor. Inspect every frame in this contact sheet. "
            "Return JSON with description, subjects, actions, setting, visual_style, text_visible, tags. "
            "Describe ONLY visible evidence. Do not infer identity, date, event, location, or historical facts "
            "not visually established. Use empty arrays when absent.")
    response=client.models.generate_content(model=model or os.getenv("FOOTAGE_VISION_MODEL","gemini-2.5-flash"),contents=[prompt,sheet])
    from gemini_worker import _parse_json_response_text
    data=_parse_json_response_text(getattr(response,"text","") or "")
    for k in ("subjects","actions","setting","visual_style","text_visible","tags"):
        v=data.get(k,[]); data[k]=v if isinstance(v,list) else [str(v)]
    data["description"]=str(data.get("description","")).strip()
    return data

def enrich_index(index_path: str, output_path: str|None=None, limit: int|None=None) -> dict:
    source=Path(index_path); data=json.loads(source.read_text(encoding="utf-8")); target=Path(output_path or index_path)
    old={}
    if target.exists():
        try: old={s["id"]:s for s in json.loads(target.read_text(encoding="utf-8")).get("shots",[])}
        except Exception: pass
    count=0
    for shot in data.get("shots",[]):
        cached=old.get(shot["id"])
        if cached and cached.get("description"):
            shot.update(cached); continue
        if limit is not None and count>=limit: continue
        print(f"Visual analysis: {shot['video_path']} {shot['start']:.2f}-{shot['end']:.2f}",flush=True)
        shot.update(describe_shot(shot["video_path"],shot["start"],shot["end"])); count+=1
    target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Enriched {count} shots; saved {target}"); return data
