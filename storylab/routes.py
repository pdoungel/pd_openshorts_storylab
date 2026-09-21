from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from .models import StoryProjectCreate
from .service import store
router=APIRouter(prefix="/api/storylab",tags=["storylab"])
class AnalyzeRequest(BaseModel):
    transcript:str=Field(default="",max_length=500000); duration:float|None=Field(default=None,gt=0)
@router.get("/projects")
async def list_projects(): return {"projects":[p.model_dump() for p in store.list()]}
@router.post("/projects")
async def create_project(payload:StoryProjectCreate): return store.create(payload).model_dump()
@router.get("/projects/{project_id}")
async def get_project(project_id:str):
    try:return store.get(project_id).model_dump()
    except FileNotFoundError:raise HTTPException(404,"Story Lab project not found")
    except ValueError:raise HTTPException(400,"Invalid Story Lab project id")
@router.post("/projects/{project_id}/analyze")
async def analyze_project(project_id:str,payload:AnalyzeRequest):
    try:return store.analyze(project_id,payload.transcript,payload.duration).model_dump()
    except FileNotFoundError:raise HTTPException(404,"Story Lab project not found")
    except ValueError:raise HTTPException(400,"Invalid Story Lab project id")
