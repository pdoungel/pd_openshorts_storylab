from __future__ import annotations

import re
import uuid
from typing import Iterable

from .models import Evidence, SourceLocator, TranscriptSegment


def normalize_evidence(items: Iterable[Evidence], duration: float | None = None) -> list[Evidence]:
    """Clamp timed evidence, retaining page-only evidence unchanged.

    An item is traceable only when it names a source and carries quoted support.
    This prevents model prose from becoming a source citation by accident.
    """
    result: list[Evidence] = []
    for item in items:
        update = {}
        if item.start is not None and item.end is not None:
            start = max(0.0, float(item.start)); end = max(start + 0.05, float(item.end))
            if duration is not None:
                start = min(start, max(0.0, duration - 0.05)); end = min(end, duration)
                if end <= start:
                    continue
            update.update(start=round(start, 3), end=round(end, 3))
        elif item.start is not None or item.end is not None:
            update.update(start=None, end=None)
        if item.source_id and item.supporting_text.strip() and (item.page or (item.start is not None and item.end is not None)):
            update["traceability"] = "source"
        else:
            update["traceability"] = "unverified"
        result.append(item.model_copy(update=update))
    return result


def evidence_index(items: Iterable[Evidence]) -> dict[str, Evidence]:
    return {item.id: item for item in items}


def _claim(text: str) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))[0]
    return sentence[:500]


def extract_source_evidence(sources: Iterable[SourceLocator], limit: int = 80) -> list[Evidence]:
    """Create citation records from source segments, never inferred timestamps."""
    evidence = []
    for source in sources:
        segments = source.segments or ([TranscriptSegment(text=source.text, source_id=source.id)] if source.text.strip() else [])
        for segment in segments:
            quote = " ".join(segment.text.split())
            if not quote:
                continue
            evidence.append(Evidence(
                id=f"ev_{uuid.uuid4().hex[:12]}", source_id=source.id, start=segment.start, end=segment.end,
                page=segment.page, label="source excerpt", claim=_claim(quote), supporting_text=quote[:2000],
                detail=quote[:2000], confidence=1.0,
            ))
            if len(evidence) >= limit:
                return normalize_evidence(evidence, source.duration if source.kind in {"video", "audio"} else None)
    return normalize_evidence(evidence)
