from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .analyzer import analyze_story
from .ingestion import ingest_file
from .models import RenderArtifact, ReviewItem, Scene, StoryBuilder, StoryProject, StoryProjectCreate
from .renderer import render_documentary, extract_scene, mux_narration
from .script import build_script
from .youtube import build_youtube_package
from .tts import generate_voiceover, voicebox_profiles, voicebox_status


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

    def delete(self, project_id: str) -> None:
        """Permanently remove a Story Lab project and all project-owned artifacts."""
        project_path = self._path(project_id)
        if not project_path.is_file():
            raise FileNotFoundError(project_id)

        # All Story Lab project data is namespaced by the validated UUID. Remove
        # the JSON record plus source snapshots, extracted scenes and renders.
        project_path.unlink()
        for relative in (Path("sources") / project_id, Path("scenes") / project_id, Path("renders") / project_id, Path("voiceover") / project_id):
            path = self.root / relative
            if path.exists():
                shutil.rmtree(path)

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
            # Scene research is driven by each generated script section, not one
            # generic project-wide query. Each section therefore gets timestamped
            # source moments relevant to the exact narration/question it will cover.
            for section in project.script:
                query = " ".join(filter(None, [
                    project.brief.question,
                    section.heading,
                    section.narration,
                ])).strip()
                self.search_scenes(
                    project.id,
                    evidence_ids=section.evidence_ids,
                    query=query,
                    context_seconds=2.5,
                    max_results=4,
                    search_mode="hybrid",
                )
            self.link_scenes_to_script(project.id)
            self._prepare_script_scenes(project.id)
            self._sync_visual_research_assets(project.id)
            # A freeform transcript can produce an outline, but it enters formal
            # review only once there is source evidence to review.
            project.status = "review" if project.analysis.evidence else "analyzed"
            project.error = None
        except Exception as exc:
            project.status = "error"; project.error = str(exc)
        return self.save(project)

    def update_brief(self, project_id: str, brief) -> StoryProject:
        """Replace the editorial brief and invalidate derived analysis/script/scene state."""
        project = self.get(project_id)
        project.brief = brief
        project.analysis = None
        project.script = []
        project.scenes = []
        project.reviews = []
        project.renders = []
        project.youtube = None
        project.voiceover = None
        project.status = "ingested" if project.sources else "new"
        project.error = None
        return self.save(project)



    def update_story(self, project_id: str, story: StoryBuilder) -> StoryProject:
        """Persist editorially approved/edited story structure without re-running research."""
        project = self.get(project_id)
        if not project.analysis:
            raise ValueError("Analyze the project before editing the story.")
        insight_ids = {item.id for item in project.analysis.insights}
        scene_ids = {scene.id for scene in project.scenes}
        components = {"hook", "context", "timeline", "key_events", "people", "conflict", "consequences", "significance", "central_question", "interpretation", "counterpoints", "open_questions"}
        for component, ids in story.component_insight_ids.items():
            if component not in components:
                raise ValueError(f"Unknown story component: {component}")
            for insight_id in ids:
                if insight_id not in insight_ids:
                    raise ValueError(f"Unknown insight: {insight_id}")
        for component, ids in story.component_scene_ids.items():
            if component not in components:
                raise ValueError(f"Unknown story component: {component}")
            for scene_id in ids:
                if scene_id not in scene_ids:
                    raise ValueError(f"Unknown scene: {scene_id}")
        evidence_ids = {item.id for item in project.analysis.evidence}
        all_story_evidence = (
            story.hook_evidence_ids + story.context_evidence_ids +
            story.conflict_evidence_ids + story.consequences_evidence_ids +
            story.significance_evidence_ids + story.central_question_evidence_ids +
            story.interpretation_evidence_ids +
            [x for group in story.timeline_evidence_ids for x in group] +
            [x for group in story.key_event_evidence_ids for x in group] +
            [x for group in story.people_evidence_ids for x in group] +
            [x for group in story.counterpoint_evidence_ids for x in group] +
            [x for group in story.open_question_evidence_ids for x in group]
        )
        unknown = [item for item in all_story_evidence if item not in evidence_ids]
        if unknown:
            raise ValueError(f"Unknown evidence: {unknown[0]}")
        # Automatically connect story components to extracted scenes through shared evidence.
        component_evidence = {
            "hook": story.hook_evidence_ids,
            "context": story.context_evidence_ids,
            "timeline": [eid for group in story.timeline_evidence_ids for eid in group],
            "key_events": [eid for group in story.key_event_evidence_ids for eid in group],
            "people": [eid for group in story.people_evidence_ids for eid in group],
            "conflict": story.conflict_evidence_ids,
            "consequences": story.consequences_evidence_ids,
            "significance": story.significance_evidence_ids,
            "central_question": story.central_question_evidence_ids,
            "interpretation": story.interpretation_evidence_ids,
            "counterpoints": [eid for group in story.counterpoint_evidence_ids for eid in group],
            "open_questions": [eid for group in story.open_question_evidence_ids for eid in group],
        }
        story.component_scene_ids = {
            component: [scene.id for scene in project.scenes if any(eid in component_ids for eid in scene.evidence_ids)]
            for component, component_ids in component_evidence.items()
        }
        project.analysis.story = story
        project.script = build_script(project.analysis, angle=project.brief.angle, kind=project.kind)
        self.save(project)
        self.link_scenes_to_script(project_id)
        self._prepare_script_scenes(project_id)
        self._sync_visual_research_assets(project_id)
        project = self.get(project_id)
        project.reviews = [item for item in project.reviews if item.target_type not in {"script", "render"}]
        project.renders = []
        project.youtube = None
        project.voiceover = None
        project.status = "review"
        project.error = None
        return self.save(project)

    def review(self, project_id: str, target_type: str, target_id: str, status: str, note: str = "") -> StoryProject:
        project = self.get(project_id)
        if target_type == "script" and target_id not in {section.id for section in project.script}:
            raise ValueError("Unknown script section")
        if target_type == "evidence" and target_id not in {item.id for item in (project.analysis.evidence if project.analysis else [])}:
            raise ValueError("Unknown evidence")
        if target_type == "insight" and target_id not in {item.id for item in (project.analysis.insights if project.analysis else [])}:
            raise ValueError("Unknown insight")
        now = datetime.now(timezone.utc).isoformat()
        project.reviews = [item for item in project.reviews if not (item.target_type == target_type and item.target_id == target_id)]
        project.reviews.append(ReviewItem(id=f"rv_{uuid.uuid4().hex[:10]}", target_type=target_type, target_id=target_id, status=status, note=note, updated_at=now))
        if target_type == "insight" and project.analysis:
            for insight in project.analysis.insights:
                if insight.id == target_id:
                    insight.status = {"approved": "approved", "changes_requested": "challenged"}.get(status, "unreviewed")
        if target_type == "script":
            for section in project.script:
                if section.id == target_id:
                    section.approved = status == "approved"
        if project.script and all(section.approved for section in project.script):
            project.status = "approved"
        elif project.status != "error":
            project.status = "review"
        return self.save(project)

    def search_scenes(self, project_id: str, evidence_ids: list[str] | None = None, query: str = "", context_seconds: float = 3.0, max_results: int = 12, search_mode: str = "hybrid", embedding_provider: str | None = None) -> StoryProject:
        """Find timestamp-backed source moments without requiring Ollama or a cloud API."""
        from .embeddings import rank_texts

        project = self.get(project_id)
        if not project.analysis:
            raise ValueError("Analyze the project before searching scenes.")
        if not 0 <= context_seconds <= 30:
            raise ValueError("Scene context must be between 0 and 30 seconds.")
        if not 1 <= max_results <= 40:
            raise ValueError("Scene result count must be between 1 and 40.")
        if search_mode not in {"hybrid", "embedding", "lexical"}:
            raise ValueError("Search mode must be hybrid, embedding, or lexical.")

        wanted = set(evidence_ids or [])
        if query.strip():
            query_text = query.strip().lower()
        else:
            query_text = " ".join(filter(None, [project.brief.question, project.analysis.story.central_question])).lower().strip()
        if not query_text and not wanted:
            query_text = project.title.lower().strip()

        candidates = [
            e for e in project.analysis.evidence
            if e.start is not None and e.end is not None
            and (not wanted or e.id in wanted) and e.source_id
        ]
        rows = []
        for item in candidates:
            source = next((s for s in project.sources if s.id == item.source_id), None)
            if not source or source.kind not in {"video", "audio"} or not source.path:
                continue
            rows.append((item, source, " ".join(filter(None, [item.label, item.claim, item.supporting_text]))))
        if not rows:
            return self.save(project)

        ranked = rank_texts(query_text, [row[2] for row in rows], mode=search_mode, provider=embedding_provider)
        selected = []
        for row_index, score, semantic_score, lexical_score, method in ranked[:max_results]:
            item, source, _ = rows[row_index]
            relevance = min(1.0, 0.65 * score + 0.35 * item.confidence)
            selected.append((relevance, semantic_score, lexical_score, method, item, source))

        grouped: dict[str, list[tuple[float, float, float, str, object, object]]] = {}
        for row in selected:
            grouped.setdefault(row[5].id, []).append(row)
        for source_rows in grouped.values():
            source_rows.sort(key=lambda row: row[4].start or 0)
            clusters = []
            for row in source_rows:
                if not clusters or (row[4].start or 0) > clusters[-1]["end"] + context_seconds * 2:
                    clusters.append({"start": row[4].start, "end": row[4].end, "rows": [row]})
                else:
                    clusters[-1]["end"] = max(clusters[-1]["end"], row[4].end)
                    clusters[-1]["rows"].append(row)
            for cluster in clusters:
                cluster_rows = cluster["rows"]
                evidence = [row[4] for row in cluster_rows]
                ids = [item.id for item in evidence]
                relevance = max(row[0] for row in cluster_rows)
                semantic_score = max(row[1] for row in cluster_rows)
                lexical_score = max(row[2] for row in cluster_rows)
                method = cluster_rows[0][3]
                existing = next((s for s in project.scenes if s.query == query_text and set(s.evidence_ids) == set(ids)), None)
                if existing:
                    existing.relevance = relevance
                    existing.semantic_score = semantic_score
                    existing.lexical_score = lexical_score
                    existing.search_method = method
                    continue
                project.scenes.append(Scene(
                    id=f"sn_{uuid.uuid4().hex[:10]}",
                    start=max(0.0, (cluster["start"] or 0) - context_seconds),
                    end=(cluster["end"] or 0) + context_seconds,
                    title=evidence[0].label or "Source moment",
                    purpose="; ".join(dict.fromkeys(item.claim for item in evidence if item.claim)),
                    evidence_ids=ids, source_id=cluster_rows[0][5].id,
                    source_file=cluster_rows[0][5].path, query=query_text,
                    relevance=relevance, semantic_score=semantic_score,
                    lexical_score=lexical_score, search_method=method,
                    extraction_status="candidate",
                ))
        project.scenes.sort(key=lambda s: s.relevance, reverse=True)
        return self.save(project)

    def _sync_visual_research_assets(self, project_id: str) -> StoryProject:
        """Resolve script visual research items to actual source/scene assets when possible."""
        project = self.get(project_id)
        evidence_by_id = {item.id: item for item in (project.analysis.evidence if project.analysis else [])}
        scenes = project.scenes

        for section in project.script:
            linked_scenes = [scene for scene in scenes if scene.id in section.scene_ids]
            for visual in section.visual_research:
                matched_evidence = [evidence_by_id[eid] for eid in visual.evidence_ids if eid in evidence_by_id]
                # A source-backed visual is only considered production-ready when
                # the cited evidence resolves to a real extracted scene.
                if visual.material_type == "source_backed":
                    scene = next(
                        (
                            item for item in linked_scenes
                            if item.extraction_status == "extracted" and item.output_file
                        ),
                        None,
                    )
                    if scene:
                        visual.source_id = scene.source_id
                        visual.asset_path = scene.output_file
                        visual.status = "planned" if visual.status not in {"approved", "rejected"} else visual.status
                        visual.notes = "Resolved from the cited timestamp-backed source scene."
                    else:
                        visual.source_id = next((item.source_id for item in matched_evidence if item.source_id), None)
                        visual.asset_path = None
                        visual.status = "planned" if visual.status not in {"approved", "rejected"} else visual.status
                        visual.notes = "Source evidence exists, but no extracted scene asset is available yet."
                elif matched_evidence:
                    # Contextual/archival research remains explicitly separate from
                    # source footage. It may have provenance without pretending to
                    # depict the cited event.
                    visual.source_id = matched_evidence[0].source_id
                    if visual.material_type == "contextual":
                        visual.notes = "Contextual material required; do not present it as the cited event."
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

    def _prepare_script_scenes(self, project_id: str) -> StoryProject:
        """Make linked source visuals immediately usable by Final Assembly."""
        project = self.get(project_id)
        linked_ids = []
        for section in project.script:
            for scene_id in section.scene_ids:
                if scene_id not in linked_ids:
                    linked_ids.append(scene_id)
        if not linked_ids:
            return self.save(project)
        for scene in project.scenes:
            scene.selected = scene.id in linked_ids
        self.save(project)
        self.extract_scenes(project_id, linked_ids)
        return self.get(project_id)

    def select_scenes(self, project_id: str, scene_ids: list[str]) -> StoryProject:
        """Persist the exact source scenes the final long-form assembly should use."""
        project = self.get(project_id)
        known = {scene.id for scene in project.scenes}
        unknown = [scene_id for scene_id in scene_ids if scene_id not in known]
        if unknown:
            raise ValueError(f"Unknown scene: {unknown[0]}")
        selected = set(scene_ids)
        for scene in project.scenes:
            scene.selected = scene.id in selected
        project = self.save(project)
        # Selection is the production hand-off: extract newly selected source
        # moments immediately so the final assembly never waits for a second
        # manual extraction step.
        project = self.extract_scenes(project_id, list(selected))
        self.link_scenes_to_script(project_id)
        self._sync_visual_research_assets(project_id)
        return self.save(self.get(project_id))

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

    def voicebox_status(self) -> dict:
        return voicebox_status()

    def voicebox_profiles(self) -> list[dict]:
        return voicebox_profiles()

    def generate_voiceover(self, project_id: str, profile_id: str) -> StoryProject:
        project = self.get(project_id)
        if not project.script or not all(section.approved for section in project.script):
            raise ValueError("Approve every script section before generating narration.")
        now = datetime.now(timezone.utc).isoformat()
        from .models import VoiceoverArtifact
        project.voiceover = VoiceoverArtifact(
            status="generating", provider="voicebox", profile_id=profile_id, created_at=now
        )
        self.save(project)
        try:
            output_dir = self.root / "voiceover" / project.id
            script_path, timing_path, audio_path = generate_voiceover(project, profile_id, output_dir)
            project.voiceover = VoiceoverArtifact(
                status="generated", provider="voicebox", profile_id=profile_id,
                script_path=script_path, timing_path=timing_path, audio_path=audio_path,
                created_at=now,
            )
            project.error = None
        except Exception as exc:
            project.voiceover = VoiceoverArtifact(
                status="error", provider="voicebox", profile_id=profile_id, error=str(exc), created_at=now
            )
            project.error = str(exc)
        return self.save(project)

    def render(self, project_id: str) -> StoryProject:
        project = self.get(project_id)
        if not project.script or not all(section.approved for section in project.script):
            raise ValueError("Approve every script section before rendering.")
        artifact = RenderArtifact(id=f"rd_{uuid.uuid4().hex[:12]}", status="rendering", created_at=datetime.now(timezone.utc).isoformat())
        project.renders.append(artifact); self.save(project)
        try:
            project = self._prepare_script_scenes(project_id)
            result = render_documentary(project, self.root / "renders" / project.id)
            if not result.output_path:
                raise ValueError("Renderer produced no video because no selected source clips were available.")
            project.youtube = build_youtube_package(project)
            artifact.status = "rendered"; artifact.output_path = result.output_path; artifact.manifest_path = result.manifest_path
            if project.voiceover and project.voiceover.status == "generated" and project.voiceover.audio_path:
                voiced_video = Path(result.output_path).with_name("storylab-final-voiceover.mp4")
                mux_narration(result.output_path, project.voiceover.audio_path, str(voiced_video))
                artifact.output_path = str(voiced_video)
            project.status = "rendered"; project.error = None
        except Exception as exc:
            artifact.status = "error"; artifact.error = str(exc); project.status = "error"; project.error = str(exc)
        return self.save(project)


store = StoryLabStore()
