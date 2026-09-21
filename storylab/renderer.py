from __future__ import annotations
import json
import os, subprocess
from dataclasses import dataclass
from pathlib import Path
from .models import StoryProject
def extract_scene(source_path: str, output_path: str, start: float, end: float) -> str:
    if not os.path.isfile(source_path): raise FileNotFoundError(source_path)
    if end <= start: raise ValueError("Scene end must be greater than start")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg","-y","-ss",f"{start:.3f}","-i",source_path,"-t",f"{end-start:.3f}","-c","copy",output_path],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=1800)
    return output_path


@dataclass
class RenderResult:
    output_path: str | None
    manifest_path: str


def render_documentary(project: StoryProject, output_dir: str | Path) -> RenderResult:
    """Render approved, source-backed visual ranges through the existing ffmpeg primitive.

    Contextual/generated items are deliberately represented in the manifest only:
    they require an editor-provided asset and must never be silently fabricated
    into an allegedly source-backed documentary.
    """
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    sources = {source.id: source for source in project.sources}
    clips, manifest_sections = [], []
    seen_clip_paths = set()
    for section in project.script:
        row = {"id": section.id, "heading": section.heading, "narration": section.narration,
               "duration_seconds": section.duration_seconds, "scene_ids": list(section.scene_ids),
               "visuals": [visual.model_dump() for visual in section.visual_suggestions],
               "visual_research": [item.model_dump() for item in section.visual_research]}
        # Preserve editorial order: script section order first, then the exact
        # scene_ids order chosen by the story/script graph. Only selected scenes
        # participate in the final assembly.
        linked_scenes = [
            scene for scene_id in section.scene_ids
            for scene in project.scenes
            if scene.id == scene_id and scene.selected
        ]
        linked_clip_count = 0
        for scene in linked_scenes:
            clip = None
            if scene.output_file and os.path.isfile(scene.output_file):
                clip = Path(scene.output_file)
            elif scene.source_file and scene.start is not None and scene.end is not None:
                clip = output_dir / f"{scene.id}.mp4"
                extract_scene(scene.source_file, str(clip), scene.start, scene.end)
            if clip is None:
                continue
            if str(clip) not in seen_clip_paths:
                clips.append(clip)
                seen_clip_paths.add(str(clip))
            row.setdefault("source_clips", []).append(str(clip))
            row.setdefault("scene_clips", []).append({"scene_id": scene.id, "path": str(clip)})
            linked_clip_count += 1
        if linked_clip_count == 0:
            for visual in section.visual_suggestions:
                if visual.material_type != "source_backed":
                    continue
                for evidence_id in visual.evidence_ids:
                    evidence = next((item for item in project.analysis.evidence if item.id == evidence_id), None) if project.analysis else None
                    source = sources.get(evidence.source_id) if evidence else None
                    if not evidence or not source or source.kind != "video" or not source.path or evidence.start is None or evidence.end is None:
                        continue
                    clip = output_dir / f"{section.id}_{evidence.id}.mp4"
                    extract_scene(source.path, str(clip), evidence.start, evidence.end)
                    if str(clip) not in seen_clip_paths:
                        clips.append(clip)
                        seen_clip_paths.add(str(clip))
                    row.setdefault("source_clips", []).append(str(clip))
                    row.setdefault("scene_clips", []).append({"scene_id": next((s.id for s in project.scenes if s.evidence_ids == [evidence.id]), None), "path": str(clip)})
        manifest_sections.append(row)
    manifest = output_dir / "render-manifest.json"
    manifest.write_text(json.dumps({
        "project_id": project.id,
        "sections": manifest_sections,
        "clips": [str(clip) for clip in clips],
        "assembly_order": [str(clip) for clip in clips],
        "selected_scene_ids": [scene.id for section in project.script for scene in project.scenes if scene.id in section.scene_ids and scene.selected],
    }, indent=2), encoding="utf-8")
    if not clips:
        return RenderResult(None, str(manifest))
    output = output_dir / "documentary-source-assembly.mp4"
    concat = output_dir / "concat.txt"
    concat.write_text("".join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(output)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=1800)
    return RenderResult(str(output), str(manifest))
