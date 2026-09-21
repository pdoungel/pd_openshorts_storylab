from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .analyzer import analyze_story
from .ingestion import ingest_file
from .models import RenderArtifact, ReviewItem, Scene, StoryProject, StoryProjectCreate
from .renderer import render_documentary, extract_scene
from .script import build_script


class StoryLabStore:
    def __init__(self, output_dir: str = "output"):
        self.root = Path(output_dir).resolve() / "storylab"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, project_id: str) -> Path:
        if not project_id or Path(project_id).name != project_id:
            raise ValueError("Invalid Story Lab project id")
        return self.root / f"{project_id}.json"

    def _source_dir(self, project_id: str) -> Path:
        path = self.root / "sources" / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(self, project: StoryProject) -> StoryProject:
        project.updated_at = datetime.now(timezone.utc).isoformat()
        self._path(project.id).write_text(project.model_dump_json(indent=2), encoding="utf-8")
        return project

    def get(self, project_id: str) -> StoryProject:
        path = self._path(project_id)
        if not path.is_file():
            raise FileNotFoundError(project_id)
        return StoryProject.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[StoryProject]:
        projects = []
        for path in self.root.glob("*.json"):
            try:
                projects.append(StoryProject.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return sorted(projects, key=lambda project: project.updated_at, reverse=True)

    def create(self, payload: StoryProjectCreate) -> StoryProject:
        now = datetime.now(timezone.utc).isoformat()
        project = StoryProject(id=str(uuid.uuid4()), title=payload.title.strip(), kind=payload.kind,
                               source_path=payload.source_path, notes=payload.notes, brief=payload.brief, created_at=now, updated_at=now)
        return self.save(project)

    def ingest(self, project_id: str, source_path: str, source_name: str | None = None, transcribe: bool = False) -> StoryProject:
        project = self.get(project_id)
        original = Path(source_path)
        if not original.is_file():
            raise FileNotFoundError(source_path)
        # Preserve a private, project-local source snapshot rather than storing arbitrary paths.
        safe_name = Path(source_name or original.name).name
        destination = self._source_dir(project.id) / f"{uuid.uuid4().hex[:8]}_{safe_name}"
        shutil.copy2(original, destination)
        source = ingest_file(destination, source_name=safe_name, transcribe=transcribe)
        project.sources.append(source)
        project.status = "ingested"
        project.error = None
        return self.save(project)

    def ingest_text(self, project_id: str, text: str, name: str = "notes.txt") -> StoryProject:
        if not text.strip():
            raise ValueError("Source text cannot be empty")
        project = self.get(project_id)
        suffix = Path(name).suffix.lower() if Path(name).suffix.lower() in {".txt", ".md", ".srt", ".vtt", ".json"} else ".txt"
        destination = self._source_dir(project.id) / f"{uuid.uuid4().hex[:8]}_{Path(name).stem}{suffix}"
        destination.write_text(text, encoding="utf-8")
        source = ingest_file(destination, source_name=destination.name)
        project.sources.append(source); project.status = "ingested"; project.error = None
        return self.save(project)

    def analyze(self, project_id: str, transcript: str = "", duration: Optional[float] = None) -> StoryProject:
        project = self.get(project_id)
        project.status = "analyzing"; self.save(project)
        try:
            project.analysis = analyze_story(
                project.title, transcript, duration, project.sources,
                angle=project.brief.angle, kind=project.kind, question=project.brief.question
            )
            project.script = build_script(project.analysis, angle=project.brief.angle, kind=project.kind)
            project.scenes = []
            self.save(project)
            self.search_scenes(project.id)
            self.link_scenes_to_script(project.id)
            # A freeform transcript can produce an outline, but it enters formal
            # review only once there is source evidence to review.
            project.status = "review" if project.analysis.evidence else "analyzed"
            project.error = None
        except Exception as exc:
            project.status = "error"; project.error = str(exc)
        return self.save(project)

    def review(self, project_id: str, target_type: str, target_id: str, status: str, note: str = "") -> StoryProject:
        project = self.get(project_id)
        if target_type == "script" and target_id not in {section.id for section in project.script}:
            raise ValueError("Unknown script section")
        if target_type == "evidence" and target_id not in {item.id for item in (project.analysis.evidence if project.analysis else [])}:
            raise ValueError("Unknown evidence")
        now = datetime.now(timezone.utc).isoformat()
        project.reviews = [item for item in project.reviews if not (item.target_type == target_type and item.target_id == target_id)]
        project.reviews.append(ReviewItem(id=f"rv_{uuid.uuid4().hex[:10]}", target_type=target_type, target_id=target_id, status=status, note=note, updated_at=now))
        if target_type == "script":
            for section in project.script:
                if section.id == target_id:
                    section.approved = status == "approved"
        if project.script and all(section.approved for section in project.script):
            project.status = "approved"
        elif project.status != "error":
            project.status = "review"
        return self.save(project)

    def search_scenes(self, project_id: str, evidence_ids: list[str] | None = None, query: str = "", context_seconds: float = 3.0) -> StoryProject:
        """Rank transcript/source evidence and merge nearby hits into coherent source scenes."""
        project = self.get(project_id)
        if not project.analysis:
            raise ValueError("Analyze the project before searching scenes.")
        if not 0 <= context_seconds <= 30:
            raise ValueError("Scene context must be between 0 and 30 seconds.")
        wanted = set(evidence_ids or [])
        candidates = [e for e in project.analysis.evidence if e.start is not None and e.end is not None and
                      (not wanted or e.id in wanted)]
        query_text = " ".join(filter(None, [query, project.brief.question, project.analysis.story.central_question])).lower().strip()
        terms = {t.strip(".,!?;:()[]{}\"'") for t in query_text.split()
                 if len(t.strip(".,!?;:()[]{}\"'")) > 2}
        ranked = []
        for item in candidates:
            if not item.source_id:
                continue
            source = next((s for s in project.sources if s.id == item.source_id), None)
            if not source or source.kind not in {"video", "audio"} or not source.path:
                continue
            haystack = " ".join((item.label, item.claim, item.supporting_text)).lower()
            matches = sum(1 for term in terms if term in haystack)
            if terms and matches == 0 and not wanted:
                continue
            lexical = matches / max(1, len(terms))
            relevance = min(1.0, 0.5 * item.confidence + 0.5 * lexical) if terms else item.confidence
            ranked.append((relevance, item, source))
        ranked.sort(key=lambda row: row[0], reverse=True)

        # Keep the strongest candidate for each evidence item and merge nearby hits
        # from the same source so a sentence split across transcript cues becomes one usable scene.
        selected = ranked[:40]
        grouped: dict[str, list[tuple[float, object, object]]] = {}
        for relevance, item, source in selected:
            grouped.setdefault(source.id, []).append((relevance, item, source))
        for source_rows in grouped.values():
            source_rows.sort(key=lambda row: row[1].start or 0)
            clusters = []
            for row in source_rows:
                if not clusters or (row[1].start or 0) > clusters[-1]["end"] + context_seconds * 2:
                    clusters.append({"start": row[1].start, "end": row[1].end, "rows": [row]})
                else:
                    clusters[-1]["end"] = max(clusters[-1]["end"], row[1].end)
                    clusters[-1]["rows"].append(row)
            for cluster in clusters:
                rows = cluster["rows"]
                evidence = [row[1] for row in rows]
                relevance = max(row[0] for row in rows)
                ids = [item.id for item in evidence]
                existing = next((s for s in project.scenes if s.query == query_text and set(s.evidence_ids) == set(ids)), None)
                if existing:
                    existing.relevance = relevance
                    continue
                project.scenes.append(Scene(
                    id=f"sn_{uuid.uuid4().hex[:10]}",
                    start=max(0.0, (cluster["start"] or 0) - context_seconds),
                    end=(cluster["end"] or 0) + context_seconds,
                    title=evidence[0].label or "Source moment",
                    purpose="; ".join(dict.fromkeys(item.claim for item in evidence if item.claim)),
                    evidence_ids=ids, source_id=rows[0][2].id, source_file=rows[0][2].path,
                    query=query_text, relevance=relevance, extraction_status="candidate",
                ))
        project.scenes.sort(key=lambda s: s.relevance, reverse=True)
        return self.save(project)

    def link_scenes_to_script(self, project_id: str) -> StoryProject:
        """Attach source scenes to script sections through shared evidence IDs."""
        project = self.get(project_id)
        if not project.analysis:
            raise ValueError("Analyze the project before linking scenes.")
        scenes_by_evidence: dict[str, list[str]] = {}
        for scene in project.scenes:
            for evidence_id in scene.evidence_ids:
                scenes_by_evidence.setdefault(evidence_id, []).append(scene.id)
        for section in project.script:
            linked: list[str] = []
            for evidence_id in section.evidence_ids:
                for scene_id in scenes_by_evidence.get(evidence_id, []):
                    if scene_id not in linked:
                        linked.append(scene_id)
            section.scene_ids = linked
        return self.save(project)

    def extract_scenes(self, project_id: str, scene_ids: list[str] | None = None) -> StoryProject:
        project = self.get(project_id)
        target_ids = set(scene_ids or [scene.id for scene in project.scenes if scene.extraction_status == "candidate"])
        output_dir = self.root / "scenes" / project.id
        output_dir.mkdir(parents=True, exist_ok=True)
        for scene in project.scenes:
            if scene.id not in target_ids or scene.extraction_status == "extracted":
                continue
            if not scene.source_file:
                scene.extraction_status = "error"
                continue
            try:
                output = output_dir / f"{scene.id}.mp4"
                extract_scene(scene.source_file, str(output), scene.start, scene.end)
                scene.output_file = str(output)
                scene.extraction_status = "extracted"
            except Exception:
                scene.extraction_status = "error"
        return self.save(project)

    def review_visual(self, project_id: str, visual_id: str, status: str, note: str = "") -> StoryProject:
        project = self.get(project_id)
        if status not in {"planned", "researching", "approved", "rejected"}:
            raise ValueError("Invalid visual research status")
        for section in project.script:
            for visual in section.visual_research:
                if visual.id == visual_id:
                    visual.status = status
                    if note:
                        visual.notes = note
                    return self.save(project)
        raise ValueError("Unknown visual research item")

    def render(self, project_id: str) -> StoryProject:
        project = self.get(project_id)
        if not project.script or not all(section.approved for section in project.script):
            raise ValueError("Approve every script section before rendering.")
        artifact = RenderArtifact(id=f"rd_{uuid.uuid4().hex[:12]}", status="rendering", created_at=datetime.now(timezone.utc).isoformat())
        project.renders.append(artifact); self.save(project)
        try:
            result = render_documentary(project, self.root / "renders" / project.id)
            artifact.status = "rendered"; artifact.output_path = result.output_path; artifact.manifest_path = result.manifest_path
            project.status = "rendered"; project.error = None
        except Exception as exc:
            artifact.status = "error"; artifact.error = str(exc); project.status = "error"; project.error = str(exc)
        return self.save(project)


store = StoryLabStore()
