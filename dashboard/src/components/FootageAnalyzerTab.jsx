import React, { useMemo, useRef, useState } from 'react';
import { FolderOpen, Mic2, Film, Sparkles, Play, CheckCircle2, AlertTriangle, ChevronDown, Search, Download, Loader2 } from 'lucide-react';

const ANALYZER_URL = import.meta.env.VITE_FOOTAGE_ANALYZER_URL || 'http://localhost:8010';

const formatTime = (seconds) => {
  const s = Math.max(0, Number(seconds) || 0);
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return \`\${String(m).padStart(2, '0')}:\${sec.toFixed(1).padStart(4, '0')}\`;
};

const demoTimeline = [
  { timeline_start: 0, timeline_end: 4.2, match_type: 'direct', score: .91, source_path: 'footage_017.mp4', source_start: 18.4, source_end: 22.6, description: 'Soldiers walking along a road', reason: 'strong subject + action match' },
  { timeline_start: 4.2, timeline_end: 9.0, match_type: 'related', score: .78, source_path: 'footage_042.mp4', source_start: 192, source_end: 196.8, description: 'People moving along a hill trail', reason: 'related movement + mountainous environment' },
  { timeline_start: 9.0, timeline_end: 12.0, match_type: 'contextual_fallback', score: .68, source_path: 'footage_008.mp4', source_start: 112.2, source_end: 115.2, description: 'Mountain path / rugged landscape', reason: 'contextual fallback; no closer shot available' },
];

const typeLabel = { direct: 'direct', related: 'related', contextual_fallback: 'contextual fallback' };

export default function FootageAnalyzerTab() {
  const [voiceover, setVoiceover] = useState(null);
  const [footage, setFootage] = useState([]);
  const [footageRoot, setFootageRoot] = useState('');
  const [instruction, setInstruction] = useState('');
  const [job, setJob] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [error, setError] = useState('');
  const pollRef = useRef(null);

  const footageCount = footage.length;
  const totalSize = useMemo(() => footage.reduce((n, f) => n + (f.size || 0), 0), [footage]);

  const stopPolling = () => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = null;
  };

  const pollJob = (id) => {
    stopPolling();
    const tick = async () => {
      try {
        const res = await fetch(\`\${ANALYZER_URL}/api/footage-analyzer/jobs/\${id}\`);
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        setJob(data);
        if (data.status === 'complete') {
          const edl = data.result?.clips || [];
          setTimeline(edl);
          stopPolling();
        } else if (data.status === 'failed') {
          setError(data.error?.message || data.message || 'Analysis failed');
          stopPolling();
        }
      } catch (e) {
        setError(e.message || 'Could not reach Footage Analyzer');
        stopPolling();
      }
    };
    tick();
    pollRef.current = window.setInterval(tick, 1500);
  };

  const startAnalysis = async () => {
    if (!voiceover || !footageRoot.trim()) {
      setError('Select a voiceover and enter the footage folder path as seen by Docker.');
      return;
    }
    setError('');
    setTimeline([]);
    setJob({ status: 'queued', stage: 'queued', progress: 0, message: 'Starting…' });
    try {
      const form = new FormData();
      form.append('voiceover', voiceover);
      form.append('footage_root', footageRoot.trim());
      form.append('instruction', instruction);
      const res = await fetch(\`\${ANALYZER_URL}/api/footage-analyzer/jobs\`, { method: 'POST', body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || 'Could not start analysis');
      setJob(data);
      pollJob(data.id);
    } catch (e) {
      setError(e.message || 'Could not start analysis');
      setJob(null);
    }
  };

  const loadDemo = () => {
    stopPolling();
    setError('');
    setTimeline(demoTimeline);
    setJob({ status: 'complete', stage: 'complete', progress: 100, message: 'Demo preview' });
  };

  return (
    <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
      <div className="max-w-7xl mx-auto p-4 sm:p-6 md:p-8 space-y-6">
        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-5">
          <div>
            <p className="eyebrow flex items-center gap-2"><Film size={12} /> 09 · FOOTAGE ANALYZER</p>
            <h1 className="font-display lowercase text-3xl md:text-4xl text-ink mt-2">Build the visuals around your voiceover</h1>
            <p className="text-muted mt-2 max-w-3xl leading-relaxed">
              An independent analyzer service uses your voiceover as the master timeline, understands your footage, and builds a duration-accurate visual EDL.
            </p>
          </div>
          <button onClick={loadDemo} className="btn-quiet shrink-0"><Sparkles size={14} /> preview matching</button>
        </div>

        <div className="grid lg:grid-cols-[0.85fr_1.15fr] gap-5">
          <section className="card p-5 space-y-5">
            <div>
              <p className="eyebrow mb-2">SOURCE MATERIAL</p>
              <h2 className="font-display lowercase text-xl text-ink">Give the analyzer your timeline</h2>
            </div>

            <label className="block">
              <span className="readout block mb-2">voiceover · wav / mp3 / m4a</span>
              <input type="file" accept="audio/*" className="input-field" onChange={e => setVoiceover(e.target.files?.[0] || null)} />
            </label>

            <label className="block">
              <span className="readout block mb-2">footage folder path · inside Docker</span>
              <input
                className="input-field"
                placeholder="/Users/yourname/Movies/Footage or /Volumes/Drive/Footage"
                value={footageRoot}
                onChange={e => setFootageRoot(e.target.value)}
              />
              <p className="text-[11px] text-muted mt-1.5">Use the Mac path. Docker maps /Users and /Volumes read-only into the analyzer.</p>
            </label>

            <label className="block">
              <span className="readout block mb-2">optional browser folder preview</span>
              <input type="file" multiple webkitdirectory="" directory="" accept="video/*" className="input-field" onChange={e => setFootage(Array.from(e.target.files || []))} />
            </label>

            <div className="rounded-input border border-rule bg-paper p-3 flex items-start gap-3">
              <FolderOpen size={17} className="text-brass mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm text-ink2">{footageCount ? \`\${footageCount} browser files selected\` : footageRoot ? 'Server-side folder configured' : 'No footage folder configured'}</p>
                <p className="text-xs text-muted mt-1">{footageCount ? \`\${(totalSize / 1024 / 1024 / 1024).toFixed(2)} GB selected\` : 'The analyzer reads the folder directly; large libraries are not uploaded through the browser.'}</p>
              </div>
            </div>

            <label className="block">
              <span className="readout block mb-2">optional editorial direction</span>
              <textarea className="input-field min-h-[92px] resize-y" placeholder="e.g. Prefer archival-looking footage and wide establishing shots when exact subjects are unavailable." value={instruction} onChange={e => setInstruction(e.target.value)} />
            </label>

            <div className="flex items-center gap-3">
              <button className="btn-primary flex-1" disabled={!voiceover || !footageRoot.trim() || job?.status === 'processing'} onClick={startAnalysis}>
                {job?.status === 'processing' ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                {job?.status === 'processing' ? ' analyzing…' : ' analyze footage'}
              </button>
              {job?.status === 'complete' && <span className="badge-ok"><CheckCircle2 size={12} /> complete</span>}
              {job?.status === 'queued' && <span className="badge-brass">queued</span>}
            </div>

            {job && job.status !== 'complete' && job.status !== 'failed' && (
              <div className="border border-rule rounded-input p-3">
                <div className="flex justify-between text-xs mb-2"><span className="text-muted">{job.message}</span><span className="readout">{job.progress || 0}%</span></div>
                <div className="h-1.5 bg-paper rounded-full overflow-hidden"><div className="h-full bg-accent transition-all" style={{width: \`\${job.progress || 0}%\`}} /></div>
                <p className="readout mt-2">{job.stage || 'queued'}</p>
              </div>
            )}

            {error && <div className="border border-rule rounded-input p-3 text-xs text-muted"><AlertTriangle size={14} className="inline mr-2 text-brass" />{error}</div>}

            <div className="border-t border-rule pt-4 grid grid-cols-3 gap-3 text-center">
              <div><Mic2 size={15} className="mx-auto text-brass mb-1" /><p className="readout">voiceover</p><p className="text-sm text-ink2 mt-1">{voiceover ? 'ready' : 'missing'}</p></div>
              <div><Film size={15} className="mx-auto text-brass mb-1" /><p className="readout">footage</p><p className="text-sm text-ink2 mt-1">{footageRoot ? 'mounted' : 'missing'}</p></div>
              <div><Search size={15} className="mx-auto text-brass mb-1" /><p className="readout">matching</p><p className="text-sm text-ink2 mt-1">semantic</p></div>
            </div>
          </section>

          <section className="card p-5 min-h-[560px]">
            <div className="flex items-start justify-between gap-4 mb-5">
              <div>
                <p className="eyebrow mb-2">VISUAL TIMELINE</p>
                <h2 className="font-display lowercase text-xl text-ink">Voiceover → usable footage</h2>
              </div>
              {job?.status === 'complete' && <a className="btn-quiet" href={\`\${ANALYZER_URL}/api/footage-analyzer/jobs/\${job.id}/edl/download\`}><Download size={13} /> EDL</a>}
            </div>

            {!timeline.length ? (
              <div className="h-[440px] flex flex-col items-center justify-center text-center border border-dashed border-rule2 rounded-card px-6">
                <Film size={28} className="text-muted mb-4" />
                <p className="text-ink2 text-sm">Your visual sequence will appear here.</p>
                <p className="text-xs text-muted max-w-md mt-2 leading-relaxed">Exact wording is not required. The planner turns narration into visual intent, then the matcher can use direct, related, or contextual footage and chain shots to cover the narration.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {timeline.map((clip, i) => (
                  <div key={i} className="border border-rule rounded-input bg-paper overflow-hidden">
                    <button className="w-full text-left p-3.5 flex items-center gap-3" onClick={() => setExpanded(expanded === i ? null : i)}>
                      <div className="w-16 shrink-0"><p className="readout">{formatTime(clip.timeline_start ?? clip.start)}</p><p className="text-[10px] text-muted">→ {formatTime(clip.timeline_end ?? clip.end)}</p></div>
                      <div className="w-2 h-10 rounded-full bg-accent shrink-0 opacity-80" />
                      <div className="min-w-0 flex-1"><p className="text-sm text-ink2 truncate">{clip.description || clip.visual_query || 'Visual match'}</p><p className="text-xs text-muted mt-1 truncate">{clip.source_path} · {formatTime(clip.source_start)}–{formatTime(clip.source_end)}</p></div>
                      <span className={clip.match_type === 'direct' ? 'badge-ok' : clip.match_type === 'related' ? 'badge-brass' : 'badge-warn'}>{typeLabel[clip.match_type] || clip.match_type}</span>
                      <span className="readout hidden sm:block">{Math.round((clip.score || 0) * 100)}%</span>
                      <ChevronDown size={14} className={\`text-muted transition-transform \${expanded === i ? 'rotate-180' : ''}\`} />
                    </button>
                    {expanded === i && <div className="px-3.5 pb-3.5 pt-0 border-t border-rule grid sm:grid-cols-2 gap-3 text-xs"><div><p className="readout mb-1">why selected</p><p className="text-muted leading-relaxed">{clip.reason || 'Evidence-based visual match.'}</p></div><div><p className="readout mb-1">narration</p><p className="text-muted leading-relaxed">{clip.narration || '—'}</p></div></div>}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        <section className="card p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle size={17} className="text-brass mt-0.5 shrink-0" />
            <div>
              <p className="text-sm text-ink2">Independent analyzer service.</p>
              <p className="text-xs text-muted mt-1 leading-relaxed">
                The analyzer has its own API, job store, transcription, scene detection, visual analysis, planner, embeddings, matcher, and EDL pipeline. It does not depend on Story Lab state. Raw footage stays local; only sampled frames are sent to Gemini.
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
