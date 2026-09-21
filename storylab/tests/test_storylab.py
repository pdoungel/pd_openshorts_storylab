from storylab.models import StoryProjectCreate,Evidence
from storylab.evidence import normalize_evidence,extract_source_evidence
from storylab.service import StoryLabStore
def test_evidence_is_clamped_to_duration():
    item=Evidence(id="e1",start=-2,end=99,label="x",claim="y"); normalized=normalize_evidence([item],duration=10); assert normalized[0].start==0; assert normalized[0].end==10
def test_store_create_and_reload(tmp_path):
    store=StoryLabStore(str(tmp_path)); p=store.create(StoryProjectCreate(title="Test film",kind="movie")); assert store.get(p.id).title=="Test film"; assert store.list()[0].id==p.id
def test_store_analysis_fallback(tmp_path):
    store=StoryLabStore(str(tmp_path)); p=store.create(StoryProjectCreate(title="Test film",kind="movie")); r=store.analyze(p.id,"A transcript with enough text to survive the fallback path."); assert r.status=="analyzed"; assert r.analysis is not None; assert r.script

def test_text_ingestion_creates_page_or_timestamp_traceable_evidence(tmp_path):
    store=StoryLabStore(str(tmp_path)); project=store.create(StoryProjectCreate(title="Record",kind="documentary"))
    ingested=store.ingest_text(project.id,"First documented event happened here.\n\nA second source passage follows.")
    result=store.analyze(ingested.id)
    assert result.sources[0].kind=="text"
    assert result.analysis.evidence[0].source_id==result.sources[0].id
    # Plain text has no page or timing; it is a quote, but not a precise citation.
    assert result.analysis.evidence[0].traceability=="unverified"

def test_timed_transcript_is_source_traceable_and_requires_approval(tmp_path):
    store=StoryLabStore(str(tmp_path)); project=store.create(StoryProjectCreate(title="Record",kind="documentary"))
    source=tmp_path/"record.srt"; source.write_text("1\n00:00:01,000 --> 00:00:03,000\nA documented event occurs.\n",encoding="utf-8")
    project=store.ingest(project.id,str(source)); project=store.analyze(project.id)
    evidence=project.analysis.evidence[0]
    assert evidence.traceability=="source" and evidence.start==1.0
    try: store.render(project.id)
    except ValueError as exc: assert "Approve" in str(exc)
    else: assert False, "render must not bypass review"
    for section in project.script: project=store.review(project.id,"script",section.id,"approved")
    assert project.status=="approved"


def test_json_transcript_invalid_timestamps_are_ignored(tmp_path):
    store=StoryLabStore(str(tmp_path)); project=store.create(StoryProjectCreate(title="Record",kind="documentary"))
    source=tmp_path/"bad.json"
    source.write_text('{"segments":[{"text":"valid","start":1,"end":2},{"text":"bad","start":"oops","end":3}]}',encoding="utf-8")
    result=store.ingest(project.id,str(source))
    assert len(result.sources[0].segments)==1
    assert result.sources[0].segments[0].start==1.0


def test_vtt_short_timestamps_are_ingested(tmp_path):
    store=StoryLabStore(str(tmp_path)); project=store.create(StoryProjectCreate(title="Record",kind="documentary"))
    source=tmp_path/"record.vtt"
    source.write_text("WEBVTT\n\n00:01.000 --> 00:03.500\nA short-form timed cue.\n",encoding="utf-8")
    result=store.ingest(project.id,str(source))
    segment=result.sources[0].segments[0]
    assert segment.start==1.0
    assert segment.end==3.5


def test_visual_research_is_seeded_and_reviewable(tmp_path):
    store=StoryLabStore(str(tmp_path)); project=store.create(StoryProjectCreate(title="Record",kind="documentary"))
    project=store.ingest_text(project.id,"A documented event happened in the archive.")
    project=store.analyze(project.id)
    visual=project.script[0].visual_research[0]
    assert visual.status=="planned" and visual.evidence_ids
    project=store.review_visual(project.id,visual.id,"approved","Checked against source")
    assert project.script[0].visual_research[0].status=="approved"


