import React, { useEffect, useState } from 'react';
import { Film, Plus, Sparkles, Clock3, BookOpen, Lightbulb, CheckCircle2, FileText, Clapperboard } from 'lucide-react';
import { apiJson } from '../lib/api';

const kinds = ['movie', 'series', 'anime', 'episode', 'documentary', 'other'];
const angles = [
  ['story', 'Story / plot'],
  ['why', 'Why / explanation'],
  ['theory', 'Theory / clues'],
  ['character', 'Character study'],
  ['theme', 'Theme / meaning'],
  ['lore', 'Lore / canon'],
  ['worldbuilding', 'Worldbuilding'],
  ['ending', 'Ending explained'],
  ['adaptation', 'Adaptation'],
  ['review', 'Review / analysis'],
  ['documentary', 'Documentary'],
];

export default function StoryLabTab() {
  const [projects, setProjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [title, setTitle] = useState('');
  const [kind, setKind] = useState('movie');
  const [angle, setAngle] = useState('story');
  const [question, setQuestion] = useState('');
  const [transcript, setTranscript] = useState('');
  const [upload, setUpload] = useState(null);
  const [transcribe, setTranscribe] = useState(true);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [sceneQuery, setSceneQuery] = useState('');
  const [sceneSearchMode, setSceneSearchMode] = useState('hybrid');
  const [sceneEmbeddingProvider, setSceneEmbeddingProvider] = useState('local');

  const replaceProject = (project) => { setSelected(project); setProjects(prev => prev.map(p => p.id === project.id ? project : p)); };

  const load = async () => {
    try { const data = await apiJson('/api/storylab/projects'); setProjects(data.projects || []); }
    catch (e) { setError(e.message || 'Could not load Story Lab projects.'); }
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    if (!title.trim()) return;
    setCreating(true); setError('');
    try {
      const project = await apiJson('/api/storylab/projects', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({title: title.trim(), kind, brief: {angle, question}}) });
      setProjects(prev => [project, ...prev]); setSelected(project); setTitle(''); setQuestion('');
    } catch (e) { setError(e.message || 'Could not create project.'); }
    finally { setCreating(false); }
  };

  const analyze = async () => {
    if (!selected) return;
    setLoading(true); setError('');
    try {
      const project = await apiJson('/api/storylab/projects/' + selected.id + '/analyze', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ transcript }) });
      replaceProject(project);
    } catch (e) { setError(e.message || 'Analysis failed.'); }
    finally { setLoading(false); }
  };

  const uploadSource = async () => {
    if (!selected || !upload) return;
    setLoading(true); setError('');
    try {
      const body = new FormData(); body.append('file', upload);
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/sources/upload?transcribe=' + String(transcribe), { method:'POST', body }));
      setUpload(null);
    } catch (e) { setError(e.message || 'Could not upload source.'); }
    finally { setLoading(false); }
  };

  const addTextSource = async () => {
    if (!selected || !transcript.trim()) return;
    setLoading(true); setError('');
    try { replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/sources/text', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: transcript.includes('-->') ? 'pasted-source.srt' : 'pasted-source.txt', text: transcript}) })); setTranscript(''); }
    catch (e) { setError(e.message || 'Could not add source text.'); }
    finally { setLoading(false); }
  };

  const evidenceStatus = (evidenceId) => selected?.reviews?.find(r => r.target_type === 'evidence' && r.target_id === evidenceId)?.status || 'pending';

  const evidenceById = (ids = []) => {
    const lookup = Object.fromEntries((selected?.analysis?.evidence || []).map(item => [item.id, item]));
    return ids.map(id => lookup[id]).filter(Boolean);
  };

  const sceneById = (ids = []) => {
    const lookup = Object.fromEntries((selected?.scenes || []).map(scene => [scene.id, scene]));
    return ids.map(id => lookup[id]).filter(Boolean);
  };

  const reviewEvidence = async (evidence, status) => {
    setLoading(true); setError('');
    try {
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/review', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({target_type:'evidence', target_id:evidence.id, status})
      }));
    } catch (e) { setError(e.message || 'Could not update evidence review.'); }
    finally { setLoading(false); }
  };

  const review = async (section) => {
    setLoading(true); setError('');
    try { replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/review', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({target_type:'script', target_id:section.id, status:'approved'}) })); }
    catch (e) { setError(e.message || 'Could not approve section.'); }
    finally { setLoading(false); }
  };

  const reviewVisual = async (visual) => {
    setLoading(true); setError('');
    try { replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/visual-review', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({target_type:'visual', target_id:visual.id, status:'approved'}) })); }
    catch (e) { setError(e.message || 'Could not approve visual research item.'); }
    finally { setLoading(false); }
  };

  const saveBrief = async (patch) => {
    if (!selected) return;
    setLoading(true); setError('');
    try {
      const brief = {...(selected.brief || {}), ...patch};
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/brief', {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(brief)
      }));
    } catch (e) { setError(e.message || 'Could not update story brief.'); }
    finally { setLoading(false); }
  };

  const searchScenes = async (query = '') => {
    if (!selected) return;
    setLoading(true); setError('');
    try { replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/scenes/search', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query, search_mode: sceneSearchMode, embedding_provider: sceneEmbeddingProvider, max_results: 12})})); }
    catch (e) { setError(e.message || 'Could not search scenes.'); }
    finally { setLoading(false); }
  };

  const extractScenes = async (sceneIds = null) => {
    if (!selected) return;
    const ids = sceneIds || (selected.scenes||[]).filter(s=>s.extraction_status==='candidate').map(s=>s.id);
    if (!ids.length) return;
    setLoading(true); setError('');
    try { replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/scenes/extract', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scene_ids:ids})})); }
    catch (e) { setError(e.message || 'Could not extract scenes.'); }
    finally { setLoading(false); }
  };

  const render = async () => {
    setLoading(true); setError('');
    try { replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/render', { method:'POST' })); }
    catch (e) { setError(e.message || 'Render failed.'); }
    finally { setLoading(false); }
  };

  return <div className="space-y-6 animate-fade">
    <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
      <div><p className="eyebrow">09 · STORY LAB</p><h1 className="font-display lowercase text-3xl sm:text-4xl text-ink">Story Lab</h1><p className="text-sm text-muted mt-2 max-w-2xl">Analyze films, series and anime, connect theories to evidence, and turn the findings into documentary-ready stories.</p></div>
      <div className="flex items-center gap-2 text-xs text-muted"><Film size={15}/> long-form analysis</div>
    </div>
    <div className="grid lg:grid-cols-[280px_1fr] gap-4">
      <section className="card p-4 space-y-3">
        <div className="flex items-center justify-between"><span className="readout">PROJECTS</span><button className="btn-ghost" onClick={()=>setSelected(null)} title="new project"><Plus size={14}/></button></div>
        {projects.length === 0 ? <p className="text-xs text-muted py-5">No Story Lab projects yet.</p> : projects.map(p => <button key={p.id} onClick={()=>setSelected(p)} className={`w-full text-left p-3 rounded-input border transition-colors ${selected?.id===p.id?'border-brass bg-paper3':'border-rule hover:bg-paper3/60'}`}><div className="text-sm text-ink truncate">{p.title}</div><div className="text-[11px] text-muted mt-1">{p.kind} · {p.status}</div></button>)}
      </section>
      <section className="card p-5 sm:p-6">
        {!selected ? <div className="max-w-xl space-y-5"><div><div className="flex items-center gap-2 text-brass"><Sparkles size={16}/><span className="readout">NEW STORY</span></div><h2 className="font-display lowercase text-2xl text-ink mt-2">Start an analysis</h2></div><div className="grid sm:grid-cols-[1fr_150px] gap-3"><input className="input-field" placeholder="Movie, series, anime or story title" value={title} onChange={e=>setTitle(e.target.value)} onKeyDown={e=>e.key==='Enter'&&create()}/><select className="input-field" value={kind} onChange={e=>setKind(e.target.value)}>{kinds.map(k=><option key={k}>{k}</option>)}</select></div><div className="grid sm:grid-cols-2 gap-3"><select className="input-field" value={angle} onChange={e=>setAngle(e.target.value)}>{angles.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select><input className="input-field" placeholder="Optional question: Why did this happen?" value={question} onChange={e=>setQuestion(e.target.value)}/></div><button className="btn-primary" disabled={!title.trim()||creating} onClick={create}>{creating?'creating…':'create project'}</button></div> : <div className="space-y-6"><div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3"><div><p className="readout">{selected.kind.toUpperCase()} · {selected.status.toUpperCase()}</p><h2 className="font-display lowercase text-2xl text-ink mt-1">{selected.title}</h2></div><button className="btn-primary" disabled={loading} onClick={analyze}>{loading?'analyzing…':'analyze story'}</button></div><div><label className="readout block mb-2">SOURCE TEXT OR TRANSCRIPT</label><textarea className="input-field min-h-48 w-full resize-y" placeholder="Paste plain text or SRT/VTT source text. Timestamped text becomes exact evidence; plain text remains explicitly unlocated." value={transcript} onChange={e=>setTranscript(e.target.value)}/><div className="flex gap-2 mt-2"><button className="btn-ghost" disabled={loading||!transcript.trim()} onClick={addTextSource}><FileText size={14}/> add as source</button><span className="text-xs text-muted self-center">{selected.sources?.length || 0} source(s) attached</span></div><div className="mt-4 rounded-input border border-rule p-3 space-y-2"><label className="readout block">UPLOAD SOURCE</label><input type="file" accept="video/*,audio/*,.pdf,.srt,.vtt,.txt,.md,.json" onChange={e=>setUpload(e.target.files?.[0] || null)} className="text-xs text-muted w-full"/><div className="flex items-center gap-3"><label className="text-xs text-muted flex items-center gap-2"><input type="checkbox" checked={transcribe} onChange={e=>setTranscribe(e.target.checked)}/> transcribe video/audio with local ASR</label><button className="btn-ghost" disabled={loading||!upload} onClick={uploadSource}><FileText size={14}/> upload source</button></div><p className="text-[11px] text-muted">PDFs use local text extraction. Video/audio uses the existing local Whisper/Parakeet pipeline when enabled.</p></div></div>{selected.analysis && <div className="grid md:grid-cols-2 gap-4"><div className="rounded-input border border-rule p-4"><div className="flex items-center gap-2 text-brass mb-2"><BookOpen size={15}/><span className="readout">STORY</span></div><p className="text-sm text-ink2 leading-relaxed">{selected.analysis.summary}</p><p className="text-xs text-muted mt-2">Lens: {selected.brief?.angle || 'story'}{selected.brief?.question ? ' · '+selected.brief.question : ''}</p>
<div className="mt-4 rounded-input border border-rule p-3">
  <div className="flex items-center justify-between mb-2"><span className="readout">STORY BRIEF</span><span className="text-[10px] text-muted">controls the next analysis</span></div>
  <div className="grid sm:grid-cols-2 gap-2">
    <select className="input-field" value={selected.brief?.angle || 'story'} onChange={e=>saveBrief({angle:e.target.value})}>{angles.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select>
    <select className="input-field" value={selected.brief?.spoiler_policy || 'light'} onChange={e=>saveBrief({spoiler_policy:e.target.value})}><option value="none">No spoilers</option><option value="light">Light spoilers</option><option value="full">Full spoilers</option></select>
  </div>
  <input className="input-field w-full mt-2" placeholder="Central question" value={selected.brief?.question || ''} onChange={e=>replaceProject({...selected,brief:{...(selected.brief||{}),question:e.target.value}})} onBlur={e=>saveBrief({question:e.target.value})}/>
  <div className="grid sm:grid-cols-2 gap-2 mt-2">
    <input className="input-field" placeholder="Audience (optional)" value={selected.brief?.audience || ''} onChange={e=>replaceProject({...selected,brief:{...(selected.brief||{}),audience:e.target.value}})} onBlur={e=>saveBrief({audience:e.target.value})}/>
    <input className="input-field" placeholder="Tone (e.g. analytical)" value={selected.brief?.tone || 'clear'} onChange={e=>replaceProject({...selected,brief:{...(selected.brief||{}),tone:e.target.value}})} onBlur={e=>saveBrief({tone:e.target.value})}/>
  </div>
</div><p className="text-xs text-muted mt-3">{selected.analysis.story?.conflict}</p></div><div className="rounded-input border border-rule p-4"><div className="flex items-center gap-2 text-brass mb-2"><Lightbulb size={15}/><span className="readout">THEORIES</span></div><p className="text-xs text-muted">Interpretation stays separate from evidence.</p></div></div>}
{selected.analysis && <div className="space-y-3">
  <div className="flex items-center justify-between"><span className="readout">STORY BUILDER</span><span className="text-[11px] text-muted">source-linked structure</span></div>
  <div className="grid md:grid-cols-2 gap-3">
    {[
      ['Central question', selected.analysis.story?.central_question, selected.analysis.story?.central_question_evidence_ids],
      ['Interpretation', selected.analysis.story?.interpretation, selected.analysis.story?.interpretation_evidence_ids],
      ['Counterpoints', selected.analysis.story?.counterpoints?.join(' '), selected.analysis.story?.counterpoint_evidence_ids?.flat()],
      ['Open questions', selected.analysis.story?.open_questions?.join(' '), selected.analysis.story?.open_question_evidence_ids?.flat()],
      ['Hook', selected.analysis.story?.hook, selected.analysis.story?.hook_evidence_ids],
      ['Context', selected.analysis.story?.context, selected.analysis.story?.context_evidence_ids],
      ['Conflict', selected.analysis.story?.conflict, selected.analysis.story?.conflict_evidence_ids],
      ['Consequences', selected.analysis.story?.consequences, selected.analysis.story?.consequences_evidence_ids],
      ['Significance', selected.analysis.story?.significance, selected.analysis.story?.significance_evidence_ids]
    ].map(([label,text,ids]) => text ? <div key={label} className="rounded-input border border-rule p-3"><div className="text-xs uppercase tracking-wide text-brass">{label}</div><p className="text-sm text-ink2 mt-1 leading-relaxed">{text}</p><div className="flex flex-wrap gap-1 mt-2">{evidenceById(ids).map(e => <span key={e.id} className="text-[10px] rounded border border-rule px-1.5 py-0.5 text-muted">{e.page ? 'p.'+e.page : e.start != null ? e.start.toFixed(1)+'s' : 'source'} · {e.id.slice(-6)}</span>)}</div></div> : null)}
  </div>
  {selected.analysis.story?.timeline?.length > 0 && <div className="rounded-input border border-rule p-3"><div className="text-xs uppercase tracking-wide text-brass">Timeline</div><div className="mt-2 space-y-2">{selected.analysis.story.timeline.map((item,index) => <div key={index} className="flex gap-2 text-sm text-ink2"><span className="text-muted">{String(index+1).padStart(2,'0')}</span><div><div>{item}</div><div className="flex flex-wrap gap-1 mt-1">{evidenceById(selected.analysis.story.timeline_evidence_ids?.[index] || []).map(e => <span key={e.id} className="text-[10px] rounded border border-rule px-1.5 py-0.5 text-muted">{e.page ? 'p.'+e.page : e.start != null ? e.start.toFixed(1)+'s' : 'source'}</span>)}</div></div></div>)}</div></div>}
  {selected.analysis.story?.key_events?.length > 0 && <div className="rounded-input border border-rule p-3"><div className="text-xs uppercase tracking-wide text-brass">Key Events</div><div className="mt-2 space-y-2">{selected.analysis.story.key_events.map((item,index) => <div key={index} className="text-sm text-ink2"><span className="text-muted mr-2">{index+1}.</span>{item}</div>)}</div></div>}
  {selected.analysis.story?.people?.length > 0 && <div className="rounded-input border border-rule p-3"><div className="text-xs uppercase tracking-wide text-brass">People / Actors</div><div className="mt-2 space-y-2">{selected.analysis.story.people.map((item,index) => <div key={index} className="text-sm text-ink2"><span className="text-muted mr-2">{index+1}.</span>{item}</div>)}</div></div>}
</div>}
{selected.analysis?.insights?.length>0 && <div className="space-y-3">
  <div className="flex items-center justify-between"><span className="readout">STORY INTELLIGENCE</span><span className="text-[11px] text-muted">{selected.analysis.insights.length} reviewable insight(s)</span></div>
  <div className="grid md:grid-cols-2 gap-3">
    {selected.analysis.insights.map(insight => {
      const reviewStatus = evidenceStatus(insight.id);
      const status = insight.status || reviewStatus;
      return <div key={insight.id} className="rounded-input border border-rule p-3">
        <div className="flex items-center justify-between gap-2"><div className="text-xs uppercase tracking-wide text-brass">{insight.type}</div><span className="text-[10px] uppercase text-muted">{status}</span></div>
        <div className="text-sm text-ink mt-1">{insight.title}</div>
        <p className="text-sm text-ink2 mt-1 leading-relaxed">{insight.text}</p>
        <div className="flex flex-wrap gap-1 mt-2">{evidenceById(insight.evidence_ids || []).map(e => <span key={e.id} className="text-[10px] rounded border border-rule px-1.5 py-0.5 text-muted">{e.page ? 'p.'+e.page : e.start != null ? e.start.toFixed(1)+'s' : 'source'} · {e.id.slice(-6)}</span>)}</div>
        <div className="flex items-center gap-2 mt-3">
          {status !== 'approved' && <button className="btn-ghost text-[11px]" disabled={loading} onClick={()=>reviewEvidence(insight,'approved')}>approve insight</button>}
          {status !== 'challenged' && <button className="btn-ghost text-[11px]" disabled={loading} onClick={()=>reviewEvidence(insight,'changes_requested')}>challenge insight</button>}
        </div>
      </div>;
    })}
  </div>
</div>}
{selected.analysis && <div className="space-y-3">
  <div className="space-y-2">
    <div className="flex items-center justify-between"><span className="readout">SCENE RESEARCH</span><div className="flex gap-2"><button className="btn-ghost" disabled={loading} onClick={()=>searchScenes(sceneQuery || selected.brief?.question || selected.analysis?.story?.central_question || '')}>search</button>{selected.scenes?.some(s=>s.extraction_status==='candidate') && <button className="btn-primary" disabled={loading} onClick={extractScenes}>extract {selected.scenes.filter(s=>s.extraction_status==='candidate').length} scene(s)</button>}</div></div>
    <div className="flex flex-col sm:flex-row gap-2">
      <input className="input-field flex-1" placeholder="Search the source by meaning or exact words" value={sceneQuery} onChange={e=>setSceneQuery(e.target.value)} onKeyDown={e=>e.key==='Enter'&&searchScenes(e.target.value)} />
      <select className="input-field sm:w-40" value={sceneEmbeddingProvider} onChange={e=>setSceneEmbeddingProvider(e.target.value)}><option value="local">Local · no model</option><option value="auto">Auto · cached model</option><option value="sentence-transformers">Pretrained · download</option></select><select className="input-field sm:w-40" value={sceneSearchMode} onChange={e=>setSceneSearchMode(e.target.value)}><option value="hybrid">Hybrid local</option><option value="embedding">Vector only</option><option value="lexical">Exact words</option></select>
    </div>
    {selected.scenes?.length ? <div className="grid md:grid-cols-2 gap-3">{selected.scenes.map(scene=><div key={scene.id} className="rounded-input border border-rule p-3"><div className="flex justify-between gap-2"><div className="text-sm text-ink">{scene.title}</div><span className="text-[10px] uppercase text-muted">{scene.extraction_status}</span></div><div className="text-xs text-muted mt-1">{scene.start.toFixed(3)}s — {scene.end.toFixed(3)}s · relevance {Math.round(scene.relevance*100)}% · {scene.search_method || 'hybrid'}</div><p className="text-xs text-ink2 mt-2">{scene.purpose}</p><div className="flex flex-wrap gap-1 mt-2">{scene.evidence_ids?.map(id=><span key={id} className="text-[10px] rounded border border-rule px-1.5 py-0.5 text-muted">{id.slice(-6)}</span>)}</div>{scene.output_file && <p className="text-[10px] text-muted mt-2 break-all">{scene.output_file}</p>}</div>)}</div> : <p className="text-xs text-muted">Analyze the project, then Story Lab can search timestamp-backed source moments without Ollama or a cloud embedding service.</p>}
  </div>
</div>}{selected.analysis?.evidence?.length>0 && <div className="space-y-2"><div className="flex items-center justify-between"><span className="readout">EVIDENCE WORKSPACE</span><span className="text-[11px] text-muted">{selected.analysis.evidence.length} cited excerpt(s)</span></div>{selected.analysis.evidence.map(e=>{ const status=evidenceStatus(e.id); return <div key={e.id} className="rounded-input border border-rule p-3"><div className="flex gap-3"><Clock3 size={14} className="text-brass mt-0.5"/><div className="min-w-0 flex-1"><div className="text-sm text-ink">{e.start != null ? e.start.toFixed(3)+'s — '+e.end.toFixed(3)+'s' : e.page ? 'page '+e.page : 'unlocated text'} · {e.label}</div><p className="text-xs text-muted mt-1">{e.claim}</p><p className="text-[11px] text-muted mt-1">{e.traceability} · confidence {Math.round(e.confidence * 100)}%</p>{e.supporting_text && <p className="text-xs text-ink2 mt-2 whitespace-pre-wrap">{e.supporting_text}</p>}<div className="flex items-center gap-2 mt-3"><span className="text-[10px] uppercase tracking-wide text-muted">{status.replace('_',' ')}</span>{status !== 'approved' && <button className="btn-ghost text-[11px]" disabled={loading} onClick={()=>reviewEvidence(e,'approved')}>approve evidence</button>}{status !== 'changes_requested' && <button className="btn-ghost text-[11px]" disabled={loading} onClick={()=>reviewEvidence(e,'changes_requested')}>request changes</button>}</div></div></div></div>})}</div>}{selected.script?.length>0 && <div className="space-y-2"><div className="flex justify-between items-center"><span className="readout">SCRIPT & VISUAL RESEARCH</span>{selected.status==='approved' && <button className="btn-primary" disabled={loading} onClick={render}><Clapperboard size={14}/> render source assembly</button>}</div>{selected.script.map(section=><div key={section.id} className="rounded-input border border-rule p-3"><div className="flex justify-between gap-3"><div><div className="text-sm text-ink">{section.heading} · {section.duration_seconds}s</div><p className="text-xs text-muted mt-1">{section.narration}</p><p className="text-xs text-muted mt-2">Visual: {section.visual_suggestions?.map(v=>v.material_type.replace('_',' ')).join(', ')}</p>{sceneById(section.scene_ids || []).length > 0 && <div className="mt-3 rounded border border-rule p-2"><div className="text-[10px] uppercase tracking-wide text-brass">SOURCE SCENES</div><div className="mt-2 space-y-2">{sceneById(section.scene_ids || []).map(scene=><div key={scene.id} className="flex items-center justify-between gap-2"><div><div className="text-xs text-ink">{scene.title}</div><div className="text-[10px] text-muted">{scene.start.toFixed(3)}s — {scene.end.toFixed(3)}s · {scene.extraction_status}</div></div>{scene.extraction_status==='candidate' && <button className="btn-ghost text-[10px]" disabled={loading} onClick={()=>extractScenes([scene.id])}>extract scene</button>}</div>)}</div></div>}{section.visual_research?.length>0 && <div className="mt-3 space-y-2">{section.visual_research.map(v=><div key={v.id} className="rounded border border-rule p-2"><div className="flex justify-between gap-2"><span className="text-xs text-ink">{v.material_type.replace('_',' ')}: {v.description}</span><button className="btn-ghost text-[11px]" disabled={loading||v.status==='approved'} onClick={()=>reviewVisual(v)}>{v.status==='approved'?'visual approved':'approve visual'}</button></div><p className="text-[10px] text-muted mt-1">{v.evidence_ids?.length||0} evidence link(s){v.source_id ? ' · source linked' : ' · asset needed'}</p></div>)}</div>}</div><button className="btn-ghost" disabled={loading||section.approved} onClick={()=>review(section)}>{section.approved ? <><CheckCircle2 size={14}/> approved</> : 'approve'}</button></div></div>)}</div>}{selected.renders?.length>0 && <p className="text-xs text-muted">Latest render: {selected.renders[selected.renders.length-1].status}. A source-assembly file is created only for approved, timestamp-backed video excerpts.</p>}</div>}
      </section>
    </div>
    {error && <div className="rounded-input border border-rule2 p-3 text-sm text-warn">{error}</div>}
  </div>;
}
