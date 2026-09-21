"""Source ingestion isolated from the Shorts upload and job directories."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import SourceLocator, TranscriptSegment

_KINDS = {
    ".mp4": "video", ".mov": "video", ".mkv": "video", ".webm": "video", ".avi": "video",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".aac": "audio", ".flac": "audio", ".ogg": "audio",
    ".pdf": "pdf", ".srt": "transcript", ".vtt": "transcript", ".json": "transcript",
    ".txt": "text", ".md": "text",
}


def source_kind(name: str) -> str:
    kind = _KINDS.get(Path(name).suffix.lower())
    if not kind:
        raise ValueError("Unsupported Story Lab source. Use video, audio, PDF, transcript, or text.")
    return kind


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ffprobe_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        return max(0.0, float(json.loads(result.stdout)["format"]["duration"]))
    except (FileNotFoundError, subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError):
        return None


def _seconds(value: str) -> float:
    parts = value.strip().replace(",", ".").split(":")
    return sum(float(part) * 60 ** index for index, part in enumerate(reversed(parts)))


def _timed_segments(text: str, source_id: str) -> list[TranscriptSegment]:
    """Parse timed transcript formats defensively.

    One malformed JSON cue must not discard valid cues from the same file.
    WebVTT/SRT timestamps may be HH:MM:SS.mmm or MM:SS.mmm.
    """
    if text.lstrip().startswith("{") or text.lstrip().startswith("["):
        try:
            data = json.loads(text)
            rows = data.get("segments", data) if isinstance(data, dict) else data
            if isinstance(rows, list):
                segments = []
                for row in rows:
                    if not isinstance(row, dict) or not row.get("text"):
                        continue
                    if row.get("start") is None or row.get("end") is None:
                        continue
                    try:
                        start = float(row["start"])
                        end = float(row["end"])
                    except (TypeError, ValueError):
                        continue
                    if start < 0 or end <= start:
                        continue
                    segments.append(
                        TranscriptSegment(
                            text=str(row["text"]).strip(),
                            start=start,
                            end=end,
                            source_id=source_id,
                        )
                    )
                if segments:
                    return segments
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    segments = []
    pattern = re.compile(
        r"(?:^|\n)(?:\d+\s*\n)?"
        r"(\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})\s*-->\s*"
        r"(\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})[^\n]*\n"
        r"(.*?)(?=\n\s*\n|\Z)",
        re.S,
    )
    for match in pattern.finditer(text):
        words = " ".join(match.group(3).split())
        if not words:
            continue
        try:
            start = _seconds(match.group(1))
            end = _seconds(match.group(2))
        except ValueError:
            continue
        if end <= start:
            continue
        segments.append(
            TranscriptSegment(
                text=words,
                start=start,
                end=end,
                source_id=source_id,
            )
        )
    return segments


def _plain_segments(text: str, source_id: str, page: int | None = None) -> list[TranscriptSegment]:
    return [TranscriptSegment(text=" ".join(part.split()), page=page, source_id=source_id)
            for part in re.split(r"\n\s*\n", text) if part.strip()]


def ingest_file(path: str | Path, *, source_name: str | None = None, transcribe: bool = False) -> SourceLocator:
    """Read a local, Story Lab-owned source; no external URLs or Shorts state."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    kind = source_kind(source_name or path.name)
    source_id = f"src_{uuid.uuid4().hex[:12]}"
    text, segments, page_count, duration = "", [], None, None
    if kind in {"text", "transcript"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        segments = _timed_segments(text, source_id) if kind == "transcript" else []
        if not segments:
            segments = _plain_segments(text, source_id)
    elif kind == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF ingestion requires pypdf. Install it to analyze PDF sources.") from exc
        reader = PdfReader(str(path)); page_count = len(reader)
        pages = [(number, page.extract_text() or "") for number, page in enumerate(reader.pages, 1)]
        text = "\n\n".join(page for _, page in pages)
        segments = [segment for number, page in pages for segment in _plain_segments(page, source_id, number)]
    else:
        duration = _ffprobe_duration(path)
        if transcribe:
            import transcribe_backends
            transcript = transcribe_backends.transcribe_media_local(str(path))
            text = transcript.get("text", "")
            segments = []
            for row in transcript.get("segments", []):
                if not row.get("text") or row.get("start") is None or row.get("end") is None:
                    continue
                try:
                    start = max(0.0, float(row["start"]))
                    end = max(start + 0.05, float(row["end"]))
                    segments.append(TranscriptSegment(text=row["text"].strip(), start=start, end=end, source_id=source_id))
                except (TypeError, ValueError):
                    continue
    return SourceLocator(id=source_id, name=source_name or path.name, kind=kind, path=str(path.resolve()),
                         mime_type=mimetypes.guess_type(path.name)[0], page_count=page_count, duration=duration,
                         text=text, segments=segments, checksum=_hash(path), created_at=_stamp())
