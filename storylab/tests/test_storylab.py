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