def test_script_sections_preserve_story_evidence_links(tmp_path):
    store=StoryLabStore(str(tmp_path))
    project=store.create(StoryProjectCreate(title="Record",kind="documentary"))
    project=store.ingest_text(project.id,"First documented event happened here.\n\nA second source passage follows.")
    project=store.analyze(project.id)
    hook=project.script[0]
    assert hook.heading=="Hook"
    assert hook.evidence_ids==project.analysis.story.hook_evidence_ids
    assert hook.evidence_ids
    event_sections=[section for section in project.script if section.heading.startswith("Key event")]
    if event_sections and project.analysis.story.key_event_evidence_ids:
        assert event_sections[0].evidence_ids==project.analysis.story.key_event_evidence_ids[0]


def test_story_brief_drives_why_angle_for_anime(tmp_path):
    store = StoryLabStore(str(tmp_path))
    project = store.create(StoryProjectCreate(
        title="Why did they do it?",
        kind="anime",
        brief={"angle": "why", "question": "Why did the character make that choice?", "spoiler_policy": "full"},
    ))
    project = store.ingest_text(project.id, "The character chooses the plan after the warning.")
    project = store.analyze(project.id)
    headings = [section.heading for section in project.script]
    assert project.brief.angle == "why"
    assert "The question" in headings
    assert "The explanation" in headings


def test_story_brief_drives_theory_angle_for_series(tmp_path):
    store = StoryLabStore(str(tmp_path))
    project = store.create(StoryProjectCreate(title="Mystery", kind="series", brief={"angle": "theory"}))
    project = store.ingest_text(project.id, "The symbol appears before the reveal.")
    project = store.analyze(project.id)
    headings = [section.heading for section in project.script]
    assert "What is canon" in headings
    assert "The theory" in headings


def test_timed_evidence_becomes_extractable_scene(tmp_path):
    store = StoryLabStore(str(tmp_path))
    project = store.create(StoryProjectCreate(title="Film", kind="movie"))
    source = tmp_path/"film.srt"
    source.write_text("1\n00:00:10,000 --> 00:00:12,500\nA key reveal happens.\n", encoding="utf-8")
    project = store.ingest(project.id, str(source))
    project = store.analyze(project.id)
    # Scene search requires a media source; the timed transcript supplies the
    # evidence coordinates, while this fixture promotes the source record to
    # a media locator without invoking ffmpeg.
    project.sources[0] = project.sources[0].model_copy(update={"kind": "video"})
    project = store.save(project)
    project.scenes = []
    project = store.search_scenes(project.id)
    assert project.scenes
    scene = project.scenes[0]
    assert scene.evidence_ids == [project.analysis.evidence[0].id]
    assert scene.start == 10.0 and scene.end == 12.5
    assert scene.extraction_status == "candidate"


def test_scene_search_can_limit_to_selected_evidence(tmp_path):
    store = StoryLabStore(str(tmp_path))
    project = store.create(StoryProjectCreate(title="Film", kind="movie"))
    source = tmp_path/"film.srt"
    source.write_text("1\n00:00:01,000 --> 00:00:02,000\nFirst.\n\n2\n00:00:05,000 --> 00:00:06,000\nSecond.\n", encoding="utf-8")
    project = store.ingest(project.id, str(source))
    project = store.analyze(project.id)
    first_id = project.analysis.evidence[0].id
    project.scenes = []
    project = store.search_scenes(project.id, [first_id])
    assert len(project.scenes) == 1
    assert project.scenes[0].evidence_ids == [first_id]


def test_project_creation_persists_story_brief(tmp_path):
    store = StoryLabStore(str(tmp_path))
    project = store.create(StoryProjectCreate(
        title="Theory project",
        kind="anime",
        brief={"angle": "theory", "question": "Who is behind the event?", "spoiler_policy": "full"},
    ))
    reloaded = store.get(project.id)
    assert reloaded.brief.angle == "theory"
    assert reloaded.brief.question == "Who is behind the event?"


