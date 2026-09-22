from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from time import sleep, monotonic
from typing import Callable

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
    request_url = path if str(path).startswith(("http://", "https://")) else _url(path)
    request = urllib.request.Request(request_url, data=body, headers=headers, method=method)
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


def _voicebox_profile(profile_id: str) -> dict:
    payload = _request_json(f"/profiles/{profile_id}", timeout=10)
    if isinstance(payload, dict):
        return payload
    return {}


def _poll_generation(generation_id: str, poll_url: str | None = None, timeout: int = 1800, progress: Callable[[str], None] | None = None) -> dict:
    """Poll the exact URL returned by Voicebox, with model-state diagnostics as fallback."""
    deadline = monotonic() + timeout
    last_status = None
    poll_path = poll_url or f"/generate/{generation_id}/status"
    while monotonic() < deadline:
        payload = _request_json(poll_path, timeout=15)
        status = str(payload.get("status") or payload.get("state") or "").lower()
        if not status and payload.get("audio_path"):
            status = "completed"
        if status != last_status:
            last_status = status
            if progress:
                model_note = ""
                try:
                    model_payload = _request_json("/models/status", timeout=8)
                    if isinstance(model_payload, dict):
                        model_status = model_payload.get("status") or model_payload.get("state")
                        if model_status:
                            model_note = f" · model={model_status}"
                except VoiceboxError:
                    pass
                progress(f"{status or 'generating'} · generation={generation_id}{model_note}")
        if status in {"completed", "complete", "done", "success", "generated"}:
            return payload
        if status in {"failed", "error", "cancelled", "canceled"}:
            detail = payload.get("error") or payload.get("message") or payload.get("detail") or "Voicebox generation failed."
            raise VoiceboxError(f"Voicebox generation {generation_id} failed: {detail}")
        sleep(1.5)
    raise VoiceboxError(f"Voicebox generation {generation_id} timed out after {timeout} seconds.")

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


def _first_sentence(text: str) -> str:
    text = " ".join((text or "").split()).strip()
    if not text:
        return ""
    first = text.split(".", 1)[0].strip()
    return first + ("." if first else "")


def _clean_source_like_narration(text: str) -> str:
    """Keep research prose useful while rejecting dialogue/OCR as narrator copy."""
    import re
    text = " ".join((text or "").split()).strip()
    if not text:
        return ""
    if text.startswith(("“", '"', "'", "‘")):
        return ""
    tokens = text.split()
    single_alpha = sum(
        1 for token in tokens
        if len(token.strip(".,!?;:")) == 1 and token.strip(".,!?;:").isalpha()
    )
    if len(tokens) >= 8 and single_alpha / len(tokens) >= 0.65:
        return ""
    text = re.sub(r'(^|\\s)(?:“|")([^“”"]{1,220})(?:”|")', r"\\1", text)
    return " ".join(text.split()).strip()


def _deterministic_narration(project: StoryProject) -> dict[int, str]:
    """Build documentary narration from research when no local LLM is available.

    Source dialogue is evidence/footage, not narrator copy. The deterministic
    layer supplies connective explanation around the user's central question.
    """
    analysis = project.analysis
    story = analysis.story
    question = (project.brief.question or story.central_question or "").strip()
    if not question:
        question = "What does the available material actually establish?"

    context = _clean_source_like_narration(story.context)
    conflict = _clean_source_like_narration(story.conflict)
    consequences = _clean_source_like_narration(story.consequences)
    significance = _clean_source_like_narration(story.significance)
    interpretation = _clean_source_like_narration(story.interpretation)
    key_events = []
    for item in story.key_events[:5]:
        cleaned = _clean_source_like_narration(item)
        if cleaned:
            key_events.append(cleaned)
    counterpoints = []
    for item in story.counterpoints[:3]:
        cleaned = _clean_source_like_narration(item)
        if cleaned:
            counterpoints.append(cleaned)
    open_questions = []
    for item in story.open_questions[:3]:
        cleaned = _clean_source_like_narration(item)
        if cleaned:
            open_questions.append(cleaned)

    subject = analysis.characters[0] if analysis.characters else "the episode"

    result = {
        0: (
            f"At first glance, {subject} may seem to follow a familiar story pattern. "
            f"But the more useful question is not simply what happens; it is this: {question} "
            f"To answer that, we need to separate what the episode actually establishes "
            f"from what we might assume from the story's genre, labels, or first impressions."
        ),
        1: (
            f"The episode introduces {subject} through a world that already has its own "
            f"people, rules, relationships, and expectations. "
            f"{_first_sentence(context) if context else 'Those details give us the starting point for the question.'} "
            f"What matters here is how those established details connect to the central question, "
            f"rather than treating the setting alone as proof of an interpretation."
        ),
        2: (
            f"So the question becomes more precise: {question} "
            f"We can approach it by following the evidence in sequence and asking what each "
            f"turning point adds to the case. The goal is not to force a conclusion, but to "
            f"see whether the material gives us enough to support one."
        ),
        3: (
            f"Several details in the episode establish the situation we are dealing with. "
            f"{_first_sentence(context) if context else ''} "
            f"{' '.join(key_events[:2]) if key_events else 'The sequence of events then gives the question some concrete evidence to work with.'} "
            f"Taken together, these moments show what the source actually puts on screen, "
            f"which gives us a firmer basis for evaluating the central question."
        ),
        4: (
            f"The strongest evidence comes from what happens next. "
            f"{' '.join(key_events[2:5]) if len(key_events) > 2 else (conflict or 'The later events add consequences and context that change how the earlier details can be understood.')} "
            f"This matters because the answer to {question} depends on the relationship between "
            f"these events, not on any single line or isolated moment."
        ),
        5: (
            f"There is also a reason to be cautious about a simple answer. "
            f"{' '.join(counterpoints) if counterpoints else (interpretation or 'Some of the available material can support more than one reading.')} "
            f"That counterpoint does not erase the evidence; it tells us where the source stops being "
            f"certain and interpretation begins."
        ),
        6: (
            f"Putting the evidence together, the episode gives us a clearer way to think about {question}. "
            f"{consequences or significance or interpretation or 'The available material supports a conclusion only to the extent that these documented details hold together.'} "
            f"{('The broader significance is ' + significance) if significance and significance.lower() not in (consequences or '').lower() else ''} "
            f"{('There are still unresolved points: ' + ' '.join(open_questions)) if open_questions else 'What remains important is to distinguish what the episode establishes from what remains interpretation.'}"
        ),
    }
    return {index: " ".join(text.split()).strip() for index, text in result.items()}


