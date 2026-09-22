from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import StoryProject


def extract_scene(source_path: str, output_path: str, start: float, end: float) -> str:
    if not os.path.isfile(source_path):
        raise FileNotFoundError(source_path)
    if end <= start:
        raise ValueError("Scene end must be greater than start")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    duration = end - start
    command = [
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", source_path,
        "-t", f"{duration:.3f}",
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", output_path,
    ]
    try:
        subprocess.run(
            command, check=True, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, timeout=1800,
        )
    except subprocess.CalledProcessError as exc:
        # Visual research must still work when the source audio stream/codec
        # cannot be decoded. The narration is mixed separately later, so a
        # silent visual clip is preferable to no clip at all.
        fallback = [
            "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", source_path,
            "-t", f"{duration:.3f}", "-map", "0:v:0",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path,
        ]
        try:
            subprocess.run(
                fallback, check=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, timeout=1800,
            )
        except subprocess.CalledProcessError as fallback_exc:
            detail = fallback_exc.stderr.decode("utf-8", errors="replace")[-1500:]
            raise RuntimeError(f"FFmpeg could not extract {start:.3f}-{end:.3f}s: {detail}") from exc
    return output_path


@dataclass
class RenderResult:
    output_path: str | None
    manifest_path: str


def _wrap_text(text: str, width: int = 68) -> str:
    words = " ".join((text or "").split()).split(" ")
    lines = []
    current = ""
    for word in words:
        if not word:
            continue
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines[:8])


def _clean_overlay_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return " ".join(text.split()).strip()


def _render_text_clip(input_path: Path, output_path: Path, text_file: Path) -> None:
    """Normalize a source clip and burn the approved story text over it."""
    filter_text = (
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
        f"drawtext=font='DejaVu Sans':textfile='{text_file.as_posix()}':"
        "fontcolor=white:fontsize=38:line_spacing=10:"
        "box=1:boxcolor=black@0.62:boxborderw=18:"
        "x=(w-text_w)/2:y=h-text_h-70"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path), "-vf", filter_text,
         "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-ar", "48000", "-movflags", "+faststart", str(output_path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=1800,
    )


def _normalize_clip(input_path: Path, output_path: Path) -> None:
    filter_text = (
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path), "-vf", filter_text,
         "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-ar", "48000", "-movflags", "+faststart", str(output_path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=1800,
    )


def mux_narration(video_path: str, narration_path: str, output_path: str, source_volume: float = 0.22) -> str:
    """Mix local narrator audio over the rendered source video while preserving visuals."""
    video = Path(video_path)
    narration = Path(narration_path)
    output = Path(output_path)
    if not video.is_file():
        raise FileNotFoundError(video_path)
    if not narration.is_file():
        raise FileNotFoundError(narration_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    duration = max(0.1, float(probe.stdout.strip()))
    filter_complex = (
        f"[0:a]volume={max(0.0, min(1.0, source_volume))}[src];"
        "[1:a]apad,atrim=duration=" + f"{duration:.3f}" + "[vo];"
        "[src][vo]amix=inputs=2:duration=first:dropout_transition=2[a]"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-i", str(narration),
         "-filter_complex", filter_complex,
         "-map", "0:v:0", "-map", "[a]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-ar", "48000", "-t", f"{duration:.3f}", "-movflags", "+faststart",
         str(output)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=1800,
    )
    return str(output)


def render_documentary(project: StoryProject, output_dir: str | Path) -> RenderResult:
    """Render a review-approved Story Lab video with source visuals and story text.

    The result is a downloadable, long-form MP4. Source clips are kept grounded in
    the evidence/scene graph; generated text is burned into the first visual clip
    for each script section. No social publishing happens here.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    sources = {source.id: source for source in project.sources}
    clips = []
    manifest_sections = []
    seen_clip_paths = set()

    for section_index, section in enumerate(project.script):
        row = {
            "id": section.id,
            "heading": section.heading,
            "narration": section.narration,
            "duration_seconds": section.duration_seconds,
            "scene_ids": list(section.scene_ids),
            "visuals": [visual.model_dump() for visual in section.visual_suggestions],
            "visual_research": [item.model_dump() for item in section.visual_research],
        }
        linked_scenes = [
            scene for scene_id in section.scene_ids
            for scene in project.scenes
            if scene.id == scene_id and scene.selected
        ]
        section_clips = []
        for scene_index, scene in enumerate(linked_scenes):
            clip = None
            if scene.output_file and os.path.isfile(scene.output_file):
                clip = Path(scene.output_file)
            elif scene.source_file and scene.start is not None and scene.end is not None:
                clip = output_dir / f"{scene.id}.mp4"
                extract_scene(scene.source_file, str(clip), scene.start, scene.end)
            if clip is None:
                continue

            normalized = work_dir / f"{section_index:03d}_{scene_index:03d}_{scene.id}.mp4"
            if scene_index == 0:
                text_file = work_dir / f"{section_index:03d}_{section.id}.txt"
                overlay = _wrap_text(
                    _clean_overlay_text(section.heading) + "\n\n" +
                    _clean_overlay_text(section.narration),
                    68,
                )
                text_file.write_text(overlay, encoding="utf-8")
                _render_text_clip(clip, normalized, text_file)
            else:
                _normalize_clip(clip, normalized)

            section_clips.append(normalized)
            if str(clip) not in seen_clip_paths:
                clips.append(normalized)
                seen_clip_paths.add(str(clip))
            row.setdefault("source_clips", []).append(str(clip))
            row.setdefault("scene_clips", []).append({"scene_id": scene.id, "path": str(clip)})
        if section_clips:
            manifest_sections.append(row)

    manifest = output_dir / "render-manifest.json"
    manifest.write_text(
        json.dumps({
            "project_id": project.id,
            "sections": manifest_sections,
            "clips": [str(clip) for clip in clips],
            "assembly_order": [str(clip) for clip in clips],
            "selected_scene_ids": [
                scene.id
                for section in project.script
                for scene in project.scenes
                if scene.id in section.scene_ids and scene.selected
            ],
            "output_type": "storylab_text_and_visual_video",
        }, indent=2),
        encoding="utf-8",
    )

    if not clips:
        return RenderResult(None, str(manifest))

    concat = work_dir / "concat.txt"
    concat.write_text(
        "".join(f"file '{clip.as_posix()}'\n" for clip in clips),
        encoding="utf-8",
    )
    output = output_dir / "storylab-final.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
         "-c", "copy", "-movflags", "+faststart", str(output)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=1800,
    )
    return RenderResult(str(output), str(manifest))
