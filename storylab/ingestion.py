"""Source ingestion isolated from the Shorts upload and job directories."""
from __future__ import annotations

import hashlib
import html
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


def _clean_subtitle_text(value: str) -> str:
    """Normalize subtitle markup so HTML/ASS-style tags never reach Story Lab."""
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\{[^}]+\}", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _is_lyric_like(text: str) -> bool:
    """Reject subtitle cues that look like songs/karaoke rather than dialogue."""
    text = _clean_subtitle_text(text)
    if not text:
        return True
    tokens = text.split()
    alpha = re.sub(r"[^A-Za-z]", "", text)
    # Musical-note markers and explicit karaoke formatting are strong signals.
    if re.search(r"(?:♪|♫|♬|🎵|🎶)", text):
        return True
    if re.search(r"\\(?:k|K|ko|Kf|\<|\>)\\d+", text):
        return True
    # Karaoke/lyric lines tend to be short fragments without sentence punctuation.
    if 1 <= len(tokens) <= 8 and not re.search(r"[.!?]", text):
        lyric_words = {"yeah","la","laa","na","naa","oh","ooh","ah","aah","hey","whoa"}
        if any(t.lower().strip(".,!?-") in lyric_words for t in tokens):
            return True
    # A subtitle made almost entirely of one-character lyric tokens is a common
    # karaoke pattern (e.g. spaced syllables/notes).
    if len(tokens) >= 8:
        single_char_tokens = sum(1 for token in tokens if len(re.sub(r"[^A-Za-z]", "", token)) <= 1)
        if single_char_tokens / len(tokens) >= 0.65:
            return True
    return False


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
                    cleaned = _clean_subtitle_text(str(row["text"]))
                    if not cleaned or _is_lyric_like(cleaned):
                        continue
                    segments.append(
                        TranscriptSegment(
                            text=cleaned,
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
        words = _clean_subtitle_text(match.group(3))
        if not words or _is_lyric_like(words):
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


def _embedded_english_subtitles(path: Path, source_id: str) -> tuple[str, list[TranscriptSegment]] | None:
    """Extract an embedded English subtitle stream when media provides one."""
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "s",
             "-show_entries", "stream=index:stream_tags=language,title",
             "-of", "json", str(path)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        streams = json.loads(probe.stdout).get("streams", [])
    except (FileNotFoundError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return None
    candidates = []
    for stream in streams:
        tags = stream.get("tags") or {}
        language = str(tags.get("language") or "").strip().lower()
        title = str(tags.get("title") or "").strip().lower()
        score = 0
        if language in {"eng", "en", "english"}:
            score += 10
        if "english" in title or re.search(r"\beng\b", title):
            score += 5
        if score:
            candidates.append((score, int(stream.get("index", -1))))
    candidates.sort(reverse=True)
    for _, stream_index in candidates:
        if stream_index < 0:
            continue
        try:
            extracted = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path),
                 "-map", f"0:{stream_index}", "-c:s", "srt", "-f", "srt", "pipe:1"],
                check=True, capture_output=True, text=True, timeout=120,
            )
            subtitle_text = extracted.stdout.strip()
            if not subtitle_text:
                continue
            segments = _timed_segments(subtitle_text, source_id)
            if segments:
                return "\n".join(segment.text for segment in segments), segments
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
    return None


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
        if segments:
            text = "\n".join(segment.text for segment in segments)
        else:
            text = _clean_subtitle_text(text)
        ingestion_source = "uploaded_transcript" if kind == "transcript" else "uploaded_text"
        ingestion_source = "uploaded_transcript" if kind == "transcript" else "uploaded_text"
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
        ingestion_source = "uploaded_pdf"
    else:
        duration = _ffprobe_duration(path)
        ingestion_source = "uploaded_media"
        embedded = _embedded_english_subtitles(path, source_id)
        if embedded:
            text, segments = embedded
            ingestion_source = "embedded_english_subtitles"
        elif transcribe:
            import transcribe_backends
            transcript = transcribe_backends.transcribe_media_local(str(path))
            text = transcript.get("text", "")
            segments = []
            ingestion_source = "local_asr"
            for row in transcript.get("segments", []):
                if not row.get("text") or row.get("start") is None or row.get("end") is None:
                    continue
                try:
                    start = max(0.0, float(row["start"]))
                    end = max(start + 0.05, float(row["end"]))
                    cleaned = _clean_subtitle_text(str(row["text"]))
                    if not cleaned or _is_lyric_like(cleaned):
                        continue
                    segments.append(TranscriptSegment(text=cleaned, start=start, end=end, source_id=source_id))
                except (TypeError, ValueError):
                    continue
    return SourceLocator(id=source_id, name=source_name or path.name, kind=kind, path=str(path.resolve()),
                         mime_type=mimetypes.guess_type(path.name)[0], page_count=page_count, duration=duration,
                         text=text, segments=segments, checksum=_hash(path), ingestion_source=ingestion_source, created_at=_stamp())
