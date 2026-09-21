from storylab.models import StoryProjectCreate,Evidence
from storylab.evidence import normalize_evidence
from storylab.service import StoryLabStore
def test_evidence_is_clamped_to_duration():
    item=Evidence(id="e1",start=-2,end=99,label="x",claim="y"); normalized=normalize_evidence([item],duration=10); assert normalized[0].start==0; assert normalized[0].end==10
def test_store_create_and_reload(tmp_path):
    store=StoryLabStore(str(tmp_path)); p=store.create(StoryProjectCreate(title="Test film",kind="movie")); assert store.get(p.id).title=="Test film"; assert store.list()[0].id==p.id
def test_store_analysis_fallback(tmp_path):
    store=StoryLabStore(str(tmp_path)); p=store.create(StoryProjectCreate(title="Test film",kind="movie")); r=store.analyze(p.id,"A transcript with enough text to survive the fallback path."); assert r.status=="analyzed"; assert r.analysis is not None; assert r.script
