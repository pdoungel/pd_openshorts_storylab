from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field

from .models import StoryProject, VoiceoverSegment

try:
    import llm_backend
except ImportError:  # pragma: no cover - Story Lab can still use deterministic narration
    llm_backend = None


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


class _NarrationRewrite(BaseModel):
    section_index: int = Field(ge=0)
    narration: str = Field(min_length=1, max_length=3000)


class _NarrationPlan(BaseModel):
    sections: list[_NarrationRewrite]


def _selected_context(project: StoryProject, section) -> str:
    evidence = {item.id: item for item in (project.analysis.evidence if project.analysis else [])}
    scenes = {scene.id: scene for scene in project.scenes}
    rows = []
    for evidence_id in section.evidence_ids:
        item = evidence.get(evidence_id)
        if not item:
            continue
        timestamp = f"{item.start:.3f}-{item.end:.3f}s" if item.start is not None and item.end is not None else "untimed"
        rows.append(f"EVIDENCE {timestamp}: {item.claim}. Source text: {item.supporting_text}")
    for scene_id in section.scene_ids:
        scene = scenes.get(scene_id)
        if scene and scene.selected:
            rows.append(f"SELECTED CLIP {scene.start:.3f}-{scene.end:.3f}s: {scene.title}. Purpose: {scene.purpose}")
    return "\\n".join(rows[:12])


def prepare_narration(project: StoryProject) -> StoryProject:
    """Use the configured local LLM to turn the research script into final voiceover copy.

    The model is constrained by the user's central question, the section's existing
    evidence provenance, and the clips the user actually selected. It may improve
    transitions and reasoning, but it may not invent facts or move evidence between
    sections. When no local LLM is configured, the already-generated Story Lab script
    is retained unchanged rather than silently fabricating a second analysis layer.
    """
    if not project.script or not project.analysis:
        raise ValueError("Build the Story Lab story before preparing narration.")
    if not llm_backend or not llm_backend.active():
        return project

    question = project.brief.question.strip() or project.analysis.story.central_question.strip()
    sections = []
    for index, section in enumerate(project.script):
        sections.append(
            f"SECTION {index}: {section.heading}\\n"
            f"DRAFT NARRATION: {section.narration}\\n"
            f"GROUNDING:\\n{_selected_context(project, section)}"
        )

    prompt = f"""Prepare the final documentary voiceover for this Story Lab project.

TITLE: {project.title}
EDITORIAL ANGLE: {project.brief.angle}
CENTRAL QUESTION: {question}

The central question is the job of the video. The narration must reason toward an
answer instead of retelling the whole episode. Use the supplied draft as material,
but rewrite it when necessary so the sections form one coherent spoken argument.

RULES:
- Answer the central question directly and progressively.
- Use only facts supported by the supplied evidence/selected clips.
- Keep interpretation clearly distinguishable from what the source establishes.
- Add useful connective reasoning where the evidence supports it; do not merely
  concatenate evidence claims.
- Do not repeat the hook/context/question in later sections.
- Do not repeat the same fact unless it is necessary to resolve the question.
- Do not describe editing instructions, timestamps, evidence IDs, or clip mechanics.
- Do not invent dialogue, events, motives, names, or conclusions.
- Write natural spoken English suitable for a documentary narrator.
- Keep each section focused; normally 45-110 words, shorter when the material warrants it.
- Preserve the section order and return exactly one rewrite for every section index.

{chr(10).join(sections)}

Return JSON with this exact shape: {{"sections":[{{"section_index":0,"narration":"..."}}]}}."""
    data, _ = llm_backend.generate_json(prompt, _NarrationPlan)
    rewrites = {row.section_index: " ".join(row.narration.split()).strip() for row in _NarrationPlan.model_validate(data).sections}
    if set(rewrites) != set(range(len(project.script))):
        raise ValueError("Narration planner did not return every script section.")
    previous = []
    for index, section in enumerate(project.script):
        text = rewrites[index]
        words = set(text.lower().split())
        if previous:
            overlap = len(words & previous[-1]) / max(1, len(words | previous[-1]))
            if overlap >= 0.82:
                raise ValueError(f"Narration section {index + 1} is too similar to the previous section.")
        section.narration = text
        section.duration_seconds = round(max(4.0, len(text.split()) / 2.5), 1)
        previous.append(words)
    for section in project.script:
        section.approved = False
    project.voiceover = None
    project.error = None
    return project


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


def _audio_duration(path: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    return max(0.01, float(probe.stdout.strip()))


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


def generate_voiceover(project: StoryProject, profile_id: str, output_dir: str | Path) -> tuple[str, str, str, list[VoiceoverSegment]]:
    if not project.script or not all(section.approved for section in project.script):
        raise VoiceboxError("Prepare and approve every Story Lab narration section before generating Voicebox audio.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    section_dir = output_dir / "sections"
    section_dir.mkdir(parents=True, exist_ok=True)
    generated = []
    segments: list[VoiceoverSegment] = []
    cursor = 0.0

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
        duration = float(response.get("duration") or 0)
        if duration <= 0:
            duration = _audio_duration(section_path)
        duration = round(duration, 3)
        section.duration_seconds = duration
        segments.append(VoiceoverSegment(
            section_id=section.id,
            generation_id=str(generation_id),
            start_seconds=round(cursor, 3),
            end_seconds=round(cursor + duration, 3),
            audio_path=str(section_path),
            text=section.narration.strip(),
        ))
        generated.append(section_path)
        cursor += duration

    if not generated:
        raise VoiceboxError("Voicebox generated no narration audio.")

    script_path = output_dir / "narration-script.txt"
    srt_path = output_dir / "narration-timing.srt"
    script_path.write_text(narration_text(project), encoding="utf-8")
    srt_path.write_text(narration_srt(project), encoding="utf-8")
    (output_dir / "narration-segments.json").write_text(
        json.dumps([segment.model_dump() for segment in segments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    audio_path = output_dir / "narration.wav"
    _concat_audio(generated, audio_path)
    return str(script_path), str(srt_path), str(audio_path), segments
