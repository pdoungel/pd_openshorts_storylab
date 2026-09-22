"""Independent Gemini visual-intent planner."""
from __future__ import annotations
import json,os
def _json(text):
    text=(text or "").strip()
    if text.startswith("```"): text=text.replace("```json","",1).replace("```","").strip()
    try: return json.loads(text)
    except Exception:
        a=text.find("{"); b=text.rfind("}")
        if a<0 or b<=a: raise ValueError("Gemini did not return valid JSON")
        return json.loads(text[a:b+1])
def plan(narrations,instruction=""):
    from google import genai
    key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key: raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY.")
    payload=[{"index":n["index"],"start":n["start"],"end":n["end"],"text":n["text"]} for n in narrations]
    prompt=("Convert every narration segment into visual intent for matching against real footage. Do not treat visual_query as an exact search string. "
            "Describe concrete visible subjects, actions, environments, objects, documents, maps and contextual imagery. Prefer related footage when exact footage is absent. "
            "Never invent evidence. Return JSON with requirements, each containing narration_index, visual_query, preferred_visuals, avoid, rationale. Cover every segment. "
            "Editorial direction: "+(instruction or "none")+"\nINPUT:\n"+json.dumps(payload,ensure_ascii=False))
    response=genai.Client(api_key=key).models.generate_content(model=os.getenv("FOOTAGE_PLANNER_MODEL","gemini-2.5-flash"),contents=prompt)
    data=_json(getattr(response,"text","")); return data.get("requirements",[]) if isinstance(data,dict) else []
