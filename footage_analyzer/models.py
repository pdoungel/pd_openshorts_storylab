from dataclasses import dataclass, asdict
from typing import Optional

@dataclass
class NarrationSegment:
    index: int
    start: float
    end: float
    text: str

@dataclass
class Shot:
    id: str
    video_path: str
    start: float
    end: float
    duration: float
    thumbnail_path: Optional[str] = None
    description: str = ""
    tags: tuple = ()

@dataclass
class Match:
    narration_index: int
    shot_id: str
    score: float
    reason: str

@dataclass
class TimelineClip:
    timeline_start: float
    timeline_end: float
    source_path: str
    source_start: float
    source_end: float
    narration_index: int
    score: float
    reason: str

def to_dict(obj):
    return asdict(obj)