def prepare_narration(project: StoryProject) -> StoryProject:
    """Prepare documentary narration with or without a local LLM.

    A local LLM is an optional enhancement. Without one, Story Lab uses a
    deterministic, question-driven narrator instead of leaving raw research
    dialogue in the voiceover.
    """
    if not project.script or not project.analysis:
        raise ValueError("Build the Story Lab story before preparing narration.")

    if llm_backend and llm_backend.active():
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
- Never copy source dialogue into narrator text. Dialogue belongs to the evidence/footage layer.
- Do not describe editing instructions, timestamps, evidence IDs, or clip mechanics.
- Do not invent dialogue, events, motives, names, or conclusions.
- Write natural spoken English suitable for a documentary narrator.
- Give each section enough substance for an engaging documentary: normally 90-180 words,
  and up to about 220 words when the evidence supports a richer explanation.
- Preserve the section order and return exactly one rewrite for every section index.

{chr(10).join(sections)}

Return JSON with this exact shape: {{"sections":[{{"section_index":0,"narration":"..."}}]}}."""
        data, _ = llm_backend.generate_json(prompt, _NarrationPlan)
        rewrites = {
            row.section_index: " ".join(row.narration.split()).strip()
            for row in _NarrationPlan.model_validate(data).sections
        }
    else:
        rewrites = _deterministic_narration(project)

    if set(rewrites) != set(range(len(project.script))):
        raise ValueError("Narration planner did not return every script section.")

    fallback = rewrites.get(6, rewrites.get(0, ""))
    previous = []
    for index, section in enumerate(project.script):
        text = rewrites.get(index, fallback)
        if not text:
            text = (
                f"Now we can return to the central question: "
                f"{project.brief.question or project.analysis.story.central_question or 'what the available material actually establishes'}."
            )
        words = set(text.lower().split())
        if previous:
            overlap = len(words & previous[-1]) / max(1, len(words | previous[-1]))
            if overlap >= 0.90:
                text = (
                    f"That brings us back to the central question: "
                    f"{project.brief.question or project.analysis.story.central_question or 'what the available material actually establishes'}."
                )
                words = set(text.lower().split())
        section.narration = text
        section.duration_seconds = round(max(4.0, len(text.split()) / 2.5), 1)
        section.approved = False
        previous.append(words)

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


def narration_srt(project: StoryProject, timeline_segments: list[VoiceoverSegment] | None = None) -> str:
    def stamp(seconds: float) -> str:
        total_ms = max(0, int(round(seconds * 1000)))
        hours, rem = divmod(total_ms, 3_600_000)
        minutes, rem = divmod(rem, 60_000)
        secs, millis = divmod(rem, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    rows = []
    source_segments = timeline_segments if timeline_segments is not None else (project.voiceover.segments if project.voiceover else [])
    segments = {segment.section_id: segment for segment in source_segments}
    cursor = 0.0
    for index, section in enumerate(project.script, start=1):
        segment = segments.get(section.id)
        if segment:
            start, end = float(segment.start_seconds), float(segment.end_seconds)
        else:
            duration = max(1.0, float(section.duration_seconds or 1.0))
            start, end = cursor, cursor + duration
            cursor = end
        rows.append(f"{index}\\n{stamp(start)} --> {stamp(end)}\\n{section.narration.strip()}\\n")
    return "\\n".join(rows)

def _visual_section_starts(project: StoryProject) -> dict[str, float]:
    """Map each script section to its position in the final selected-clip timeline."""
    starts = {}
    cursor = 0.0
    seen_source_clips = set()
    scenes = {scene.id: scene for scene in project.scenes}
    for section in project.script:
        starts[section.id] = round(cursor, 3)
        for scene_id in section.scene_ids:
            scene = scenes.get(scene_id)
            if not scene or not scene.selected:
                continue
            source_key = scene.output_file or scene.id
            if source_key in seen_source_clips:
                continue
            seen_source_clips.add(source_key)
            cursor += max(0.0, float(scene.end) - float(scene.start))
    return starts


def _mix_audio_timeline(segments: list[VoiceoverSegment], output: Path) -> None:
    """Place each generated Voicebox segment at its final-video timeline position."""
    if not segments:
        raise VoiceboxError("Voicebox generated no narration segments.")
    inputs = []
    filters = []
    labels = []
    for index, segment in enumerate(segments):
        if not segment.audio_path or not Path(segment.audio_path).is_file():
            raise VoiceboxError(f"Narration audio is missing for section {segment.section_id}.")
        inputs.extend(["-i", segment.audio_path])
        delay_ms = max(0, int(round(segment.start_seconds * 1000)))
        label = f"d{index}"
        filters.append(f"[{index}:a]adelay={delay_ms}|{delay_ms}:all=1[{label}]")
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(segments)}:duration=longest:dropout_transition=0[mix]")
    subprocess.run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters),
         "-map", "[mix]", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(output)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=1800,
    )


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


def generate_voiceover(project: StoryProject, profile_id: str, output_dir: str | Path, progress: Callable[[int, int, str], None] | None = None) -> tuple[str, str, str, list[VoiceoverSegment]]:
    if not project.script or not all(section.approved for section in project.script):
        raise VoiceboxError("Prepare and approve every Story Lab narration section before generating Voicebox audio.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    section_dir = output_dir / "sections"
    section_dir.mkdir(parents=True, exist_ok=True)
    generated = []
    segments: list[VoiceoverSegment] = []
    section_starts = _visual_section_starts(project)
    total = len(project.script)
    script_path = output_dir / "narration-script.txt"
    srt_path = output_dir / "narration-timing.srt"
    script_path.write_text(narration_text(project), encoding="utf-8")
    srt_path.write_text(narration_srt(project), encoding="utf-8")
    if progress:
        progress(0, total, "Narration script saved. Starting Voicebox.")

    profile = _voicebox_profile(profile_id)
    language = str(profile.get("language") or "en").lower()
    if language not in {"en", "zh"}:
        language = "en"

    for index, section in enumerate(project.script):
        if not section.narration.strip():
            continue
        if progress:
            progress(index, total, f"Sending narration section {index + 1}/{total} to Voicebox.")
        response = _request_json(
            "/generate",
            method="POST",
            payload={
                "profile_id": profile_id,
                "text": section.narration.strip(),
                "language": language,
            },
            timeout=60,
        )
        generation_id = response.get("id") or response.get("generation_id")
        if not generation_id:
            raise VoiceboxError(f"Voicebox did not return a generation id for section {index + 1}.")
        if str(response.get("status") or "").lower() not in {"completed", "complete", "done", "success", "generated"}:
            response = _poll_generation(
                str(generation_id),
                poll_url=response.get("poll_url"),
                timeout=1800,
                progress=lambda status: progress(index, total, f"Voicebox section {index + 1}/{total}: {status}") if progress else None,
            )
        if progress:
            progress(index, total, f"Downloading audio for section {index + 1}/{total}.")
        audio = _request_bytes(f"/audio/{generation_id}", timeout=300)
        section_path = section_dir / f"{index:03d}_{section.id}.wav"
        section_path.write_bytes(audio)
        duration = float(response.get("duration") or 0)
        if duration <= 0:
            duration = _audio_duration(section_path)
        duration = round(duration, 3)
        section.duration_seconds = duration
        start_seconds = section_starts.get(section.id, 0.0)
        segments.append(VoiceoverSegment(
            section_id=section.id,
            generation_id=str(generation_id),
            start_seconds=round(start_seconds, 3),
            end_seconds=round(start_seconds + duration, 3),
            audio_path=str(section_path),
            text=section.narration.strip(),
        ))
        generated.append(section_path)

    if not generated:
        raise VoiceboxError("Voicebox generated no narration audio.")

    script_path.write_text(narration_text(project), encoding="utf-8")
    srt_path.write_text(narration_srt(project, segments), encoding="utf-8")
    (output_dir / "narration-segments.json").write_text(
        json.dumps([segment.model_dump() for segment in segments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if progress:
        progress(total, total, "Mixing narration onto the final documentary timeline.")
    audio_path = output_dir / "narration.wav"
    _mix_audio_timeline(segments, audio_path)
    if progress:
        progress(total, total, "Voicebox narration is ready.")
    return str(script_path), str(srt_path), str(audio_path), segments