def test_updating_story_brief_resets_analysis(tmp_path):
    store = StoryLabStore(str(tmp_path))
    project = store.create(StoryProjectCreate(title="Story", brief={"angle": "story"}))
    project = store.ingest_text(project.id, "A source passage.")
    project = store.analyze(project.id)
    assert project.analysis is not None
    project = store.update_brief(project.id, project.brief.model_copy(update={"angle": "why", "question": "Why?"}))
    assert project.analysis is None
    assert project.script == []
    assert project.brief.angle == "why"


def test_timed_scene_is_linked_back_to_matching_script_section(tmp_path):
    store = StoryLabStore(str(tmp_path))
    project = store.create(StoryProjectCreate(title="Film", kind="movie"))
    source = tmp_path/"film.srt"
    source.write_text("1\\n00:00:10,000 --> 00:00:12,500\\nA key reveal happens.\\n", encoding="utf-8")
    project = store.ingest(project.id, str(source))
    project = store.analyze(project.id)
    scene = project.scenes[0]
    linked_sections = [section for section in project.script if scene.id in section.scene_ids]
    assert linked_sections
    assert scene.evidence_ids[0] in linked_sections[0].evidence_ids


def test_link_scenes_to_script_is_idempotent(tmp_path):
    store = StoryLabStore(str(tmp_path))
    project = store.create(StoryProjectCreate(title="Film", kind="movie"))
    source = tmp_path/"film.srt"
    source.write_text("1\\n00:00:10,000 --> 00:00:12,500\\nA key reveal happens.\\n", encoding="utf-8")
    project = store.ingest(project.id, str(source))
    project = store.analyze(project.id)
    before = [list(section.scene_ids) for section in project.script]
    project = store.link_scenes_to_script(project.id)
    after = [list(section.scene_ids) for section in project.script]
    assert after == before


def test_semantic_scene_search_ranks_matching_evidence_and_adds_context(tmp_path):
    store = StoryLabStore(str(tmp_path))
    project = store.create(StoryProjectCreate(title="Film", kind="movie", brief={"question": "Why did the character leave?"}))
    source = tmp_path/"film.srt"
    source.write_text("1\n00:00:10,000 --> 00:00:12,000\nThe character leaves because the warning changes everything.\n\n2\n00:00:30,000 --> 00:00:32,000\nA landscape is shown.\n", encoding="utf-8")
    project = store.ingest(project.id, str(source))
    project.sources[0] = project.sources[0].model_copy(update={"kind": "video"})
    project = store.analyze(project.id)
    project.scenes = []
    project = store.search_scenes(project.id, query="Why did the character leave?", context_seconds=2)
    assert project.scenes
    assert project.scenes[0].start == 8.0
    assert project.scenes[0].end == 14.0
    assert project.scenes[0].query == "why did the character leave?"
    assert project.scenes[0].relevance > 0

def test_scene_search_is_idempotent_for_same_query(tmp_path):
    store = StoryLabStore(str(tmp_path))
    project = store.create(StoryProjectCreate(title="Film", kind="movie", brief={"question": "Why?"}))
    source = tmp_path/"film.srt"
    source.write_text("1\n00:00:10,000 --> 00:00:12,000\nThe reason is explained here.\n", encoding="utf-8")
    project = store.ingest(project.id, str(source))
    project.sources[0] = project.sources[0].model_copy(update={"kind": "video"})
    project = store.analyze(project.id)
    count = len(project.scenes)
    project = store.search_scenes(project.id, query="reason", context_seconds=1)
    assert len(project.scenes) >= count
    project = store.search_scenes(project.id, query="reason", context_seconds=1)
    reason_scenes = [s for s in project.scenes if s.query == "reason"]
    assert len(reason_scenes) == 1
