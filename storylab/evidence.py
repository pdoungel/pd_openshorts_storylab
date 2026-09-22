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


def _is_lyric_like(text: str) -> bool:
    """Return True for song/lyric material, including OCR/ASR-corrupted lyrics.

    Subtitle extraction can produce character-spaced text such as
    "t s u n a g a r u ...". Those cues are especially common in karaoke/
    opening sequences and otherwise bypass normal lyric-word heuristics.
    """
    value = " ".join(text.split()).strip()
    if not value:
        return True

    tokens = value.split()
    lowered = value.lower()

    if re.search(r"(?:♪|♫|♬|🎵|🎶)", value):
        return True
    if re.search(r"(^|\s)(\[?(music|instrumental|singing|sings|song|lyrics|chorus|verse|refrain|opening|ending)\]?)(\s|$)", lowered):
        return True
    if re.search(r"(^|\s)(la+|na+|oh+|ah+|yeah+|ooh+|woo+)([!.,]?\s|$)", lowered) and len(tokens) <= 12:
        return True

    # Character-spaced subtitle/OCR output is not useful source dialogue. A high
    # proportion of one-character alphabetic tokens is a strong signal, while
    # retaining ordinary short dialogue with normal word spacing.
    if len(tokens) >= 8:
        alpha_tokens = [re.sub(r"[^A-Za-z]", "", token) for token in tokens]
        single_char = sum(len(token) == 1 for token in alpha_tokens)
        if single_char / max(1, len(alpha_tokens)) >= 0.65:
            return True

    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ']+", lowered)
    if len(words) < 3:
        return False

    # Collapse duplicated subtitle payloads before judging them. Some embedded
    # subtitle tracks repeat the same cue twice in one text field.
    compact = re.sub(r"[^a-z0-9]+", "", lowered)
    if len(compact) >= 40 and len(compact) % 2 == 0:
        half = len(compact) // 2
        if compact[:half] == compact[half:]:
            return True

    # Repeated short phrases are a strong signal of a refrain.
    tokens = [word for word in words if len(word) > 1]
    if len(tokens) >= 6:
        half = max(3, len(tokens) // 2)
        if " ".join(tokens[:half]) == " ".join(tokens[-half:]):
            return True

    filler = {"la", "na", "oh", "ah", "ooh", "woo", "yeah", "hey"}
    filler_count = sum(1 for word in words if word in filler)
    return len(words) >= 4 and filler_count / len(words) >= 0.5


def _merge_timed_segments(segments: list[TranscriptSegment], max_gap: float = 1.5, max_window: float = 18.0) -> list[TranscriptSegment]:
    """Turn subtitle/ASR cues into meaningful dialogue windows.

    Story Lab should cite a short scene of dialogue, not every subtitle cue as a
    separate piece of evidence. Adjacent cues are merged until there is a real
    pause or the evidence window becomes long enough to be unwieldy.
    """
    timed = sorted(
        [item for item in segments if item.start is not None and item.end is not None],
        key=lambda item: (item.start or 0.0, item.end or 0.0),
    )
    merged: list[TranscriptSegment] = []
    for item in timed:
        text = " ".join(item.text.split())
        if not text:
            continue
        if not merged:
            merged.append(TranscriptSegment(text=text, start=item.start, end=item.end, source_id=item.source_id))
            continue
        current = merged[-1]
        gap = max(0.0, float(item.start or 0.0) - float(current.end or 0.0))
        span = float(item.end or 0.0) - float(current.start or 0.0)
        if gap <= max_gap and span <= max_window:
            current.text = f"{current.text} {text}".strip()
            current.end = item.end
        else:
            merged.append(TranscriptSegment(text=text, start=item.start, end=item.end, source_id=item.source_id))
    return merged


def extract_source_evidence(sources: Iterable[SourceLocator], limit: int = 80) -> list[Evidence]:
    """Create source-grounded evidence while avoiding lyric/karaoke noise and subtitle-level fragmentation."""
    evidence = []
    for source in sources:
        # A source explicitly identified as lyrics/karaoke is not documentary evidence.
        source_name = (source.name or "").lower()
        if re.search(r"(^|[\s._-])(lyrics?|karaoke|opening|ending|ost|song)([\s._-]|$)", source_name):
            continue

        segments = source.segments or (
            [TranscriptSegment(text=source.text, source_id=source.id)]
            if source.text.strip() else []
        )
        if source.kind in {"video", "audio"}:
            segments = _merge_timed_segments(segments)
        for segment in segments:
            quote = " ".join(segment.text.split())
            if not quote or _is_lyric_like(quote):
                continue
            evidence.append(Evidence(
                id=f"ev_{uuid.uuid4().hex[:12]}", source_id=source.id,
                start=segment.start, end=segment.end, page=segment.page,
                label="source dialogue / narration" if segment.start is not None else "source excerpt",
                claim=_claim(quote), supporting_text=quote[:2000],
                detail=quote[:2000], confidence=1.0,
            ))
            if len(evidence) >= limit:
                return normalize_evidence(
                    evidence,
                    source.duration if source.kind in {"video", "audio"} else None,
                )
    return normalize_evidence(evidence)
