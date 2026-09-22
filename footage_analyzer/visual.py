"""Independent sampled-frame visual enrichment."""
from __future__ import annotations
import json,os,subprocess
from io import BytesIO
from PIL import Image
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
    w=max(x.width for x in frames); h=max(x.height for x in frames); sheet=Image.new("RGB",(w*2,h*((len(frames)+1)//2)),"white")
    for i,im in enumerate(frames): sheet.paste(im,((i%2)*w,(i//2)*h))
    return sheet
def describe_shot(path,start,end):
    from google import genai
    key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key: raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY.")
    sheet=sample_frames(path,start,end)
    prompt=("Inspect every panel in this footage contact sheet. Return JSON with description, subjects, actions, setting, visual_style, text_visible, tags. "
            "Describe only visible evidence; do not infer identity, date, event, location, or historical facts.")
    r=genai.Client(api_key=key).models.generate_content(model=os.getenv("FOOTAGE_VISION_MODEL","gemini-2.5-flash"),contents=[prompt,sheet])
    data=_json(getattr(r,"text",""))
    for k in ("subjects","actions","setting","visual_style","text_visible","tags"):
        v=data.get(k,[]); data[k]=v if isinstance(v,list) else [str(v)]
    data["description"]=str(data.get("description","")).strip(); return data
def enrich_index(index_path,output_path,progress=None,limit=None):
    data=json.loads(open(index_path,encoding="utf-8").read()); old={}
    if os.path.exists(output_path):
        try: old={s["id"]:s for s in json.load(open(output_path,encoding="utf-8")).get("shots",[])}
        except Exception: pass
    shots=data.get("shots",[]); total=min(len(shots),limit) if limit else len(shots); done=0
    for shot in shots:
        if limit is not None and done>=limit: break
        if shot["id"] in old and old[shot["id"]].get("description"): shot.update(old[shot["id"]])
        else: shot.update(describe_shot(shot["video_path"],shot["start"],shot["end"]))
        done+=1
        if progress: progress(done,total)
    data["version"]=3; open(output_path,"w",encoding="utf-8").write(json.dumps(data,ensure_ascii=False,indent=2)); return data
