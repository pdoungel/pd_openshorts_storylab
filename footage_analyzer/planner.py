"""Convert narration into concrete visual requirements."""
from __future__ import annotations
import json, os
from pathlib import Path
from pydantic import BaseModel, Field

class VisualRequirement(BaseModel):
    narration_index:int
    visual_query:str
    preferred_visuals:list[str]=Field(default_factory=list)
    avoid:list[str]=Field(default_factory=list)
    rationale:str=""

class VisualPlan(BaseModel):
    requirements:list[VisualRequirement]=Field(default_factory=list)

def plan(narrations:list[dict])->list[dict]:
    from google import genai
    key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key: raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY.")
    client=genai.Client(api_key=key)
    payload=[{"index":n["index"],"start":n["start"],"end":n["end"],"text":n["text"]} for n in narrations]
    prompt=("You are a documentary visual editor. For every narration segment, describe what the viewer should see, "
            "not merely what the narrator says. Prefer concrete visible subjects, actions, places, documents, maps, "
            "archival photographs, or contextual imagery. Do not invent evidence. Return JSON with requirements, where "
            "each item has narration_index, visual_query, preferred_visuals, avoid, rationale. Cover every input segment. "
            "INPUT NARRATION:\n"+json.dumps(payload,ensure_ascii=False))
    response=client.models.generate_content(model=os.getenv("FOOTAGE_PLANNER_MODEL","gemini-2.5-flash"),contents=prompt)
    from gemini_worker import _parse_json_response_text
    parsed=VisualPlan.model_validate(_parse_json_response_text(getattr(response,"text","") or ""))
    return [x.model_dump() for x in parsed.requirements]

def save_plan(requirements:list[dict],output:str):
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps({"version":1,"requirements":requirements},ensure_ascii=False,indent=2),encoding="utf-8")
