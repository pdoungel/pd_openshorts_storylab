import React, { useEffect, useState } from 'react';
import { Film, Plus, Search, Sparkles, Clock3, BookOpen, Lightbulb } from 'lucide-react';
import { apiJson } from '../lib/api';

const kinds = ['movie', 'series', 'anime', 'episode'];

export default function StoryLabTab() {
  const [projects, setProjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [title, setTitle] = useState('');
  const [kind, setKind] = useState('movie');
  const [transcript, setTranscript] = useState('');
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    try { const data = await apiJson('/api/storylab/projects'); setProjects(data.projects || []); }
    catch (e) { setError(e.message || 'Could not load Story Lab projects.'); }
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    if (!title.trim()) return;
    setCreating(true); setError('');
    try {
      const project = await apiJson('/api/storylab/projects', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({title: title.trim(), kind}) });
      setProjects(prev => [project, ...prev]); setSelected(project); setTitle('');
    } catch (e) { setError(e.message || 'Could not create project.'); }
    finally { setCreating(false); }
  };

  const analyze = async () => {
    if (!selected) return;
    setLoading(true); setError('');
    try {
      const project = await apiJson('/api/storylab/projects/' + selected.id + '/analyze', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ transcript }) });
      setSelected(project); setProjects(prev => prev.map(p => p.id === project.id ? project : p));
    } catch (e) { setError(e.message || 'Analysis failed.'); }
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
        {!selected ? <div className="max-w-xl space-y-5"><div><div className="flex items-center gap-2 text-brass"><Sparkles size={16}/><span className="readout">NEW STORY</span></div><h2 className="font-display lowercase text-2xl text-ink mt-2">Start an analysis</h2></div><div className="grid sm:grid-cols-[1fr_150px] gap-3"><input className="input-field" placeholder="Movie or episode title" value={title} onChange={e=>setTitle(e.target.value)} onKeyDown={e=>e.key==='Enter'&&create()}/><select className="input-field" value={kind} onChange={e=>setKind(e.target.value)}>{kinds.map(k=><option key={k}>{k}</option>)}</select></div><button className="btn-primary" disabled={!title.trim()||creating} onClick={create}>{creating?'creating…':'create project'}</button></div> : <div className="space-y-6"><div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3"><div><p className="readout">{selected.kind.toUpperCase()} · {selected.status.toUpperCase()}</p><h2 className="font-display lowercase text-2xl text-ink mt-1">{selected.title}</h2></div><button className="btn-primary" disabled={loading} onClick={analyze}>{loading?'analyzing…':'analyze story'}</button></div><div><label className="readout block mb-2">TRANSCRIPT / TIMED SOURCE TEXT</label><textarea className="input-field min-h-48 w-full resize-y" placeholder="Paste a transcript here for the first analysis pass. Timestamped source material can later produce exact evidence ranges." value={transcript} onChange={e=>setTranscript(e.target.value)}/></div>{selected.analysis && <div className="grid md:grid-cols-2 gap-4"><div className="rounded-input border border-rule p-4"><div className="flex items-center gap-2 text-brass mb-2"><BookOpen size={15}/><span className="readout">SUMMARY</span></div><p className="text-sm text-ink2 leading-relaxed">{selected.analysis.summary}</p></div><div className="rounded-input border border-rule p-4"><div className="flex items-center gap-2 text-brass mb-2"><Lightbulb size={15}/><span className="readout">THEORIES</span></div>{selected.analysis.theories?.length ? selected.analysis.theories.map(t=><div key={t.id} className="mb-3"><div className="text-sm text-ink">{t.title}</div><p className="text-xs text-muted mt-1">{t.claim}</p></div>) : <p className="text-xs text-muted">No timestamp-backed theories yet.</p>}</div></div>}{selected.analysis?.evidence?.length>0 && <div className="space-y-2"><span className="readout">EVIDENCE</span>{selected.analysis.evidence.map(e=><div key={e.id} className="flex gap-3 rounded-input border border-rule p-3"><Clock3 size={14} className="text-brass mt-0.5"/><div><div className="text-sm text-ink">{e.start.toFixed(3)}s — {e.end.toFixed(3)}s · {e.label}</div><p className="text-xs text-muted mt-1">{e.claim}</p></div></div>)}</div>}</div>}
      </section>
    </div>
    {error && <div className="rounded-input border border-rule2 p-3 text-sm text-warn">{error}</div>}
  </div>;
}
