from __future__ import annotations
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from .analyzer import analyze_story
from .models import StoryProject, StoryProjectCreate
from .script import build_script
class StoryLabStore:
    def __init__(self, output_dir: str = "output"):
        self.root=Path(output_dir).resolve()/"storylab"; self.root.mkdir(parents=True,exist_ok=True)
    def _path(self, project_id: str)->Path:
        if not project_id or Path(project_id).name != project_id: raise ValueError("Invalid Story Lab project id")
        return self.root/f"{project_id}.json"
    def save(self,p:StoryProject)->StoryProject:
        p.updated_at=datetime.now(timezone.utc).isoformat(); self._path(p.id).write_text(p.model_dump_json(indent=2),encoding="utf-8"); return p
    def get(self,project_id:str)->StoryProject:
        path=self._path(project_id)
        if not path.is_file(): raise FileNotFoundError(project_id)
        return StoryProject.model_validate_json(path.read_text(encoding="utf-8"))
    def list(self)->list[StoryProject]:
        out=[]
        for path in self.root.glob("*.json"):
            try: out.append(StoryProject.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception: pass
        return sorted(out,key=lambda p:p.updated_at,reverse=True)
    def create(self,payload:StoryProjectCreate)->StoryProject:
        now=datetime.now(timezone.utc).isoformat(); return self.save(StoryProject(id=str(uuid.uuid4()),title=payload.title.strip(),kind=payload.kind,source_path=payload.source_path,notes=payload.notes,created_at=now,updated_at=now))
    def analyze(self,project_id:str,transcript:str="",duration:Optional[float]=None)->StoryProject:
        p=self.get(project_id); p.status="analyzing"; self.save(p)
        try: p.analysis=analyze_story(p.title,transcript,duration); p.script=build_script(p.analysis); p.status="analyzed"; p.error=None
        except Exception as exc: p.status="error"; p.error=str(exc)
        return self.save(p)
store=StoryLabStore()
