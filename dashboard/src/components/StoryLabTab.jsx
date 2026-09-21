import React, { useEffect, useRef, useState } from 'react';
import { Film, Plus, Sparkles, Clock3, BookOpen, Lightbulb, CheckCircle2, FileText, Clapperboard, HelpCircle, X, Copy, Check } from 'lucide-react';
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

export default function StoryLabTab({ uploadPostKey = '', uploadUserId = '', managed = false }) {
  const [projects, setProjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [title, setTitle] = useState('');
  const [kind, setKind] = useState('movie');
  const [angle, setAngle] = useState('story');
  const [question, setQuestion] = useState('');
  const [transcript, setTranscript] = useState('');
  const [upload, setUpload] = useState(null);
  const fileInputRef = useRef(null);
  const [transcribe, setTranscribe] = useState(true);
  const [loading, setLoading] = useState(false);
  const [busyLabel, setBusyLabel] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [sceneQuery, setSceneQuery] = useState('');
  const [sceneSearchMode, setSceneSearchMode] = useState('hybrid');
  const [sceneEmbeddingProvider, setSceneEmbeddingProvider] = useState('local');
  const [storyDraft, setStoryDraft] = useState(null);
  const [storyDirty, setStoryDirty] = useState(false);
  const [youtubeDirty, setYoutubeDirty] = useState(false);
  const [sourceMessage, setSourceMessage] = useState('');
  const [analysisMessage, setAnalysisMessage] = useState('');
  const [copiedMetadata, setCopiedMetadata] = useState('');
  const [voiceboxProfiles, setVoiceboxProfiles] = useState([]);
  const [voiceboxAvailable, setVoiceboxAvailable] = useState(false);
  const [voiceboxLoading, setVoiceboxLoading] = useState(false);
  const [voiceProfileId, setVoiceProfileId] = useState('');

  const replaceProject = (project) => { setSelected(project); setProjects(prev => prev.map(p => p.id === project.id ? project : p)); };

  const load = async () => {
    try { const data = await apiJson('/api/storylab/projects'); setProjects(data.projects || []); }
    catch (e) { setError(e.message || 'Could not load Story Lab projects.'); }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (selected?.script?.length) loadVoicebox();
  }, [selected?.id, selected?.script?.length]);
  useEffect(() => {
    if (selected?.analysis?.story) {
      setStoryDraft(selected.analysis.story);
      setStoryDirty(false);
    }
  }, [selected?.id, selected?.analysis?.story]);

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
    setLoading(true); setBusyLabel('Analyzing story…'); setError('');
    try {
      const project = await apiJson('/api/storylab/projects/' + selected.id + '/analyze', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ transcript }) });
      replaceProject(project);
      setAnalysisMessage('Analysis completed successfully. Story Intelligence and Story Builder are ready to review.');
    } catch (e) { setError(e.message || 'Analysis failed.'); setAnalysisMessage(''); }
    finally { setLoading(false); }
  };

  const uploadSource = async () => {
    if (!selected || !upload) return;
    setLoading(true); setError('');
    try {
      const body = new FormData(); body.append('file', upload);
      const project = await apiJson('/api/storylab/projects/' + selected.id + '/sources/upload?transcribe=' + String(transcribe), { method:'POST', body });
      replaceProject(project);
      const source = project.sources?.[project.sources.length - 1];
      const sourceLabel = source?.ingestion_source === 'embedded_english_subtitles' ? 'English subtitles detected and used.' : 'Source uploaded successfully.';
      setSourceMessage(source ? `${sourceLabel} ${source.name}` : sourceLabel);
      setUpload(null);
    } catch (e) { setError(e.message || 'Could not upload source.'); setSourceMessage(''); }
    finally { setLoading(false); }
  };

  const addTextSource = async () => {
    if (!selected || !transcript.trim()) return;
    setLoading(true); setError('');
    try { replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/sources/text', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: transcript.includes('-->') ? 'pasted-source.srt' : 'pasted-source.txt', text: transcript}) })); setTranscript(''); }
    catch (e) { setError(e.message || 'Could not add source text.'); }
    finally { setLoading(false); }
  };

  const loadVoicebox = async () => {
    setVoiceboxLoading(true);
    try {
      const status = await apiJson('/api/storylab/voicebox/status');
      setVoiceboxAvailable(Boolean(status.available));
      if (status.available) {
        const data = await apiJson('/api/storylab/voicebox/profiles');
        const profiles = data.profiles || [];
        setVoiceboxProfiles(profiles);
        setVoiceProfileId(prev => prev || profiles[0]?.id || '');
      }
    } catch (e) {
      setVoiceboxAvailable(false);
      setVoiceboxProfiles([]);
    } finally {
      setVoiceboxLoading(false);
    }
  };

  const generateVoiceover = async () => {
    if (!selected || !voiceProfileId) return;
    setLoading(true); setBusyLabel('Generating narration…'); setError('');
    try {
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/voiceover', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({profile_id: voiceProfileId})
      }));
    } catch (e) { setError(e.message || 'Voiceover generation failed.'); }
    finally { setLoading(false); setBusyLabel(''); }
  };

  const evidenceStatus = (evidenceId) => selected?.reviews?.find(r => r.target_type === 'evidence' && r.target_id === evidenceId)?.status || 'pending';
  const insightStatus = (insightId) => selected?.reviews?.find(r => r.target_type === 'insight' && r.target_id === insightId)?.status || 'pending';

  const evidenceById = (ids = []) => {
    const lookup = Object.fromEntries((selected?.analysis?.evidence || []).map(item => [item.id, item]));
    return [...new Set(ids)].map(id => lookup[id]).filter(Boolean);
  };

  const curatedEvidenceIds = () => {
    const story = selected?.analysis?.story;
    if (!story) return [];
    const groups = [
      story.hook_evidence_ids, story.context_evidence_ids, story.conflict_evidence_ids,
      story.consequences_evidence_ids, story.significance_evidence_ids,
      story.central_question_evidence_ids, story.interpretation_evidence_ids,
      ...(story.timeline_evidence_ids || []), ...(story.key_event_evidence_ids || []),
      ...(story.people_evidence_ids || []), ...(story.counterpoint_evidence_ids || []),
      ...(story.open_question_evidence_ids || [])
    ];
    return [...new Set(groups.flat().filter(Boolean))];
  };

  const curatedInsights = () => {
    const insights = selected?.analysis?.insights || [];
    const story = selected?.analysis?.story;
    const ids = new Set(story ? Object.values(story.component_insight_ids || {}).flat() : []);
    return ids.size ? insights.filter(item => ids.has(item.id)) : insights;
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
        body: JSON.stringify({target_type:evidence.type ? 'insight' : 'evidence', target_id:evidence.id, status})
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

  const selectScene = async (sceneId, checked) => {
    if (!selected) return;
    setLoading(true); setError('');
    try {
      const ids = (selected.scenes || []).filter(s => s.selected !== false && s.id !== sceneId).map(s => s.id);
      if (checked) ids.push(sceneId);
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/scenes/select', {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({scene_ids: ids})
      }));
    } catch (e) { setError(e.message || 'Could not update scene selection.'); }
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

  const saveYoutube = async (patch) => {
    if (!selected) return;
    setLoading(true); setError('');
    try {
      const youtube = {...(selected.youtube || {}), ...patch};
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/youtube', {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(youtube)
      }));
      setYoutubeDirty(false);
    } catch (e) { setError(e.message || 'Could not save YouTube metadata.'); }
    finally { setLoading(false); }
  };

  const copyMetadata = async (key, value) => {
    try {
      await navigator.clipboard.writeText(value || '');
      setCopiedMetadata(key);
      window.setTimeout(() => setCopiedMetadata(''), 1600);
    } catch (e) {
      setError('Could not copy to clipboard. You can still select and copy the text manually.');
    }
  };

  const copyAllMetadata = async () => {
    const youtube = selected?.youtube || {};
    const payload = [
      'TITLE',
      youtube.title || '',
      '',
      'DESCRIPTION',
      youtube.description || '',
      '',
      'TAGS',
      (youtube.tags || []).join(', ')
    ].join('\n');
    await copyMetadata('all', payload);
  };

  const updateStoryField = (field, value) => {
    setStoryDraft(prev => ({ ...(prev || {}), [field]: value }));
    setStoryDirty(true);
  };

  const scenesForEvidence = (evidenceIds = []) => {
    const wanted = new Set(evidenceIds || []);
    return (selected?.scenes || []).filter(scene =>
      (scene.evidence_ids || []).some(id => wanted.has(id))
    );
  };

  const saveStory = async () => {
    if (!selected || !storyDraft) return;
    setLoading(true); setError('');
    try {
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/story', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(storyDraft)
      }));
      setStoryDirty(false);
    } catch (e) { setError(e.message || 'Could not save story builder.'); }
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
      <div className="flex items-center gap-2"><button type="button" className="btn-ghost text-xs" onClick={()=>setHelpOpen(true)}><HelpCircle size={14}/> how Story Lab works</button><div className="flex items-center gap-2 text-xs text-muted"><Film size={15}/> long-form analysis</div></div>
    </div>
    <div className="grid lg:grid-cols-[280px_1fr] gap-4">
      <section className="card p-4 space-y-3">
        <div className="flex items-center justify-between"><span className="readout">PROJECTS</span><button className="btn-ghost" onClick={()=>setSelected(null)} title="new project"><Plus size={14}/></button></div>
        {projects.length === 0 ? <p className="text-xs text-muted py-5">No Story Lab projects yet.</p> : projects.map(p => <div key={p.id} className={`flex items-stretch gap-1 rounded-input border transition-colors ${selected?.id===p.id?'border-brass bg-paper3':'border-rule hover:bg-paper3/60'}`}>
          <button onClick={()=>setSelected(p)} className="flex-1 min-w-0 text-left p-3">
            <div className="text-sm text-ink truncate">{p.title}</div><div className="text-[11px] text-muted mt-1">{p.kind} · {p.status}</div>
          </button>
          <button type="button" className="px-2 text-muted hover:text-warn" title={`Delete ${p.title}`} aria-label={`Delete ${p.title}`} onClick={async (e)=>{
            e.stopPropagation();
            if (!window.confirm(`Delete “${p.title}”? This will permanently remove its sources, scenes, renders and analysis.`)) return;
            setLoading(true); setError('');
            try {
              await apiJson('/api/storylab/projects/' + p.id, { method:'DELETE' });
              setProjects(prev => prev.filter(item => item.id !== p.id));
              if (selected?.id === p.id) setSelected(null);
            } catch (err) { setError(err.message || 'Could not delete project.'); }
            finally { setLoading(false); }
          }}><X size={14}/></button>
        </div>)}
      </section>
      <section className="card p-5 sm:p-6">
        {!selected ? <div className="max-w-xl space-y-5"><div><div className="flex items-center gap-2 text-brass"><Sparkles size={16}/><span className="readout">NEW STORY</span></div><h2 className="font-display lowercase text-2xl text-ink mt-2">Start an analysis</h2></div><div className="grid sm:grid-cols-[1fr_150px] gap-3"><input className="input-field" placeholder="Movie, series, anime or story title" value={title} onChange={e=>setTitle(e.target.value)} onKeyDown={e=>e.key==='Enter'&&create()}/><select className="input-field" value={kind} onChange={e=>setKind(e.target.value)}>{kinds.map(k=><option key={k}>{k}</option>)}</select></div><div className="grid sm:grid-cols-2 gap-3"><select className="input-field" value={angle} onChange={e=>setAngle(e.target.value)}>{angles.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select><input className="input-field" placeholder="Optional question: Why did this happen?" value={question} onChange={e=>setQuestion(e.target.value)}/></div><button className="btn-primary" disabled={!title.trim()||creating} onClick={create}>{creating?'creating…':'create project'}</button></div> : <div className="space-y-6"><div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3"><div><p className="readout">{selected.kind.toUpperCase()} · {selected.status.toUpperCase()}</p><h2 className="font-display lowercase text-2xl text-ink mt-1">{selected.title}</h2></div><button className="btn-primary" disabled={loading} onClick={analyze}>{loading && busyLabel === 'Analyzing story…' ? 'analyzing…' : 'analyze story'}</button></div><div><div className="flex items-center justify-between mb-2"><label className="readout block">SOURCE TEXT OR TRANSCRIPT</label><span className="text-[10px] text-muted">Add text/transcript or upload media, then click Analyze Story</span></div><textarea className="input-field min-h-48 w-full resize-y" placeholder="Paste plain text or SRT/VTT source text. Timestamped text becomes exact evidence; plain text remains explicitly unlocated." value={transcript} onChange={e=>setTranscript(e.target.value)}/><div className="flex gap-2 mt-2"><button className="btn-ghost" disabled={loading||!transcript.trim()} onClick={addTextSource}><FileText size={14}/> add as source</button><span className="text-xs text-muted self-center">{selected.sources?.length || 0} source(s) attached</span></div>
{sourceMessage && <div className="mt-3 rounded border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs text-ink2"><CheckCircle2 size={14} className="inline mr-2 text-emerald-600"/>{sourceMessage}</div>}
{selected.sources?.length > 0 && <div className="mt-3 space-y-1">{selected.sources.map(source => <div key={source.id} className="flex items-center justify-between gap-3 rounded border border-rule px-3 py-2 text-[11px]"><span className="truncate text-ink2">{source.name}</span><span className="text-muted whitespace-nowrap">{source.ingestion_source === 'embedded_english_subtitles' ? 'English subtitles used' : source.ingestion_source === 'local_asr' ? 'local ASR' : source.ingestion_source?.replaceAll('_',' ')}</span></div>)}</div>}<div className="mt-4 rounded-input border border-rule p-3 space-y-3"><div className="rounded border border-brass/30 bg-paper3 p-3"><div className="flex items-center gap-2 text-xs text-brass uppercase tracking-wide"><Sparkles size={13}/> Recommended workflow</div><p className="text-xs text-muted mt-2 leading-relaxed">Create the project → add source text/transcript or upload video/audio → click <strong>Analyze Story</strong> → review Story Intelligence → edit the generated Story Builder only where needed → save it → review/approve script sections → select scenes → render.</p></div>
  <div className="flex items-center justify-between gap-3">
    <label className="readout block">UPLOAD SOURCE</label>
    <span className="text-[10px] text-muted text-right">Video: MP4, MKV, MOV, AVI, WebM, M4V · Audio: MP3, WAV, M4A, AAC, FLAC, OGG · Documents: PDF, SRT, VTT, TXT, MD, JSON</span>
  </div>
  <label
    htmlFor="storylab-source-file"
    className="relative block rounded-input border border-dashed border-rule p-6 text-center cursor-pointer hover:border-brass transition-colors"
    onDragOver={e=>{e.preventDefault();e.stopPropagation();e.currentTarget.classList.add('border-brass')}}
    onDragLeave={e=>{e.preventDefault();e.stopPropagation();e.currentTarget.classList.remove('border-brass')}}
    onDrop={e=>{e.preventDefault();e.stopPropagation();e.currentTarget.classList.remove('border-brass');const file=e.dataTransfer.files?.[0];if(file&&!loading)setUpload(file)}}
  >
    <input
      id="storylab-source-file"
      ref={fileInputRef}
      type="file"
      accept=".mp4,.mkv,.mov,.avi,.webm,.m4v,.mp3,.wav,.m4a,.aac,.flac,.ogg,.pdf,.srt,.vtt,.txt,.md,.json,video/*,audio/*,application/pdf,text/plain,text/markdown,application/json"
      onChange={e=>{const file=e.target.files?.[0];if(file)setUpload(file)}}
      disabled={loading}
      className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
    />
    <div className="flex justify-center mb-2"><Plus size={22}/></div>
    <p className="text-sm text-ink2">{upload ? 'File selected — click here to change it' : 'Click to choose a file or drag it here'}</p>
    <p className="text-[11px] text-muted mt-1">{upload ? upload.name : 'MKV and other supported video/audio files are accepted'}</p>
  </label>
  <div className="flex flex-wrap items-center gap-3">
    <label className="text-xs text-muted flex items-center gap-2">
      <input type="checkbox" checked={transcribe} onChange={e=>setTranscribe(e.target.checked)}/> transcribe video/audio with local ASR
    </label>
    <button type="button" className="btn-ghost" disabled={loading||!upload} onClick={uploadSource}><FileText size={14}/> upload source</button>
    {upload && <button type="button" className="btn-ghost" disabled={loading} onClick={()=>{setUpload(null);if(fileInputRef.current)fileInputRef.current.value='';}}>clear</button>}
  </div>
  <p className="text-[11px] text-muted">The file picker is a real browser file input covering the drop zone, so clicking the + area opens the system file finder.</p>
</div></div>{analysisMessage && selected.analysis && <div className="rounded border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs text-ink2"><CheckCircle2 size={14} className="inline mr-2 text-emerald-600"/>{analysisMessage}</div>}
{selected.analysis && <div className="grid md:grid-cols-2 gap-4"><div className="rounded-input border border-rule p-4"><div className="flex items-center gap-2 text-brass mb-2"><BookOpen size={15}/><span className="readout">STORY</span></div><p className="text-sm text-ink2 leading-relaxed">{selected.analysis.summary}</p><p className="text-xs text-muted mt-2">Lens: {selected.brief?.angle || 'story'}{selected.brief?.question ? ' · '+selected.brief.question : ''}</p>
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
</div><p className="text-xs text-muted mt-3">{selected.analysis.story?.conflict}</p></div><div className="rounded-input border border-rule p-4"><div className="flex items-center gap-2 text-brass mb-2"><Lightbulb size={15}/><span className="readout">THEORY / WHY ANGLE</span></div><p className="text-xs text-muted">This is the explanation the finished video should answer—not a plot recap.</p>{selected.brief?.question && <div className="mt-3 rounded border border-brass/30 bg-paper3 p-3"><div className="text-[10px] uppercase tracking-wide text-brass">CENTRAL QUESTION</div><p className="text-sm text-ink mt-1">{selected.brief.question}</p></div>}{selected.analysis?.theories?.length ? <div className="mt-3 space-y-2">{selected.analysis.theories.map(theory=><div key={theory.id} className="rounded border border-rule p-3"><div className="text-xs font-medium text-ink">{theory.title}</div><p className="text-xs text-ink2 mt-1 leading-relaxed">{theory.claim}</p><div className="text-[10px] text-muted mt-2">{theory.evidence_ids?.length || 0} evidence link(s) · confidence {Math.round((theory.confidence || 0)*100)}%</div></div>)}</div> : <p className="text-xs text-muted mt-3">No explicit theory was generated yet. Use the Theory / clues angle and a precise question, then analyze again.</p>}</div></div>}
{selected.analysis && storyDraft && <div className="space-y-3"><div className="rounded border border-brass/30 bg-paper3 p-3 mb-3"><div className="text-xs uppercase tracking-wide text-brass">HOW TO USE STORY BUILDER</div><p className="text-xs text-muted mt-2 leading-relaxed">Story Builder is the editable narrative draft created from your evidence and insights. You normally do not write it from scratch. Read the generated hook, context, conflict, consequences, significance and interpretation; correct or refine wording when needed, keep claims grounded in the linked evidence, then click <strong>save story</strong>. The saved story automatically rebuilds the script and reconnects relevant source scenes.</p></div>
  <div className="flex items-center justify-between">
    <div><span className="readout">STORY BUILDER</span><div className="text-[11px] text-muted mt-1">Editable story claims with insight → evidence → scene provenance.</div></div>
    <button className="btn-primary" disabled={loading || !storyDirty} onClick={saveStory}>{loading ? 'saving…' : storyDirty ? 'save story' : 'saved'}</button>
  </div>
  <div className="grid md:grid-cols-2 gap-3">
    {[
      ['central_question','Central question'],
      ['hook','Hook'],
      ['context','Context'],
      ['conflict','Conflict'],
      ['consequences','Consequences'],
      ['significance','Significance'],
      ['interpretation','Interpretation']
    ].map(([field,label]) => {
      const ids = storyDraft.component_insight_ids?.[field] || [];
      const evidenceIds = storyDraft[field+'_evidence_ids'] || [];
      const insights = (selected.analysis.insights || []).filter(i => ids.includes(i.id));
      const scenes = scenesForEvidence(evidenceIds);
      return <div key={field} className="rounded-input border border-rule p-3">
        <div className="text-xs uppercase tracking-wide text-brass">{label}</div>
        <textarea className="input-field w-full mt-2 min-h-24 resize-y" value={storyDraft[field] || ''} onChange={e=>updateStoryField(field,e.target.value)} />
        <div className="flex flex-wrap gap-1 mt-2">
          {insights.map(i => <span key={i.id} className="text-[10px] rounded border border-brass/40 px-1.5 py-0.5 text-muted">{i.type} · {i.title}</span>)}
          {evidenceById(evidenceIds).map(e => <span key={e.id} className="text-[10px] rounded border border-rule px-1.5 py-0.5 text-muted">{e.page ? 'p.'+e.page : e.start != null ? e.start.toFixed(1)+'s' : 'source'} · evidence</span>)}
          {scenes.map(scene => <span key={scene.id} className="text-[10px] rounded border border-rule px-1.5 py-0.5 text-muted">scene · {scene.start.toFixed(1)}s</span>)}
        </div>
      </div>;
    })}
  </div>
  <div className="grid md:grid-cols-3 gap-3">
    {[
      ['timeline','Timeline', storyDraft.timeline || []],
      ['key_events','Key events', storyDraft.key_events || []],
      ['people','People / relationships', storyDraft.people || []],
      ['counterpoints','Counterpoints', storyDraft.counterpoints || []],
      ['open_questions','Open questions', storyDraft.open_questions || []]
    ].map(([field,label,items]) => {
      const ids = storyDraft.component_insight_ids?.[field] || [];
      const evidenceGroups = storyDraft[field+'_evidence_ids'] || [];
      const flatEvidence = Array.isArray(evidenceGroups) && evidenceGroups.every(x=>Array.isArray(x)) ? evidenceGroups.flat() : evidenceGroups;
      return <div key={field} className="rounded-input border border-rule p-3">
        <div className="text-xs uppercase tracking-wide text-brass">{label}</div>
        <textarea className="input-field w-full mt-2 min-h-28 resize-y" value={(items || []).join('\n')} onChange={e=>updateStoryField(field,e.target.value.split('\n').map(v=>v.trim()).filter(Boolean))} />
        <div className="flex flex-wrap gap-1 mt-2">
          {(selected.analysis.insights || []).filter(i=>ids.includes(i.id)).map(i=><span key={i.id} className="text-[10px] rounded border border-brass/40 px-1.5 py-0.5 text-muted">{i.type} · {i.title}</span>)}
          {evidenceById(flatEvidence).map(e=><span key={e.id} className="text-[10px] rounded border border-rule px-1.5 py-0.5 text-muted">evidence · {e.id.slice(-6)}</span>)}
        </div>
      </div>;
    })}
  </div>
</div>}
{selected.analysis?.insights?.length>0 && <div className="space-y-3">
  <div className="flex items-center justify-between"><span className="readout">STORY INTELLIGENCE</span><span className="text-[11px] text-muted">{selected.analysis.insights.length} reviewable insight(s)</span></div>
  <div className="grid md:grid-cols-2 gap-3">
    {selected.analysis.insights.map(insight => {
      const reviewStatus = insightStatus(insight.id);
      const status = reviewStatus === 'pending' ? (insight.status || 'unreviewed') : reviewStatus;
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
    {selected.scenes?.length ? <div className="grid md:grid-cols-2 gap-3">{selected.scenes.map(scene=><div key={scene.id} className="rounded-input border border-rule p-3"><div className="flex justify-between gap-2"><label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={scene.selected !== false} onChange={e=>selectScene(scene.id,e.target.checked)} />{scene.title}</label><span className="text-[10px] uppercase text-muted">{scene.extraction_status}</span></div><div className="text-xs text-muted mt-1">{scene.start.toFixed(3)}s — {scene.end.toFixed(3)}s · relevance {Math.round(scene.relevance*100)}% · {scene.search_method || 'hybrid'}</div><p className="text-xs text-ink2 mt-2">{scene.purpose}</p><div className="flex flex-wrap gap-1 mt-2">{scene.evidence_ids?.map(id=><span key={id} className="text-[10px] rounded border border-rule px-1.5 py-0.5 text-muted">{id.slice(-6)}</span>)}</div><div className="mt-3">{scene.output_file ? <video className="w-full aspect-video rounded border border-rule bg-black object-contain" controls playsInline preload="metadata" src={'/api/storylab/projects/' + selected.id + '/scenes/' + scene.id + '/file'} /> : <div className="w-full aspect-video rounded border border-dashed border-rule bg-paper3 flex items-center justify-center text-xs text-muted">Select this scene to extract the preview.</div>}<div className="flex items-center justify-between gap-2 mt-1"><p className="text-[10px] text-muted">source visual · {scene.extraction_status}</p>{scene.output_file && <a className="text-[10px] text-brass underline" href={'/api/storylab/projects/' + selected.id + '/scenes/' + scene.id + '/file'} target="_blank" rel="noreferrer">open clip</a>}</div></div></div>)}</div> : <p className="text-xs text-muted">Analyze the project, then Story Lab can search timestamp-backed source moments without Ollama or a cloud embedding service.</p>}
  </div>
</div>}{selected.analysis?.evidence?.length>0 && <div className="space-y-4">
  <div className="rounded-input border border-brass/30 bg-paper3 p-4 space-y-3">
    <div className="flex items-center justify-between gap-3">
      <div><span className="readout">EVIDENCE FOR THIS ANGLE</span><p className="text-xs text-muted mt-1">Only evidence linked to the generated question, theory, story sections and counterpoints is shown here. The full transcript remains available below.</p></div>
      <span className="text-[11px] text-muted">{evidenceById(curatedEvidenceIds()).length} relevant excerpt(s)</span>
    </div>
    <div className="grid sm:grid-cols-2 gap-2">
      {curatedInsights().slice(0, 8).map(insight => <div key={insight.id} className="rounded border border-rule p-3">
        <div className="flex items-center justify-between gap-2"><span className="text-[10px] uppercase tracking-wide text-brass">{insight.type}</span><span className="text-[10px] text-muted">{Math.round(insight.confidence * 100)}%</span></div>
        <div className="text-xs text-ink mt-1">{insight.title}</div>
        <p className="text-[11px] text-ink2 mt-1">{insight.text}</p>
        <p className="text-[10px] text-muted mt-2">{insight.evidence_ids?.length || 0} linked source excerpt(s)</p>
      </div>)}
    </div>
    <div className="space-y-2">
      {evidenceById(curatedEvidenceIds()).slice(0, 24).map(e => <div key={e.id} className="rounded border border-rule p-3">
        <div className="text-xs text-ink">{e.start != null ? e.start.toFixed(3)+'s — '+e.end.toFixed(3)+'s' : e.page ? 'page '+e.page : 'unlocated text'} · {e.label}</div>
        <p className="text-[11px] text-ink2 mt-1">{e.claim}</p>
        <p className="text-[10px] text-muted mt-1">{e.traceability} · confidence {Math.round(e.confidence * 100)}%</p>
      </div>)}
    </div>
  </div>
  <details className="rounded-input border border-rule p-4">
    <summary className="cursor-pointer text-xs text-ink">Show all source excerpts ({selected.analysis.evidence.length})</summary>
    <div className="mt-3 space-y-2">
      {selected.analysis.evidence.map(e => <div key={e.id} className="rounded border border-rule p-3">
        <div className="text-xs text-ink">{e.start != null ? e.start.toFixed(3)+'s — '+e.end.toFixed(3)+'s' : e.page ? 'page '+e.page : 'unlocated text'} · {e.label}</div>
        <p className="text-[11px] text-muted mt-1">{e.claim}</p>
      </div>)}
    </div>
  </details>
</div>}{selected.script?.length>0 && <div className="space-y-2"><div className="flex justify-between items-center"><span className="readout">SCRIPT & VISUAL RESEARCH</span>{selected.status==='approved' && <button className="btn-primary" disabled={loading} onClick={render}><Clapperboard size={14}/> create final video</button>}</div>{selected.script.map(section=><div key={section.id} className="rounded-input border border-rule p-3"><div className="flex justify-between gap-3"><div><div className="text-sm text-ink">{section.heading} · {section.duration_seconds}s</div><p className="text-xs text-muted mt-1">{section.narration}</p><p className="text-xs text-muted mt-2">Visual: {section.visual_suggestions?.map(v=>v.material_type.replace('_',' ')).join(', ')}</p>{sceneById(section.scene_ids || []).length > 0 && <div className="mt-3 rounded border border-rule p-2"><div className="text-[10px] uppercase tracking-wide text-brass">SOURCE SCENES</div><div className="mt-2 space-y-2">{sceneById(section.scene_ids || []).map(scene=><div key={scene.id} className="flex items-center justify-between gap-2"><div><div className="text-xs text-ink">{scene.title}</div><div className="text-[10px] text-muted">{scene.start.toFixed(3)}s — {scene.end.toFixed(3)}s · {scene.extraction_status}</div></div>{scene.extraction_status==='candidate' && <button className="btn-ghost text-[10px]" disabled={loading} onClick={()=>extractScenes([scene.id])}>extract scene</button>}</div>)}</div></div>}{section.visual_research?.length>0 && <div className="mt-3 space-y-2">{section.visual_research.map(v=><div key={v.id} className="rounded border border-rule p-2"><div className="flex justify-between gap-2"><span className="text-xs text-ink">{v.material_type.replace('_',' ')}: {v.description}</span><button className="btn-ghost text-[11px]" disabled={loading||v.status==='approved'} onClick={()=>reviewVisual(v)}>{v.status==='approved'?'visual approved':'approve visual'}</button></div><p className="text-[10px] text-muted mt-1">{v.evidence_ids?.length||0} evidence link(s){v.source_id ? ' · source linked' : ' · asset needed'}</p></div>)}</div>}</div><button className="btn-ghost" disabled={loading||section.approved} onClick={()=>review(section)}>{section.approved ? <><CheckCircle2 size={14}/> approved</> : 'approve'}</button></div></div>)}</div>}
{selected.script?.length>0 && <div className="rounded-input border border-brass/40 bg-paper3 p-4 space-y-4">
  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
    <div>
      <span className="readout">FINAL ASSEMBLY</span>
      <p className="text-xs text-muted mt-1">This is the production hand-off: script sections, approved narration and selected source visuals are brought together here in the exact order used by the renderer.</p>
    </div>
    <div className="flex flex-wrap items-center gap-2 text-[11px]">
      <span className="rounded-full border border-rule px-2 py-1">{selected.script.filter(s=>s.approved).length}/{selected.script.length} script approved</span>
      <span className="rounded-full border border-rule px-2 py-1">{(selected.scenes||[]).filter(s=>s.selected !== false).length} scenes selected</span>
      <span className="rounded-full border border-rule px-2 py-1">{(selected.scenes||[]).filter(s=>s.selected !== false && s.extraction_status === 'extracted').length} visuals extracted</span>
    </div>
  </div>
  <div className="space-y-2">
    {selected.script.map((section, index) => {
      const sectionScenes = sceneById(section.scene_ids || []).filter(scene => scene.selected !== false);
      return <div key={section.id} className="rounded-input border border-rule bg-paper p-3">
        <div className="flex items-start gap-3">
          <div className="text-[11px] text-muted w-6 pt-1">{String(index + 1).padStart(2,'0')}</div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
              <div className="text-sm text-ink">{section.heading}</div>
              <span className="text-[10px] uppercase text-muted">{section.duration_seconds}s · {section.approved ? 'approved' : 'needs approval'}</span>
            </div>
            <p className="text-xs text-ink2 mt-2 leading-relaxed">{section.narration}</p>
            {sectionScenes.length ? <div className="grid sm:grid-cols-2 gap-2 mt-3">
              {sectionScenes.map(scene => <div key={scene.id} className="rounded border border-rule overflow-hidden bg-black">
                {scene.output_file ? <video className="w-full aspect-video object-cover" controls preload="metadata" src={'/api/storylab/projects/' + selected.id + '/scenes/' + scene.id + '/file'} /> : <div className="aspect-video flex items-center justify-center text-[10px] text-muted bg-paper3">visual not extracted</div>}
                <div className="bg-paper px-2 py-1.5">
                  <div className="text-[11px] text-ink truncate">{scene.title}</div>
                  <div className="text-[10px] text-muted">{scene.start.toFixed(1)}s — {scene.end.toFixed(1)}s</div>
                </div>
              </div>)}
            </div> : <div className="mt-3 rounded border border-dashed border-rule p-3 text-[11px] text-muted">No selected source visual is linked to this section yet. Use Scene Research to search for a timestamp-backed moment, select it, and extract it.</div>}
          </div>
        </div>
      </div>;
    })}
  </div>
  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pt-2">
    <p className="text-[11px] text-muted">Final render uses the approved script, extracted section-linked source scenes and the generated Voicebox narration. Nothing is published automatically.</p>
    <button className="btn-primary" disabled={loading || selected.status !== 'approved' || selected.voiceover?.status !== 'generated'} onClick={render}><Clapperboard size={14}/> create final video</button>
  </div>
</div>}
{selected.script?.length>0 && <div className="space-y-4">
<div className="rounded-input border border-brass/40 bg-paper3 p-4 space-y-4">
  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
    <div>
      <span className="readout">NARRATION & VOICEOVER</span>
      <p className="text-xs text-muted mt-1">The narration is generated from the approved Story Lab script, so it follows the same question, theory/why angle, evidence and conclusion used by the video.</p>
    </div>
    <div className="flex flex-wrap gap-2">
      <a className="btn-ghost text-[11px]" href={'/api/storylab/projects/' + selected.id + '/download/narration'} download><FileText size={13}/> narration script</a>
      <a className="btn-ghost text-[11px]" href={'/api/storylab/projects/' + selected.id + '/download/narration-srt'} download><FileText size={13}/> timing SRT</a>
    </div>
  </div>
  <div className="rounded border border-rule p-3">
    <div className="flex flex-col sm:flex-row sm:items-end gap-3">
      <div className="flex-1">
        <label className="eyebrow block mb-1.5">LOCAL VOICEBOX VOICE</label>
        {voiceboxProfiles.length ? <select className="input-field w-full" value={voiceProfileId} onChange={e=>setVoiceProfileId(e.target.value)}>{voiceboxProfiles.map(profile=><option key={profile.id} value={profile.id}>{profile.name} · {profile.language || 'en'}</option>)}</select> : <div className="text-xs text-muted border border-dashed border-rule rounded p-3">{voiceboxLoading ? 'Checking Voicebox…' : voiceboxAvailable ? 'No Voicebox profiles found. Create a voice profile in Voicebox first.' : 'Voicebox is not connected.'}</div>}
      </div>
      <div className="flex gap-2">
        <button className="btn-ghost text-[11px]" disabled={voiceboxLoading || loading} onClick={loadVoicebox}>refresh</button>
        <button className="btn-primary text-[11px]" disabled={!voiceboxAvailable || !voiceProfileId || loading} onClick={generateVoiceover}>generate voiceover</button>
      </div>
    </div>
    {selected.voiceover?.status === 'generated' && <p className="text-[11px] text-emerald-700 mt-2">Voiceover generated with Voicebox and mixed into the latest final video.</p>}
    {selected.voiceover?.status === 'error' && <p className="text-[11px] text-warn mt-2">Voiceover failed: {selected.voiceover.error}</p>}
    <p className="text-[10px] text-muted mt-2">No ElevenLabs account or cloud API is required. Story Lab talks to the local Voicebox server on your computer.</p>
  </div>
</div>
{selected.renders?.length>0 && <div className="rounded-input border border-rule p-4 space-y-4"><div className="flex items-center justify-between gap-3"><div><span className="readout">FINAL VIDEO</span><p className="text-xs text-muted mt-1">The approved script and selected source visuals have been assembled into a video-ready MP4. Nothing is published automatically.</p></div>{selected.renders[selected.renders.length-1].status === 'rendered' && <a className="btn-primary" href={'/api/storylab/projects/' + selected.id + '/download/render'} download><FileText size={14}/> download final video</a>}</div><div className="text-xs text-muted">Latest render: {selected.renders[selected.renders.length-1].status}. Selected clips are extracted automatically and assembled in script order.</div>{selected.youtube && <>
<div className="rounded border border-rule p-3 space-y-4">
  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
    <div><span className="readout">YOUTUBE UPLOAD PACKAGE</span><p className="text-[11px] text-muted mt-1">Same quick-copy workflow as OpenShorts: edit the generated title, description and tags, then copy each field directly into YouTube Studio. Story Lab never publishes automatically.</p></div>
    <button className="btn-ghost text-[11px]" type="button" onClick={copyAllMetadata}><Copy size={13}/>{copiedMetadata === 'all' ? 'copied all' : 'copy all'}</button>
  </div>
  <div>
    <div className="flex items-center justify-between gap-2 mb-1.5"><label className="eyebrow">YOUTUBE TITLE</label><button type="button" className="btn-ghost text-[10px]" onClick={()=>copyMetadata('title', selected.youtube.title || '')}><>{copiedMetadata === 'title' ? <Check size={13}/> : <Copy size={13}/>}</> {copiedMetadata === 'title' ? 'copied' : 'copy'}</button></div>
    <input className="input-field w-full" maxLength={100} value={selected.youtube.title || ''} onChange={e=>replaceProject({...selected,youtube:{...selected.youtube,title:e.target.value}})} onBlur={()=>saveYoutube({title:selected.youtube.title})} placeholder="Video title"/>
  </div>
  <div>
    <div className="flex items-center justify-between gap-2 mb-1.5"><label className="eyebrow">YOUTUBE DESCRIPTION</label><button type="button" className="btn-ghost text-[10px]" onClick={()=>copyMetadata('description', selected.youtube.description || '')}><>{copiedMetadata === 'description' ? <Check size={13}/> : <Copy size={13}/>}</> {copiedMetadata === 'description' ? 'copied' : 'copy'}</button></div>
    <textarea className="input-field w-full min-h-40 resize-y" maxLength={5000} value={selected.youtube.description || ''} onChange={e=>replaceProject({...selected,youtube:{...selected.youtube,description:e.target.value}})} onBlur={()=>saveYoutube({description:selected.youtube.description})} placeholder="Video description"/>
  </div>
  <div>
    <div className="flex items-center justify-between gap-2 mb-1.5"><label className="eyebrow">YOUTUBE TAGS</label><button type="button" className="btn-ghost text-[10px]" onClick={()=>copyMetadata('tags', (selected.youtube.tags || []).join(', '))}><>{copiedMetadata === 'tags' ? <Check size={13}/> : <Copy size={13}/>}</> {copiedMetadata === 'tags' ? 'copied' : 'copy'}</button></div>
    <input className="input-field w-full" value={(selected.youtube.tags || []).join(', ')} onChange={e=>replaceProject({...selected,youtube:{...selected.youtube,tags:e.target.value.split(',').map(v=>v.trim()).filter(Boolean)}})} onBlur={()=>saveYoutube({tags:selected.youtube.tags || []})} placeholder="tag 1, tag 2, tag 3"/>
    <p className="text-[10px] text-muted mt-1">Copy uses comma-separated tags, ready to paste into YouTube's tags field.</p>
  </div>
  <div className="flex flex-wrap gap-2">
    <a className="btn-ghost" href={'/api/storylab/projects/' + selected.id + '/download/metadata'} download><FileText size={13}/> download metadata JSON</a>
  </div>
</div>
</>}
</div>}
</div>
</div>}
      </section>
    </div>
    {loading && busyLabel === 'Analyzing story…' && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"><div className="card max-w-md w-full p-6 text-center shadow-xl"><div className="mx-auto mb-4 h-10 w-10 rounded-full border-2 border-brass border-t-transparent animate-spin"></div><div className="readout text-brass">ANALYZING STORY</div><p className="text-sm text-ink mt-2">Story Lab is reading the supplied sources, extracting evidence, building insights and generating the story outline.</p><p className="text-xs text-muted mt-2">This can take a while for video/audio because transcription may run first.</p></div></div>}
    {helpOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={()=>setHelpOpen(false)}><div className="card max-w-2xl w-full max-h-[85vh] overflow-y-auto p-6" onClick={e=>e.stopPropagation()}><div className="flex items-center justify-between"><div><div className="readout text-brass">HOW STORY LAB WORKS</div><h3 className="font-display lowercase text-2xl text-ink mt-1">From source to finished story</h3></div><button className="btn-ghost" onClick={()=>setHelpOpen(false)}><X size={16}/></button></div><div className="mt-5 space-y-4 text-sm text-ink2"><div><strong>1. Create a project.</strong><p className="text-xs text-muted mt-1">Enter the title, choose the type, and select the editorial angle. The angle changes what Story Lab looks for; it does not change the source evidence.</p></div><div><strong>2. Add your sources.</strong><p className="text-xs text-muted mt-1">Paste a transcript/source text or upload video, audio, PDF, SRT/VTT, TXT, Markdown or JSON. For video/audio, enable local transcription when you want Story Lab to extract spoken content.</p></div><div><strong>3. Analyze Story.</strong><p className="text-xs text-muted mt-1">Analysis is a deliberate step. Click <strong>Analyze Story</strong> after your sources are attached. The analysis screen shows that Story Lab is working while transcription, evidence extraction and story analysis run.</p></div><div><strong>4. Review Story Intelligence.</strong><p className="text-xs text-muted mt-1">Facts, events, characters, themes, theories, interpretations, questions and counterpoints are separated and linked back to evidence. Approve or challenge insights as needed.</p></div><div><strong>5. Use Story Builder.</strong><p className="text-xs text-muted mt-1">Treat the generated Story Builder as your editable narrative draft. Refine the central question, hook, context, conflict, consequences, significance, interpretation, timeline, key events, people, counterpoints and open questions. Keep changes consistent with the evidence shown underneath each field, then save the story.</p></div><div><strong>6. Build and review the script.</strong><p className="text-xs text-muted mt-1">The saved story feeds the script builder. Approve each script section after checking its narration, evidence and visual research.</p></div><div><strong>7. Select scenes and render.</strong><p className="text-xs text-muted mt-1">Search the source for relevant moments, select the scenes you want, extract them, and create the final text-and-visual video. Download the MP4 and the generated title, description and tags; Story Lab does not publish automatically.</p></div><div className="rounded border border-brass/30 bg-paper3 p-3"><strong>Language:</strong><p className="text-xs text-muted mt-1">Story Lab's analysis output is intended to be English. Source material may be in another language; the analysis should translate the meaning into English while preserving necessary proper names and original titles.</p></div></div></div></div>}
    {error && <div className="rounded-input border border-rule2 p-3 text-sm text-warn">{error}</div>}
  </div>;
}
