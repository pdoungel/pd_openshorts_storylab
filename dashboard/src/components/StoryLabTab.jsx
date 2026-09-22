import React, { useEffect, useRef, useState } from 'react';
import {
  Film, Plus, Sparkles, Clock3, BookOpen, Lightbulb, CheckCircle2,
  FileText, Clapperboard, HelpCircle, X, ChevronRight, ChevronLeft,
  PlayCircle, Check, Circle, Upload, MessageSquareQuestion
} from 'lucide-react';
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

const steps = [
  ['sources', '1', 'Sources', 'Build the complete source story'],
  ['angle', '2', 'Question / Why', 'Choose what the film should answer'],
  ['build', '3', 'Build Story', 'Script + evidence + actual clips'],
  ['narration', '4', 'Narration', 'Prepare and approve the voiceover'],
  ['final', '5', 'Final Video', 'Assemble and render'],
];

const formatTime = (seconds) => {
  if (seconds == null || Number.isNaN(Number(seconds))) return '—';
  const total = Math.max(0, Math.round(Number(seconds)));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
};

export default function StoryLabTab({ uploadPostKey = '', uploadUserId = '', managed = false }) {
  const [projects, setProjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [workflowStep, setWorkflowStep] = useState('sources');
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
  const [sourceMessage, setSourceMessage] = useState('');
  const [analysisMessage, setAnalysisMessage] = useState('');
  const [voiceboxProfiles, setVoiceboxProfiles] = useState([]);
  const [voiceboxAvailable, setVoiceboxAvailable] = useState(false);
  const [voiceboxLoading, setVoiceboxLoading] = useState(false);
  const [voiceProfileId, setVoiceProfileId] = useState('');

  const replaceProject = (project) => {
    setSelected(project);
    setProjects(prev => prev.map(p => p.id === project.id ? project : p));
  };

  const openProject = (project) => {
    setSelected(project);
    setAngle(project.brief?.angle || 'story');
    setQuestion(project.brief?.question || '');
    setWorkflowStep(project.analysis ? (project.script?.length ? 'build' : 'angle') : 'sources');
  };

  const load = async () => {
    try {
      const data = await apiJson('/api/storylab/projects');
      setProjects(data.projects || []);
    } catch (e) {
      setError(e.message || 'Could not load Story Lab projects.');
    }
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (selected?.script?.length) loadVoicebox();
  }, [selected?.id, selected?.script?.length]);

  useEffect(() => {
    if (!selected) return;
    if (!selected.analysis) setWorkflowStep('sources');
  }, [selected?.id]);

  const create = async () => {
    if (!title.trim()) return;
    setCreating(true);
    setError('');
    try {
      const project = await apiJson('/api/storylab/projects', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          title: title.trim(),
          kind,
          brief: { angle: 'story', question: '' }
        })
      });
      setProjects(prev => [project, ...prev]);
      openProject(project);
      setWorkflowStep('sources');
      setTitle('');
      setQuestion('');
      setAngle('story');
    } catch (e) {
      setError(e.message || 'Could not create project.');
    } finally {
      setCreating(false);
    }
  };

  const analyzeSources = async () => {
    if (!selected) return;
    setLoading(true);
    setBusyLabel('Analyzing sources…');
    setError('');
    try {
      const project = await apiJson('/api/storylab/projects/' + selected.id + '/analyze', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ transcript: '' })
      });
      replaceProject(project);
      setAnalysisMessage('Complete source analysis is ready. Now choose the question or theory that should drive the documentary.');
      setWorkflowStep('angle');
    } catch (e) {
      setError(e.message || 'Source analysis failed.');
    } finally {
      setLoading(false);
      setBusyLabel('');
    }
  };

  const uploadSource = async () => {
    if (!selected || !upload) return;
    setLoading(true);
    setError('');
    try {
      const body = new FormData();
      body.append('file', upload);
      const project = await apiJson(
        '/api/storylab/projects/' + selected.id + '/sources/upload?transcribe=' + String(transcribe),
        { method: 'POST', body }
      );
      replaceProject(project);
      const source = project.sources?.[project.sources.length - 1];
      setSourceMessage(source
        ? `${source.ingestion_source === 'embedded_english_subtitles' ? 'English subtitles detected and used. ' : ''}${source.name} added.`
        : 'Source uploaded successfully.');
      setUpload(null);
    } catch (e) {
      setError(e.message || 'Could not upload source.');
      setSourceMessage('');
    } finally {
      setLoading(false);
    }
  };

  const addTextSource = async () => {
    if (!selected || !transcript.trim()) return;
    setLoading(true);
    setError('');
    try {
      const name = transcript.includes('-->') ? 'pasted-source.srt' : 'pasted-source.txt';
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/sources/text', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, text: transcript})
      }));
      setTranscript('');
      setSourceMessage('Text/transcript source added.');
    } catch (e) {
      setError(e.message || 'Could not add source text.');
    } finally {
      setLoading(false);
    }
  };

  const buildStory = async () => {
    if (!selected) return;
    if (!question.trim() && angle === 'story') {
      setError('Choose an angle or enter the central question before building the story.');
      return;
    }
    setLoading(true);
    setBusyLabel('Building story…');
    setError('');
    try {
      await apiJson('/api/storylab/projects/' + selected.id + '/brief', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ ...(selected.brief || {}), angle, question: question.trim() })
      });
      const project = await apiJson('/api/storylab/projects/' + selected.id + '/analyze', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ transcript: '' })
      });
      replaceProject(project);
      setWorkflowStep('build');
    } catch (e) {
      setError(e.message || 'Could not build the story.');
    } finally {
      setLoading(false);
      setBusyLabel('');
    }
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
    setLoading(true);
    setBusyLabel('Preparing narration…');
    setError('');
    try {
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/voiceover', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({profile_id: voiceProfileId})
      }));
      setWorkflowStep('final');
    } catch (e) {
      setError(e.message || 'Voiceover generation failed.');
    } finally {
      setLoading(false);
      setBusyLabel('');
    }
  };

  const approveSection = async (section, approved = true) => {
    if (!selected) return;
    setLoading(true);
    setError('');
    try {
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/review', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          target_type: 'script',
          target_id: section.id,
          status: approved ? 'approved' : 'changes_requested'
        })
      }));
    } catch (e) {
      setError(e.message || 'Could not update script approval.');
    } finally {
      setLoading(false);
    }
  };

  const selectScene = async (sceneId, checked) => {
    if (!selected) return;
    setLoading(true);
    setError('');
    try {
      const ids = (selected.scenes || [])
        .filter(scene => scene.selected !== false && scene.id !== sceneId)
        .map(scene => scene.id);
      if (checked) ids.push(sceneId);
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/scenes/select', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scene_ids: ids})
      }));
    } catch (e) {
      setError(e.message || 'Could not update clip selection.');
    } finally {
      setLoading(false);
    }
  };

  const extractScenes = async (sceneIds) => {
    if (!selected || !sceneIds?.length) return;
    setLoading(true);
    setError('');
    try {
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/scenes/extract', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scene_ids: sceneIds})
      }));
    } catch (e) {
      setError(e.message || 'Could not extract source clips.');
    } finally {
      setLoading(false);
    }
  };

  const render = async () => {
    if (!selected) return;
    setLoading(true);
    setBusyLabel('Rendering final video…');
    setError('');
    try {
      replaceProject(await apiJson('/api/storylab/projects/' + selected.id + '/render', {method: 'POST'}));
    } catch (e) {
      setError(e.message || 'Render failed.');
    } finally {
      setLoading(false);
      setBusyLabel('');
    }
  };

  const allScriptApproved = Boolean(selected?.script?.length && selected.script.every(section => section.approved));
  const selectedClips = (selected?.scenes || []).filter(scene => scene.selected !== false);
  const extractedClips = selectedClips.filter(scene => scene.extraction_status === 'extracted' && scene.output_file);

  const evidenceById = (ids = []) => {
    const lookup = Object.fromEntries((selected?.analysis?.evidence || []).map(item => [item.id, item]));
    return [...new Set(ids)].map(id => lookup[id]).filter(Boolean);
  };

  const scenesForSection = (section) => {
    const wanted = new Set(section.scene_ids || []);
    return (selected?.scenes || []).filter(scene => wanted.has(scene.id));
  };

  const allEvidence = selected?.analysis?.evidence || [];
  const story = selected?.analysis?.story;
  const insights = selected?.analysis?.insights || [];

  const goTo = (step) => {
    if (!selected) return;
    if (step === 'angle' && !selected.analysis) return;
    if (step === 'build' && !selected.script?.length) return;
    if (step === 'narration' && !selected.script?.length) return;
    if (step === 'final' && !allScriptApproved) return;
    setWorkflowStep(step);
  };

  const stepIndex = Math.max(0, steps.findIndex(item => item[0] === workflowStep));

  return (
    <div className="space-y-6 animate-fade">
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4">
        <div>
          <p className="eyebrow">09 · STORY LAB</p>
          <h1 className="font-display lowercase text-3xl sm:text-4xl text-ink">Story Lab</h1>
          <p className="text-sm text-muted mt-2 max-w-3xl">
            Analyze the source first. Choose the question second. Then build a documentary from
            evidence and real playable source clips — not visual placeholders.
          </p>
        </div>
        <button type="button" className="btn-ghost text-xs" onClick={() => setHelpOpen(true)}>
          <HelpCircle size={14}/> how this workflow works
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {steps.map(([id, number, label, sub], index) => {
          const active = workflowStep === id;
          const done = index < stepIndex;
          return (
            <button
              key={id}
              type="button"
              onClick={() => goTo(id)}
              className={`flex items-center gap-2 rounded-full border px-3 py-2 text-left transition-colors ${active ? 'border-brass bg-paper3 text-ink' : 'border-rule text-muted'}`}
            >
              <span className={`flex h-6 w-6 items-center justify-center rounded-full text-[10px] ${done ? 'bg-brass text-white' : active ? 'bg-ink text-paper' : 'bg-paper3'}`}>
                {done ? <Check size={12}/> : number}
              </span>
              <span>
                <span className="block text-xs">{label}</span>
                <span className="hidden md:block text-[9px] text-muted">{sub}</span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="grid lg:grid-cols-[260px_1fr] gap-4">
        <section className="card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="readout">PROJECTS</span>
            <button className="btn-ghost" onClick={() => {setSelected(null); setWorkflowStep('sources');}} title="new project">
              <Plus size={14}/>
            </button>
          </div>

          {projects.length === 0 ? (
            <p className="text-xs text-muted py-5">No Story Lab projects yet.</p>
          ) : projects.map(project => (
            <div key={project.id} className={`rounded-input border transition-colors ${selected?.id === project.id ? 'border-brass bg-paper3' : 'border-rule hover:bg-paper3/60'}`}>
              <button
                onClick={() => {
                  openProject(project);
                }}
                className="w-full text-left p-3"
              >
                <div className="text-sm text-ink truncate">{project.title}</div>
                <div className="text-[11px] text-muted mt-1">{project.kind} · {project.status}</div>
              </button>
            </div>
          ))}
        </section>

        <section className="card p-5 sm:p-6 min-w-0">
          {!selected ? (
            <div className="max-w-xl space-y-5">
              <div>
                <div className="flex items-center gap-2 text-brass">
                  <Sparkles size={16}/><span className="readout">NEW STORY</span>
                </div>
                <h2 className="font-display lowercase text-2xl text-ink mt-2">Start with the sources</h2>
                <p className="text-xs text-muted mt-2">
                  Do not choose the theory yet. Story Lab first builds the complete source story so
                  the later question is answered from what is actually present in the material.
                </p>
              </div>

              <div className="grid sm:grid-cols-[1fr_150px] gap-3">
                <input
                  className="input-field"
                  placeholder="Movie, series, anime or story title"
                  value={title}
                  onChange={e => setTitle(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && create()}
                />
                <select className="input-field" value={kind} onChange={e => setKind(e.target.value)}>
                  {kinds.map(k => <option key={k}>{k}</option>)}
                </select>
              </div>

              <button className="btn-primary" disabled={!title.trim() || creating} onClick={create}>
                <Plus size={14}/>{creating ? 'creating…' : 'create project'}
              </button>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
                <div>
                  <p className="readout">{selected.kind.toUpperCase()} · {selected.status.toUpperCase()}</p>
                  <h2 className="font-display lowercase text-2xl text-ink mt-1">{selected.title}</h2>
                </div>
                <div className="flex flex-wrap gap-2">
                  {workflowStep !== 'sources' && (
                    <button className="btn-ghost" onClick={() => goTo('sources')}><ChevronLeft size={14}/> sources</button>
                  )}
                </div>
              </div>

              {workflowStep === 'sources' && (
                <div className="space-y-6">
                  <div className="rounded-input border border-brass/40 bg-paper3 p-4">
                    <div className="flex items-start gap-3">
                      <div className="rounded-full bg-brass/10 p-2 text-brass"><BookOpen size={17}/></div>
                      <div>
                        <div className="readout text-brass">STEP 1 · COMPLETE SOURCE STORY</div>
                        <h3 className="text-lg text-ink mt-1">Upload everything before choosing the angle</h3>
                        <p className="text-xs text-muted mt-1">
                          Video/audio is transcribed when enabled. Timestamped source material becomes
                          evidence that can later resolve to real video clips.
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="grid md:grid-cols-2 gap-4">
                    <div className="rounded-input border border-rule p-4 space-y-3">
                      <div className="readout">VIDEO / AUDIO / DOCUMENT</div>
                      <input
                        ref={fileInputRef}
                        type="file"
                        className="hidden"
                        onChange={e => setUpload(e.target.files?.[0] || null)}
                      />
                      <button className="btn-ghost w-full justify-center" onClick={() => fileInputRef.current?.click()} disabled={loading}>
                        <Upload size={14}/>{upload ? upload.name : 'choose source file'}
                      </button>
                      <label className="flex items-center gap-2 text-xs text-muted">
                        <input type="checkbox" checked={transcribe} onChange={e => setTranscribe(e.target.checked)}/>
                        transcribe video/audio for timestamped evidence
                      </label>
                      <button className="btn-primary w-full justify-center" disabled={!upload || loading} onClick={uploadSource}>
                        upload source
                      </button>
                    </div>

                    <div className="rounded-input border border-rule p-4 space-y-3">
                      <div className="readout">TRANSCRIPT / TEXT SOURCE</div>
                      <textarea
                        className="input-field min-h-28 w-full resize-y"
                        placeholder="Paste transcript, SRT/VTT or source notes…"
                        value={transcript}
                        onChange={e => setTranscript(e.target.value)}
                      />
                      <button className="btn-ghost" disabled={!transcript.trim() || loading} onClick={addTextSource}>
                        <FileText size={14}/> add text source
                      </button>
                    </div>
                  </div>

                  {sourceMessage && (
                    <div className="rounded border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs text-ink2">
                      <CheckCircle2 size={14} className="inline mr-2 text-emerald-600"/>{sourceMessage}
                    </div>
                  )}

                  <div className="rounded-input border border-rule p-4">
                    <div className="flex items-center justify-between mb-3">
                      <span className="readout">ATTACHED SOURCES</span>
                      <span className="text-[11px] text-muted">{selected.sources?.length || 0} source(s)</span>
                    </div>
                    {selected.sources?.length ? (
                      <div className="space-y-2">
                        {selected.sources.map(source => (
                          <div key={source.id} className="flex items-center gap-3 rounded border border-rule p-3">
                            <FileText size={14} className="text-brass shrink-0"/>
                            <div className="min-w-0">
                              <div className="text-xs text-ink truncate">{source.name}</div>
                              <div className="text-[10px] text-muted">{source.kind} · {source.ingestion_source || 'source'}</div>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-muted">No sources attached yet.</p>
                    )}
                  </div>

                  <button
                    className="btn-primary w-full sm:w-auto"
                    disabled={!selected.sources?.length || loading}
                    onClick={analyzeSources}
                  >
                    <Sparkles size={14}/>{loading && busyLabel === 'Analyzing sources…' ? 'analyzing complete source story…' : 'analyze complete source story'}
                  </button>
                </div>
              )}

              {workflowStep === 'angle' && selected.analysis && (
                <div className="space-y-6">
                  <div className="rounded-input border border-brass/40 bg-paper3 p-4">
                    <div className="readout text-brass">STEP 2 · CHOOSE THE STORY QUESTION</div>
                    <h3 className="font-display lowercase text-2xl text-ink mt-1">What do you want this documentary to answer?</h3>
                    <p className="text-xs text-muted mt-2 max-w-3xl">
                      The complete source story has already been analyzed. Now choose the WHY, question,
                      theory or angle. Build Story will use the source material again to find the evidence
                      and clips that specifically answer it.
                    </p>
                  </div>

                  <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
                    {angles.map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setAngle(value)}
                        className={`rounded-input border p-4 text-left ${angle === value ? 'border-brass bg-paper3' : 'border-rule hover:bg-paper3/60'}`}
                      >
                        <div className="flex items-center gap-2">
                          {angle === value ? <CheckCircle2 size={15} className="text-brass"/> : <Circle size={15} className="text-muted"/>}
                          <span className="text-sm text-ink">{label}</span>
                        </div>
                      </button>
                    ))}
                  </div>

                  <div className="rounded-input border border-rule p-4">
                    <label className="readout flex items-center gap-2 mb-2"><MessageSquareQuestion size={14}/> CENTRAL QUESTION / THEORY / WHY</label>
                    <textarea
                      className="input-field w-full min-h-24 resize-y"
                      placeholder="Example: Is Satou actually an isekai? Why did this happen? What evidence supports this theory?"
                      value={question}
                      onChange={e => setQuestion(e.target.value)}
                    />
                  </div>

                  <div className="rounded-input border border-rule p-4">
                    <div className="readout">COMPLETE SOURCE STORY</div>
                    <p className="text-xs text-ink2 mt-2 leading-relaxed">{selected.analysis.summary || 'No summary was returned.'}</p>
                    <div className="grid sm:grid-cols-3 gap-2 mt-4">
                      <div className="rounded border border-rule p-3"><div className="readout">EVIDENCE</div><div className="text-xl text-ink mt-1">{allEvidence.length}</div></div>
                      <div className="rounded border border-rule p-3"><div className="readout">INSIGHTS</div><div className="text-xl text-ink mt-1">{insights.length}</div></div>
                      <div className="rounded border border-rule p-3"><div className="readout">THEORIES</div><div className="text-xl text-ink mt-1">{selected.analysis.theories?.length || 0}</div></div>
                    </div>
                    {selected.analysis.themes?.length > 0 && (
                      <div className="flex flex-wrap gap-2 mt-3">
                        {selected.analysis.themes.map(theme => <span key={theme} className="rounded-full border border-rule px-2 py-1 text-[10px] text-muted">{theme}</span>)}
                      </div>
                    )}

                    {selected.analysis.story && (
                      <details className="mt-4 rounded border border-rule p-3" open>
                        <summary className="cursor-pointer text-xs text-ink">View the complete source story</summary>
                        <div className="grid md:grid-cols-2 gap-4 mt-4">
                          {[
                            ['Hook', selected.analysis.story.hook],
                            ['Context', selected.analysis.story.context],
                            ['Conflict', selected.analysis.story.conflict],
                            ['Consequences', selected.analysis.story.consequences],
                            ['Significance', selected.analysis.story.significance],
                            ['Central question found in the source', selected.analysis.story.central_question],
                            ['Interpretation', selected.analysis.story.interpretation],
                          ].map(([label, value]) => (
                            <div key={label} className="rounded border border-rule p-3">
                              <div className="readout">{label}</div>
                              <p className="text-xs text-ink2 mt-2 leading-relaxed">{value || '—'}</p>
                            </div>
                          ))}
                        </div>

                        {selected.analysis.story.timeline?.length > 0 && (
                          <div className="mt-4">
                            <div className="readout">TIMELINE</div>
                            <div className="space-y-2 mt-2">
                              {selected.analysis.story.timeline.map((item, index) => (
                                <div key={index} className="rounded border border-rule p-2 text-xs text-ink2">
                                  {index + 1}. {item}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {selected.analysis.story.key_events?.length > 0 && (
                          <div className="mt-4">
                            <div className="readout">KEY EVENTS</div>
                            <div className="space-y-2 mt-2">
                              {selected.analysis.story.key_events.map((item, index) => (
                                <div key={index} className="rounded border border-rule p-2 text-xs text-ink2">
                                  {index + 1}. {item}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {selected.analysis.story.people?.length > 0 && (
                          <div className="mt-4">
                            <div className="readout">PEOPLE / RELATIONSHIPS</div>
                            <div className="flex flex-wrap gap-2 mt-2">
                              {selected.analysis.story.people.map((item, index) => (
                                <span key={index} className="rounded-full border border-rule px-2 py-1 text-[10px] text-muted">{item}</span>
                              ))}
                            </div>
                          </div>
                        )}

                        {selected.analysis.story.counterpoints?.length > 0 && (
                          <div className="mt-4">
                            <div className="readout">COUNTERPOINTS</div>
                            <div className="space-y-2 mt-2">
                              {selected.analysis.story.counterpoints.map((item, index) => (
                                <div key={index} className="rounded border border-rule p-2 text-xs text-ink2">
                                  {index + 1}. {item}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {selected.analysis.story.open_questions?.length > 0 && (
                          <div className="mt-4">
                            <div className="readout">OPEN QUESTIONS</div>
                            <div className="space-y-2 mt-2">
                              {selected.analysis.story.open_questions.map((item, index) => (
                                <div key={index} className="rounded border border-rule p-2 text-xs text-ink2">
                                  {index + 1}. {item}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </details>
                    )}
                  </div>

                  <div className="flex justify-end">
                    <button className="btn-primary" disabled={!question.trim() && angle === 'story' || loading} onClick={buildStory}>
                      <Sparkles size={14}/>{loading && busyLabel === 'Building story…' ? 'building story…' : 'build story'}
                    </button>
                  </div>
                </div>
              )}

              {workflowStep === 'build' && selected.script?.length > 0 && (
                <div className="space-y-6">
                  <div className="rounded-input border border-brass/40 bg-paper3 p-4">
                    <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3">
                      <div>
                        <div className="readout text-brass">STEP 3 · BUILD STORY</div>
                        <h3 className="font-display lowercase text-2xl text-ink mt-1">
                          {selected.brief?.question || selected.analysis?.story?.central_question || selected.title}
                        </h3>
                        <p className="text-xs text-muted mt-2">
                          Every section below keeps the narration, evidence and actual source footage together.
                          Select only the clips you want in the final documentary.
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2 text-[10px]">
                        <span className="rounded-full border border-rule px-2 py-1">{selected.script.length} sections</span>
                        <span className="rounded-full border border-rule px-2 py-1">{selectedClips.length} clips selected</span>
                        <span className="rounded-full border border-rule px-2 py-1">{extractedClips.length} clips ready</span>
                      </div>
                    </div>
                  </div>

                  {selected.script.map((section, index) => {
                    const evidence = evidenceById(section.evidence_ids || []);
                    const scenes = scenesForSection(section);
                    return (
                      <div key={section.id} className="rounded-input border border-rule overflow-hidden">
                        <div className="bg-paper3 p-4 border-b border-rule">
                          <div className="flex items-start gap-3">
                            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-ink text-paper text-[10px] shrink-0">
                              {String(index + 1).padStart(2, '0')}
                            </div>
                            <div className="min-w-0">
                              <div className="text-sm font-medium text-ink">{section.heading}</div>
                              <div className="text-[10px] text-muted mt-1">{section.duration_seconds || '—'}s narration · {evidence.length} evidence item(s) · {scenes.length} source clip(s)</div>
                            </div>
                          </div>
                        </div>

                        <div className="grid xl:grid-cols-2 gap-0">
                          <div className="p-4 border-b xl:border-b-0 xl:border-r border-rule space-y-4">
                            <div>
                              <div className="readout">NARRATION / STORY</div>
                              <p className="text-sm text-ink2 mt-2 leading-relaxed">{section.narration}</p>
                            </div>

                            <div>
                              <div className="readout">EVIDENCE</div>
                              {evidence.length ? (
                                <div className="space-y-2 mt-2">
                                  {evidence.map(item => (
                                    <div key={item.id} className="rounded border border-rule p-3">
                                      <div className="flex items-start justify-between gap-2">
                                        <div className="text-xs text-ink">{item.label || 'Source evidence'}</div>
                                        {item.start != null && <span className="text-[10px] text-brass">{formatTime(item.start)} — {formatTime(item.end)}</span>}
                                      </div>
                                      {item.claim && <p className="text-xs text-ink2 mt-1">{item.claim}</p>}
                                      {item.supporting_text && <p className="text-[10px] text-muted mt-1">{item.supporting_text}</p>}
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <p className="text-xs text-muted mt-2">No linked evidence was returned for this section.</p>
                              )}
                            </div>
                          </div>

                          <div className="p-4 space-y-3">
                            <div className="flex items-center justify-between gap-2">
                              <div>
                                <div className="readout">SOURCE VIDEO CLIPS</div>
                                <p className="text-[10px] text-muted mt-1">Playable footage found from the cited source timestamps.</p>
                              </div>
                              <span className="text-[10px] text-muted">{scenes.filter(s => s.selected !== false).length} selected</span>
                            </div>

                            {scenes.length ? (
                              <div className="space-y-3">
                                {scenes.map(scene => {
                                  const checked = scene.selected !== false;
                                  const ready = scene.extraction_status === 'extracted' && scene.output_file;
                                  return (
                                    <div key={scene.id} className={`rounded border overflow-hidden ${checked ? 'border-brass/60' : 'border-rule'}`}>
                                      {ready ? (
                                        <video
                                          className="w-full aspect-video object-contain bg-black"
                                          controls
                                          playsInline
                                          preload="metadata"
                                          src={'/api/storylab/projects/' + selected.id + '/scenes/' + scene.id + '/file'}
                                        />
                                      ) : (
                                        <div className="aspect-video bg-paper3 flex flex-col items-center justify-center text-center p-4">
                                          <PlayCircle size={28} className="text-muted"/>
                                          <p className="text-xs text-muted mt-2">Clip is not extracted yet.</p>
                                          {scene.extraction_error && <p className="text-[10px] text-warn mt-1">{scene.extraction_error}</p>}
                                          <button className="btn-ghost text-[10px] mt-2" onClick={() => extractScenes([scene.id])} disabled={loading}>
                                            extract clip
                                          </button>
                                        </div>
                                      )}

                                      <div className="bg-paper p-3">
                                        <label className="flex items-start gap-2 cursor-pointer">
                                          <input
                                            type="checkbox"
                                            className="mt-0.5"
                                            checked={checked}
                                            onChange={e => selectScene(scene.id, e.target.checked)}
                                          />
                                          <span className="min-w-0">
                                            <span className="block text-xs text-ink">{scene.title}</span>
                                            <span className="block text-[10px] text-muted mt-1">
                                              {formatTime(scene.start)} — {formatTime(scene.end)} · {Math.max(0, (scene.end || 0) - (scene.start || 0)).toFixed(1)}s
                                            </span>
                                          </span>
                                        </label>
                                        {scene.purpose && <p className="text-[10px] text-muted mt-2">{scene.purpose}</p>}
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            ) : (
                              <div className="rounded border border-dashed border-rule p-5 text-center">
                                <Film size={22} className="mx-auto text-muted"/>
                                <p className="text-xs text-muted mt-2">No timestamp-backed source clip was found for this section.</p>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}

                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 rounded-input border border-brass/40 bg-paper3 p-4">
                    <div>
                      <div className="readout text-brass">CLIP SELECTION</div>
                      <p className="text-xs text-muted mt-1">
                        {selectedClips.length} selected · {extractedClips.length} playable.
                        Uncheck anything you do not want used.
                      </p>
                    </div>
                    <button className="btn-primary" disabled={!selectedClips.length || loading} onClick={() => setWorkflowStep('narration')}>
                      continue to narration <ChevronRight size={14}/>
                    </button>
                  </div>
                </div>
              )}

              {workflowStep === 'narration' && selected.script?.length > 0 && (
                <div className="space-y-6">
                  <div className="rounded-input border border-brass/40 bg-paper3 p-4">
                    <div className="readout text-brass">STEP 4 · NARRATION</div>
                    <h3 className="font-display lowercase text-2xl text-ink mt-1">Prepare the voiceover from the selected story</h3>
                    <p className="text-xs text-muted mt-2">
                      The narration follows the question-driven script that was built from the source evidence.
                      Approve each section after checking the wording against the evidence and selected footage.
                    </p>
                  </div>

                  <div className="space-y-3">
                    {selected.script.map((section, index) => {
                      const approved = Boolean(section.approved);
                      const scenes = scenesForSection(section).filter(scene => scene.selected !== false);
                      return (
                        <div key={section.id} className="rounded-input border border-rule p-4">
                          <div className="flex flex-col lg:flex-row gap-4">
                            <div className="flex-1">
                              <div className="flex items-center gap-2">
                                <span className="text-[10px] text-muted">{String(index + 1).padStart(2, '0')}</span>
                                <span className="text-sm text-ink">{section.heading}</span>
                                {approved ? <CheckCircle2 size={14} className="text-emerald-600"/> : <Circle size={14} className="text-muted"/>}
                              </div>
                              <p className="text-sm text-ink2 leading-relaxed mt-2">{section.narration}</p>
                              <div className="flex flex-wrap gap-2 mt-3">
                                {scenes.map(scene => (
                                  <span key={scene.id} className="rounded-full border border-rule px-2 py-1 text-[10px] text-muted">
                                    {formatTime(scene.start)} · {scene.title}
                                  </span>
                                ))}
                              </div>
                            </div>
                            <div className="shrink-0">
                              <button
                                className={approved ? 'btn-ghost' : 'btn-primary'}
                                disabled={loading}
                                onClick={() => approveSection(section, !approved)}
                              >
                                {approved ? 'unapprove' : 'approve narration'}
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="rounded-input border border-rule p-4">
                    <div className="flex flex-col sm:flex-row sm:items-end gap-3">
                      <div className="flex-1">
                        <div className="readout">LOCAL VOICEBOX</div>
                        {voiceboxProfiles.length ? (
                          <select className="input-field w-full mt-2" value={voiceProfileId} onChange={e => setVoiceProfileId(e.target.value)}>
                            {voiceboxProfiles.map(profile => (
                              <option key={profile.id} value={profile.id}>{profile.name} · {profile.language || 'en'}</option>
                            ))}
                          </select>
                        ) : (
                          <div className="text-xs text-muted border border-dashed border-rule rounded p-3 mt-2">
                            {voiceboxLoading ? 'Checking Voicebox…' : voiceboxAvailable ? 'No Voicebox profiles found.' : 'Voicebox is not connected.'}
                          </div>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <button className="btn-ghost text-[11px]" disabled={voiceboxLoading || loading} onClick={loadVoicebox}>refresh</button>
                        <button
                          className="btn-primary"
                          disabled={!allScriptApproved || !voiceboxAvailable || !voiceProfileId || loading}
                          onClick={generateVoiceover}
                        >
                          prepare narration & voiceover
                        </button>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2 mt-3">
                      <a className="btn-ghost text-[11px]" href={'/api/storylab/projects/' + selected.id + '/download/narration'} download>
                        <FileText size={13}/> narration script
                      </a>
                      <a className="btn-ghost text-[11px]" href={'/api/storylab/projects/' + selected.id + '/download/narration-srt'} download>
                        <Clock3 size={13}/> timing SRT
                      </a>
                    </div>
                  </div>
                </div>
              )}

              {workflowStep === 'final' && (
                <div className="space-y-6">
                  <div className="rounded-input border border-brass/40 bg-paper3 p-4">
                    <div className="readout text-brass">STEP 5 · FINAL VIDEO</div>
                    <h3 className="font-display lowercase text-2xl text-ink mt-1">Assemble the selected clips with narration</h3>
                    <p className="text-xs text-muted mt-2">
                      The final render uses the approved script, selected source scenes and generated narration.
                    </p>
                  </div>

                  <div className="grid sm:grid-cols-3 gap-3">
                    <div className="rounded border border-rule p-4"><div className="readout">SCRIPT</div><div className="text-xl text-ink mt-1">{selected.script?.length || 0}</div><div className="text-[10px] text-muted">sections</div></div>
                    <div className="rounded border border-rule p-4"><div className="readout">SELECTED CLIPS</div><div className="text-xl text-ink mt-1">{selectedClips.length}</div><div className="text-[10px] text-muted">{extractedClips.length} playable</div></div>
                    <div className="rounded border border-rule p-4"><div className="readout">VOICEOVER</div><div className="text-xl text-ink mt-1">{selected.voiceover?.status === 'generated' ? 'READY' : '—'}</div><div className="text-[10px] text-muted">{allScriptApproved ? 'script approved' : 'approval required'}</div></div>
                  </div>

                  <div className="rounded-input border border-rule p-4">
                    <div className="readout">SELECTED VISUAL TIMELINE</div>
                    <div className="grid sm:grid-cols-2 gap-3 mt-3">
                      {extractedClips.map((scene, index) => (
                        <div key={scene.id} className="rounded border border-rule overflow-hidden bg-black">
                          <video
                            className="w-full aspect-video object-contain"
                            controls
                            playsInline
                            preload="metadata"
                            src={'/api/storylab/projects/' + selected.id + '/scenes/' + scene.id + '/file'}
                          />
                          <div className="bg-paper p-2">
                            <div className="text-[11px] text-ink">{index + 1}. {scene.title}</div>
                            <div className="text-[10px] text-muted">{formatTime(scene.start)} — {formatTime(scene.end)}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div>
                      <p className="text-xs text-muted">
                        {selected.voiceover?.status === 'generated'
                          ? 'Narration is ready. Create the final documentary when the selected footage is correct.'
                          : 'Generate narration first before rendering the final documentary.'}
                      </p>
                    </div>
                    <button
                      className="btn-primary"
                      disabled={!allScriptApproved || selected.voiceover?.status !== 'generated' || !extractedClips.length || loading}
                      onClick={render}
                    >
                      <Clapperboard size={14}/>{loading && busyLabel === 'Rendering final video…' ? 'rendering…' : 'create final video'}
                    </button>
                  </div>

                  {selected.renders?.length > 0 && (
                    <div className="rounded-input border border-rule p-4">
                      <div className="readout">FINAL OUTPUT</div>
                      <p className="text-xs text-muted mt-1">
                        Latest render: {selected.renders[selected.renders.length - 1].status}
                      </p>
                      {selected.renders[selected.renders.length - 1].status === 'rendered' && (
                        <div className="mt-3 space-y-3">
                          <video
                            className="w-full max-h-[520px] rounded bg-black"
                            controls
                            preload="metadata"
                            src={'/api/storylab/projects/' + selected.id + '/download/render'}
                          />
                          <a className="btn-primary inline-flex" href={'/api/storylab/projects/' + selected.id + '/download/render'} download>
                            <FileText size={14}/> download final video
                          </a>
                        </div>
                      )}
                      {selected.renders[selected.renders.length - 1].error && (
                        <p className="text-xs text-warn mt-2">{selected.renders[selected.renders.length - 1].error}</p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {analysisMessage && workflowStep === 'angle' && (
                <div className="rounded border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs text-ink2">
                  <CheckCircle2 size={14} className="inline mr-2 text-emerald-600"/>{analysisMessage}
                </div>
              )}
            </div>
          )}
        </section>
      </div>

      {loading && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/25 p-4">
          <div className="card max-w-md w-full p-6 text-center shadow-xl">
            <div className="mx-auto mb-4 h-10 w-10 rounded-full border-2 border-brass border-t-transparent animate-spin"></div>
            <div className="readout text-brass">{busyLabel || 'WORKING'}</div>
            <p className="text-sm text-ink mt-2">
              {busyLabel === 'Analyzing sources…'
                ? 'Reading the supplied sources and building the complete source story.'
                : busyLabel === 'Building story…'
                  ? 'Applying the selected question/theory to the source evidence and finding the necessary timestamped clips.'
                  : busyLabel === 'Rendering final video…'
                    ? 'Assembling the selected source footage and narration.'
                    : 'Story Lab is processing your request.'}
            </p>
          </div>
        </div>
      )}

      {helpOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={() => setHelpOpen(false)}>
          <div className="card max-w-2xl w-full max-h-[85vh] overflow-y-auto p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div>
                <div className="readout text-brass">HOW STORY LAB WORKS</div>
                <h3 className="font-display lowercase text-2xl text-ink mt-1">Source → question → evidence → footage → narration → video</h3>
              </div>
              <button className="btn-ghost" onClick={() => setHelpOpen(false)}><X size={16}/></button>
            </div>
            <div className="mt-5 space-y-4 text-sm text-ink2">
              <div><strong>1. Source analysis.</strong><p className="text-xs text-muted mt-1">Upload the complete source material and analyze it before choosing an editorial theory. This creates the underlying story, evidence, insights and timestamped source record.</p></div>
              <div><strong>2. Choose the question.</strong><p className="text-xs text-muted mt-1">Select Why, Theory, Character, Ending, Documentary or another angle, then enter the actual question you want the video to answer.</p></div>
              <div><strong>3. Build Story.</strong><p className="text-xs text-muted mt-1">Each generated section puts narration, evidence and source clips together. Clips are real extracted MP4 segments from the uploaded source whenever timestamped evidence exists.</p></div>
              <div><strong>4. Narration.</strong><p className="text-xs text-muted mt-1">Review and approve the narration section by section, then generate the local Voicebox narration.</p></div>
              <div><strong>5. Final Video.</strong><p className="text-xs text-muted mt-1">Only the clips you selected are passed into the final assembly. The final MP4 is previewable and downloadable here.</p></div>
            </div>
          </div>
        </div>
      )}

      {error && <div className="rounded-input border border-rule2 p-3 text-sm text-warn">{error}</div>}
    </div>
  );
}
