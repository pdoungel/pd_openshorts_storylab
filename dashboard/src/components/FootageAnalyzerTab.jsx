import React, { useMemo, useState } from 'react';
import { FolderOpen, Mic2, Film, Sparkles, Play, Clock3, CheckCircle2, AlertTriangle, ChevronDown, Search } from 'lucide-react';

const formatTime = (seconds = 0) => {
  const s = Math.max(0, Number(seconds) || 0);
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return `${String(m).padStart(2, '0')}:${sec.toFixed(1).padStart(4, '0')}`;
};

const demoTimeline = [
  { start: 0, end: 4.2, type: 'direct', score: .91, file: 'footage_017.mp4', source: '00:18.4–00:22.6', visual: 'Soldiers walking along a road', reason: 'strong subject + action match' },
  { start: 4.2, end: 9.0, type: 'related', score: .78, file: 'footage_042.mp4', source: '03:12.0–03:16.8', visual: 'People moving along a hill trail', reason: 'related movement + mountainous environment' },
  { start: 9.0, end: 12.0, type: 'contextual_fallback', score: .68, file: 'footage_008.mp4', source: '01:52.2–01:55.2', visual: 'Mountain path / rugged landscape', reason: 'contextual fallback; no closer shot available' },
];

const typeLabel = { direct: 'direct', related: 'related', contextual_fallback: 'contextual fallback' };

export default function FootageAnalyzerTab() {
  const [voiceover, setVoiceover] = useState(null);
  const [footage, setFootage] = useState([]);
  const [instruction, setInstruction] = useState('');
  const [status, setStatus] = useState('idle');
  const [timeline, setTimeline] = useState([]);
  const [expanded, setExpanded] = useState(null);

  const footageCount = footage.length;
  const totalSize = useMemo(() => footage.reduce((n, f) => n + (f.size || 0), 0), [footage]);

  const startAnalysis = () => {
    if (!voiceover || !footage.length) return;
    setStatus('ready');
    setTimeline([]);
  };

  const loadDemo = () => {
    setTimeline(demoTimeline);
    setStatus('complete');
  };

  return (
    <div className="h-full overflow-y-auto custom-scrollbar animate-fade">
      <div className="max-w-7xl mx-auto p-4 sm:p-6 md:p-8 space-y-6">
        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-5">
          <div>
            <p className="eyebrow flex items-center gap-2"><Film size={12} /> 09 · FOOTAGE ANALYZER</p>
            <h1 className="font-display lowercase text-3xl md:text-4xl text-ink mt-2">Build the visuals around your voiceover</h1>
            <p className="text-muted mt-2 max-w-3xl leading-relaxed">
              Your voiceover is the master timeline. The analyzer searches your footage for the closest usable visual—even when the exact scene does not exist—and chains clips when needed.
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
              <span className="readout block mb-2">footage library · select a folder</span>
              <input
                type="file"
                multiple
                webkitdirectory=""
                directory=""
                accept="video/*"
                className="input-field"
                onChange={e => setFootage(Array.from(e.target.files || []))}
              />
            </label>

            <div className="rounded-input border border-rule bg-paper p-3 flex items-start gap-3">
              <FolderOpen size={17} className="text-brass mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm text-ink2">{footageCount ? `${footageCount} footage files selected` : 'No footage selected yet'}</p>
                <p className="text-xs text-muted mt-1">{footageCount ? `${(totalSize / 1024 / 1024 / 1024).toFixed(2)} GB selected` : 'The browser will keep the folder structure while selecting files.'}</p>
              </div>
            </div>

            <label className="block">
              <span className="readout block mb-2">optional editorial direction</span>
              <textarea
                className="input-field min-h-[92px] resize-y"
                placeholder="e.g. Prefer archival-looking footage and wide establishing shots when exact subjects are unavailable."
                value={instruction}
                onChange={e => setInstruction(e.target.value)}
              />
            </label>

            <div className="flex items-center gap-3">
              <button className="btn-primary flex-1" disabled={!voiceover || !footage.length} onClick={startAnalysis}>
                <Play size={14} /> analyze footage
              </button>
              {status === 'ready' && <span className="badge-brass">queued</span>}
            </div>

            <div className="border-t border-rule pt-4 grid grid-cols-3 gap-3 text-center">
              <div><Mic2 size={15} className="mx-auto text-brass mb-1" /><p className="readout">voiceover</p><p className="text-sm text-ink2 mt-1">{voiceover ? 'ready' : 'missing'}</p></div>
              <div><Film size={15} className="mx-auto text-brass mb-1" /><p className="readout">footage</p><p className="text-sm text-ink2 mt-1">{footageCount}</p></div>
              <div><Search size={15} className="mx-auto text-brass mb-1" /><p className="readout">matching</p><p className="text-sm text-ink2 mt-1">semantic</p></div>
            </div>
          </section>

          <section className="card p-5 min-h-[560px]">
            <div className="flex items-start justify-between gap-4 mb-5">
              <div>
                <p className="eyebrow mb-2">VISUAL TIMELINE</p>
                <h2 className="font-display lowercase text-xl text-ink">Voiceover → usable footage</h2>
              </div>
              {status === 'complete' && <span className="badge-ok"><CheckCircle2 size={12} /> timeline covered</span>}
            </div>

            {!timeline.length ? (
              <div className="h-[440px] flex flex-col items-center justify-center text-center border border-dashed border-rule2 rounded-card px-6">
                <Film size={28} className="text-muted mb-4" />
                <p className="text-ink2 text-sm">Your visual sequence will appear here.</p>
                <p className="text-xs text-muted max-w-md mt-2 leading-relaxed">
                  Example: “British colonial soldiers moving through mountainous terrain” can become soldiers walking, related movement through hills, and finally a landscape fallback.
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {timeline.map((clip, i) => (
                  <div key={i} className="border border-rule rounded-input bg-paper overflow-hidden">
                    <button className="w-full text-left p-3.5 flex items-center gap-3" onClick={() => setExpanded(expanded === i ? null : i)}>
                      <div className="w-16 shrink-0"><p className="readout">{formatTime(clip.start)}</p><p className="text-[10px] text-muted">→ {formatTime(clip.end)}</p></div>
                      <div className="w-2 h-10 rounded-full bg-accent shrink-0 opacity-80" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-ink2 truncate">{clip.visual}</p>
                        <p className="text-xs text-muted mt-1 truncate">{clip.file} · {clip.source}</p>
                      </div>
                      <span className={clip.type === 'direct' ? 'badge-ok' : clip.type === 'related' ? 'badge-brass' : 'badge-warn'}>{typeLabel[clip.type]}</span>
                      <span className="readout hidden sm:block">{Math.round(clip.score * 100)}%</span>
                      <ChevronDown size={14} className={`text-muted transition-transform ${expanded === i ? 'rotate-180' : ''}`} />
                    </button>
                    {expanded === i && (
                      <div className="px-3.5 pb-3.5 pt-0 border-t border-rule grid sm:grid-cols-2 gap-3 text-xs">
                        <div><p className="readout mb-1">why selected</p><p className="text-muted leading-relaxed">{clip.reason}</p></div>
                        <div><p className="readout mb-1">source range</p><p className="text-ink2 font-mono">{clip.file} · {clip.source}</p></div>
                      </div>
                    )}
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
              <p className="text-sm text-ink2">Matching is evidence-based.</p>
              <p className="text-xs text-muted mt-1 leading-relaxed">
                The analyzer does not require an exact shot. It progressively relaxes subject, action, environment, and context requirements and records whether each selection is direct, related, or contextual fallback. Raw footage stays local; only sampled frames are sent to the configured vision model.
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
