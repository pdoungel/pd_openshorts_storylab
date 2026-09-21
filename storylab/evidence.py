from __future__ import annotations
from typing import Iterable
from .models import Evidence
def normalize_evidence(items: Iterable[Evidence], duration: float | None = None) -> list[Evidence]:
    result: list[Evidence] = []
    for item in items:
        start = max(0.0, float(item.start)); end = max(start + 0.05, float(item.end))
        if duration is not None:
            start = min(start, max(0.0, duration - 0.05)); end = min(end, duration)
            if end <= start: continue
        result.append(item.model_copy(update={"start": round(start, 3), "end": round(end, 3)}))
    return result
def evidence_index(items: Iterable[Evidence]) -> dict[str, Evidence]:
    return {item.id: item for item in items}
