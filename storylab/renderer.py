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
    for section in project.script:
        row = {"id": section.id, "heading": section.heading, "narration": section.narration,
               "duration_seconds": section.duration_seconds, "visuals": [visual.model_dump() for visual in section.visual_suggestions], "visual_research": [item.model_dump() for item in section.visual_research]}
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
                clips.append(clip); row.setdefault("source_clips", []).append(str(clip))
        manifest_sections.append(row)
    manifest = output_dir / "render-manifest.json"
    manifest.write_text(json.dumps({"project_id": project.id, "sections": manifest_sections, "clips": [str(clip) for clip in clips]}, indent=2), encoding="utf-8")
    if not clips:
        return RenderResult(None, str(manifest))
    output = output_dir / "documentary-source-assembly.mp4"
    concat = output_dir / "concat.txt"
    concat.write_text("".join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(output)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=1800)
    return RenderResult(str(output), str(manifest))
