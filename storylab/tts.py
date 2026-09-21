from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .models import StoryProject


DEFAULT_VOICEBOX_URL = os.getenv("STORYLAB_VOICEBOX_URL", "http://host.docker.internal:17493")


class VoiceboxError(RuntimeError):
    pass


def _url(path: str) -> str:
    return DEFAULT_VOICEBOX_URL.rstrip("/") + "/" + path.lstrip("/")


def _request_json(path: str, method: str = "GET", payload: dict | None = None, timeout: int = 30):
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(_url(path), data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise VoiceboxError(f"Voicebox HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise VoiceboxError(f"Voicebox is not reachable at {DEFAULT_VOICEBOX_URL}.") from exc


def _request_bytes(path: str, timeout: int = 300) -> bytes:
    request = urllib.request.Request(_url(path), headers={"Accept": "audio/wav,audio/*,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise VoiceboxError(f"Voicebox audio HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise VoiceboxError(f"Voicebox audio is not reachable at {DEFAULT_VOICEBOX_URL}.") from exc


def voicebox_status() -> dict:
    try:
        health = _request_json("/health", timeout=5)
        return {"available": True, "url": DEFAULT_VOICEBOX_URL, "health": health}
    except VoiceboxError as exc:
        return {"available": False, "url": DEFAULT_VOICEBOX_URL, "error": str(exc)}


def voicebox_profiles() -> list[dict]:
    payload = _request_json("/profiles", timeout=10)
    if isinstance(payload, dict) and "profiles" in payload:
        return payload["profiles"]
    if isinstance(payload, list):
        return payload
    return []


def narration_text(project: StoryProject) -> str:
    lines = [f"# {project.title}", "", f"Editorial question: {project.brief.question or project.analysis.story.central_question}", ""]
    for index, section in enumerate(project.script, start=1):
        lines.extend([
            f"## {index}. {section.heading}",
            "",
            section.narration.strip(),
            "",
        ])
    return "\n".join(lines).strip() + "\n"


def narration_srt(project: StoryProject) -> str:
    def stamp(seconds: float) -> str:
        total_ms = max(0, int(round(seconds * 1000)))
        hours, rem = divmod(total_ms, 3_600_000)
        minutes, rem = divmod(rem, 60_000)
        secs, millis = divmod(rem, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    rows = []
    cursor = 0.0
    for index, section in enumerate(project.script, start=1):
        duration = max(1.0, float(section.duration_seconds or 1.0))
        rows.append(f"{index}\n{stamp(cursor)} --> {stamp(cursor + duration)}\n{section.narration.strip()}\n")
        cursor += duration
    return "\n".join(rows)


def _concat_audio(files: list[Path], output: Path) -> None:
    if not files:
        raise VoiceboxError("Voicebox generated no narration audio.")
    concat = output.with_suffix(".concat.txt")
    concat.write_text("".join(f"file '{path.as_posix()}'\n" for path in files), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
         "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(output)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=1800,
    )
    concat.unlink(missing_ok=True)


def generate_voiceover(project: StoryProject, profile_id: str, output_dir: str | Path) -> tuple[str, str, str]:
    if not project.script:
        raise VoiceboxError("Build and approve the Story Lab script before generating narration.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = output_dir / "narration-script.txt"
    srt_path = output_dir / "narration-timing.srt"
    script_path.write_text(narration_text(project), encoding="utf-8")
    srt_path.write_text(narration_srt(project), encoding="utf-8")

    section_dir = output_dir / "sections"
    section_dir.mkdir(parents=True, exist_ok=True)
    generated = []
    for index, section in enumerate(project.script):
        if not section.narration.strip():
            continue
        response = _request_json(
            "/generate",
            method="POST",
            payload={
                "profile_id": profile_id,
                "text": section.narration.strip(),
                "language": "en",
            },
            timeout=1800,
        )
        generation_id = response.get("id") or response.get("generation_id")
        if not generation_id:
            raise VoiceboxError("Voicebox did not return a generation id.")
        audio = _request_bytes(f"/audio/{generation_id}", timeout=1800)
        section_path = section_dir / f"{index:03d}_{section.id}.wav"
        section_path.write_bytes(audio)
        generated.append(section_path)

    audio_path = output_dir / "narration.wav"
    _concat_audio(generated, audio_path)
    return str(script_path), str(srt_path), str(audio_path)
