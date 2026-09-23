import React, { useEffect, useMemo, useRef, useState } from 'react';
import { FolderOpen, Mic2, Film, Sparkles, Play, CheckCircle2, AlertTriangle, ChevronDown, Search, Download, Loader2, Trash2, RefreshCw, HardDrive } from 'lucide-react';

const ANALYZER_URL = import.meta.env.VITE_FOOTAGE_ANALYZER_URL || 'http://localhost:8010';

const formatTime = (seconds) => {
  const s = Math.max(0, Number(seconds) || 0);
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return `${String(m).padStart(2, '0')}:${sec.toFixed(1).padStart(4, '0')}`;
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
  const [footageFolderName, setFootageFolderName] = useState('');
  const [resolvingFolder, setResolvingFolder] = useState(false);
  const [folderResolutionError, setFolderResolutionError] = useState('');
  const [instruction, setInstruction] = useState('');
  const [job, setJob] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [error, setError] = useState('');
  const [indexInfo, setIndexInfo] = useState(null);
  const [indexBusy, setIndexBusy] = useState(false);
  const pollRef = useRef(null);
  const pollAbortRef = useRef(null);
  const mountedRef = useRef(true);
  const pollingRef = useRef(false);

  const footageCount = footage.length;
  const totalSize = useMemo(() => footage.reduce((n, f) => n + (f.size || 0), 0), [footage]);

  useEffect(() => () => {
    mountedRef.current = false;
    if (pollRef.current) window.clearTimeout(pollRef.current);
    if (pollAbortRef.current) pollAbortRef.current.abort();
  }, []);

  const refreshIndex = async (root = footageRoot) => {
    if (!root) return;
    try {
      const res = await fetch(`${ANALYZER_URL}/api/footage-analyzer/index?root=${encodeURIComponent(root)}`, { cache: 'no-store' });
      if (res.ok && mountedRef.current) setIndexInfo(await res.json());
    } catch (_) {}
  };

  useEffect(() => { if (footageRoot) refreshIndex(footageRoot); }, [footageRoot]);

  const stopPolling = () => {
    if (pollRef.current) window.clearTimeout(pollRef.current);
    pollRef.current = null;
    if (pollAbortRef.current) pollAbortRef.current.abort();
    pollAbortRef.current = null;
    pollingRef.current = false;
  };

  const pollJob = (id) => {
    stopPolling();
    const tick = async () => {
      if (!mountedRef.current || pollingRef.current) return;
      pollingRef.current = true;
      const controller = new AbortController();
      let terminal = false;
      pollAbortRef.current = controller;
      try {
        const res = await fetch(`${ANALYZER_URL}/api/footage-analyzer/jobs/${id}`, { signal: controller.signal, cache: 'no-store' });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        if (!mountedRef.current) return;
        setJob(data);
        if (data.index_stats) setIndexInfo(data.index_stats);
        if (data.status === 'complete') {
          terminal = true;
          setTimeline(data.result?.clips || []);
          stopPolling();
          refreshIndex(data.footage_root || footageRoot);
        } else if (data.status === 'failed') {
          terminal = true;
          setError(data.error?.message || data.message || 'Analysis failed');
          stopPolling();
        }
      } catch (e) {
        if (e?.name !== 'AbortError' && mountedRef.current) setError(e.message || 'Could not reach Footage Analyzer');
      } finally {
        pollingRef.current = false;
        if (pollAbortRef.current === controller) pollAbortRef.current = null;
        if (mountedRef.current && !terminal && !pollRef.current && !pollingRef.current) {
          pollRef.current = window.setTimeout(() => { pollRef.current = null; tick(); }, 1500);
        }
      }
    };
    tick();
  };

  const startAnalysis = async () => {
    if (!voiceover || !footageRoot.trim()) {
      setError('Select a voiceover and choose a footage folder that can be located by the analyzer.');
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
      // Use XMLHttpRequest for the multipart upload. Some desktop/webview
      // clients can close a fetch request while a File-backed FormData body is
      // being sent; XHR keeps the upload request alive until the response arrives.
      const data = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', `${ANALYZER_URL}/api/footage-analyzer/jobs`, true);
        xhr.responseType = 'text';
        xhr.onload = () => {
          let body = {};
          try { body = xhr.responseText ? JSON.parse(xhr.responseText) : {}; } catch {}
          if (xhr.status >= 200 && xhr.status < 300) resolve(body);
          else reject(new Error(body.detail || body.message || `Could not start analysis (HTTP ${xhr.status})`));
        };
        xhr.onerror = () => reject(new Error('Could not connect to Footage Analyzer. Check that the analyzer service is running.'));
        xhr.onabort = () => reject(new Error('The upload request was aborted before Footage Analyzer received it.'));
        xhr.ontimeout = () => reject(new Error('Timed out while starting Footage Analyzer.'));
        xhr.timeout = 120000;
        xhr.send(form);
      });
      if (!data?.id) throw new Error(data?.detail || 'Footage Analyzer did not return a job ID');
      setJob(data);
      pollJob(data.id);
    } catch (e) {
      setError(e.message || 'Could not start analysis');
      setJob(null);
    }
  };

  const clearIndex = async () => {
    if (!footageRoot) return;
    if (!window.confirm('Clear Footage Analyzer index and cached visual analysis for this folder? Original video files will NOT be deleted.')) return;
    setIndexBusy(true); setError('');
    try {
      const res = await fetch(`${ANALYZER_URL}/api/footage-analyzer/index?root=${encodeURIComponent(footageRoot)}`, { method: 'DELETE' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || 'Could not clear the index');
      setIndexInfo(null); setTimeline([]); setJob(null);
      setError(`Index cleared · freed ${data.cleared_size || '0 B'} · original footage was not touched.`);
    } catch (e) { setError(e.message || 'Could not clear the index'); }
    finally { if (mountedRef.current) setIndexBusy(false); }
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
            {voiceover && (
              <div className="rounded-input border border-rule bg-paper p-3 flex items-center gap-3">
                <CheckCircle2 size={17} className="text-brass shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-ink2 truncate">{voiceover.name}</p>
                  <p className="text-xs text-muted mt-1">{(voiceover.size / 1024 / 1024).toFixed(2)} MB · voiceover selected successfully</p>
                </div>
                <span className="badge-ok shrink-0"><CheckCircle2 size={12} /> ready</span>
              </div>
            )}

            <div className="block">
              <span className="readout block mb-2">footage folder</span>
              <label className="btn-quiet inline-flex cursor-pointer items-center gap-2">
                <FolderOpen size={14} />
                {resolvingFolder ? ' locating folder…' : ' choose footage folder'}
                <input type="file" multiple webkitdirectory="" directory="" accept="video/*" className="hidden"
                  onChange={async e => {
                    const files = Array.from(e.target.files || []);
                    setFootage(files); setFootageRoot(''); setFootageFolderName(''); setFolderResolutionError(''); setError(''); setIndexInfo(null);
                    if (!files.length) return;
                    const first = files[0];
                    const folderName = (first.webkitRelativePath || '').split('/')[0] || '';
                    setFootageFolderName(folderName);
                    const nativePath = first.path;
                    const relativePath = (first.webkitRelativePath || '').replace(/^\/+|\/+$/g, '');
                    if (nativePath && (nativePath.startsWith('/Users/') || nativePath.startsWith('/Volumes/'))) {
                      const rootPath = relativePath && nativePath.endsWith(relativePath)
                        ? nativePath.slice(0, nativePath.length - relativePath.length).replace(/\/$/, '')
                        : nativePath.slice(0, nativePath.lastIndexOf('/'));
                      setFootageRoot(rootPath);
                      setResolvingFolder(false);
                      return;
                    }
                    setResolvingFolder(true);
                    try {
                      const resolveRes = await fetch(`${ANALYZER_URL}/api/footage-analyzer/resolve-folder`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ folder_name: folderName, samples: files.slice(0, 10).map(f => ({ relative_path: f.webkitRelativePath, size: f.size })) })
                      });
                      const resolveData = await resolveRes.json().catch(() => ({}));
                      if (!resolveRes.ok) {
                        const detail = typeof resolveData.detail === 'string' ? resolveData.detail : resolveData.detail?.message || 'Could not locate the selected folder';
                        throw new Error(detail);
                      }
                      setFootageRoot(resolveData.path);
                      setFolderResolutionError('');
                    } catch (err) {
                      const message = err.message || 'Could not locate the selected folder';
                      setFolderResolutionError(message);
                      setError(message);
                    } finally { setResolvingFolder(false); }
                  }}
                />
              </label>
              <p className="text-[11px] text-muted mt-2">Choose the folder in Finder. The folder itself is not uploaded; the analyzer reads it from the mounted Mac filesystem.</p>
            </div>

            <div className="rounded-input border border-rule bg-paper p-3 flex items-start gap-3">
              {resolvingFolder ? <Loader2 size={17} className="text-brass mt-0.5 shrink-0 animate-spin" /> : footageRoot ? <CheckCircle2 size={17} className="text-brass mt-0.5 shrink-0" /> : folderResolutionError ? <AlertTriangle size={17} className="text-brass mt-0.5 shrink-0" /> : <FolderOpen size={17} className="text-muted mt-0.5 shrink-0" />}
              <div className="min-w-0 flex-1">
                <p className="text-sm text-ink2">{resolvingFolder ? 'Checking analyzer access…' : footageFolderName || 'No footage folder selected'}</p>
                {footageRoot ? (
                  <>
                    <p className="text-xs text-muted mt-1 break-all">{footageRoot}</p>
                    <p className="text-[11px] text-muted mt-1">{footageCount} video files detected · analyzer can access this folder</p>
                  </>
                ) : folderResolutionError ? (
                  <>
                    <p className="text-xs text-muted mt-1 leading-relaxed">{footageCount} video files detected in the browser, but the analyzer cannot access this folder yet.</p>
                    <p className="text-[11px] text-brass mt-1 leading-relaxed">{folderResolutionError}</p>
                  </>
                ) : (
                  <p className="text-xs text-muted mt-1">{footageCount ? `${footageCount} video files detected · checking analyzer access…` : 'Select a footage folder from Finder.'}</p>
                )}
              </div>
            </div>

            {footageRoot && (
              <div className="border border-rule rounded-input p-3 bg-paper">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2"><HardDrive size={15} className="text-brass" /><span className="readout">PERSISTENT INDEX</span><button onClick={() => refreshIndex()} className="text-muted" title="Refresh"><RefreshCw size={13} /></button></div>
                  <span className="text-xs text-muted">{indexInfo?.size || '0 B'}</span>
                </div>
                <div className="grid grid-cols-3 gap-2 mt-3 text-center">
                  <div><p className="text-sm text-ink2">{indexInfo?.files_indexed || 0}/{indexInfo?.files_total || 0}</p><p className="readout">files indexed</p></div>
                  <div><p className="text-sm text-ink2">{indexInfo?.visual_shots_completed || 0}</p><p className="readout">visual analyses</p></div>
                  <div><p className="text-sm text-ink2">{indexInfo?.files_failed || 0}</p><p className="readout">failed/retry</p></div>
                </div>
                <button onClick={clearIndex} disabled={indexBusy || job?.status === 'processing' || job?.status === 'queued'} className="btn-quiet text-xs mt-3"><Trash2 size={13} />{indexBusy ? ' clearing…' : ' clear index / free storage'}</button>
                <p className="text-[10px] text-muted mt-2">Clears analyzer-generated index/cache only. Original video files are never deleted.</p>
              </div>
            )}

            <label className="block">
              <span className="readout block mb-2">optional editorial direction</span>
              <textarea className="input-field min-h-[92px] resize-y" placeholder="e.g. Prefer archival-looking footage and wide establishing shots when exact subjects are unavailable." value={instruction} onChange={e => setInstruction(e.target.value)} />
            </label>

            {voiceover && footageRoot && !resolvingFolder && (
              <div className="rounded-input border border-rule bg-paper p-3 flex items-center gap-3">
                <CheckCircle2 size={18} className="text-brass shrink-0" />
                <div>
                  <p className="text-sm text-ink2">Ready to analyze</p>
                  <p className="text-xs text-muted mt-1">{indexInfo?.files_indexed ? `Resumable index: ${indexInfo.files_indexed} files already completed; unchanged files will be skipped.` : 'A persistent index will be created. Progress is saved after every file.'}</p>
                </div>
              </div>
            )}

            <div className="flex items-center gap-3">
              <button className="btn-primary flex-1" disabled={!voiceover || !footageRoot.trim() || resolvingFolder || job?.status === 'processing' || job?.status === 'queued'} onClick={startAnalysis}>
                {job?.status === 'processing' ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                {job?.status === 'processing' ? ' analyzing…' : job?.status === 'failed' ? ' retry analysis' : ' analyze footage'}
              </button>
              {job?.status === 'complete' && <span className="badge-ok"><CheckCircle2 size={12} /> complete</span>}
              {job?.status === 'failed' && <span className="badge-warn"><AlertTriangle size={12} /> resumable</span>}
            </div>

            {job && job.status !== 'complete' && (
              <div className="border border-rule rounded-input p-4 bg-paper">
                <div className="flex items-start gap-3 mb-3">
                  <div className="mt-0.5 shrink-0">
                    {job.status === 'failed' ? <AlertTriangle size={19} className="text-brass" /> : <Loader2 size={19} className="text-brass animate-spin" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium text-ink2">
                        {job.status === 'failed' ? 'Analysis stopped — saved progress is available' : (
                          job.stage === 'transcription' ? '🎙️ Transcribing audio…' :
                          job.stage === 'indexing' ? '🎬 Indexing / analyzing video files…' :
                          job.stage === 'visual_analysis' ? '🧠 Analyzing video…' :
                          job.stage === 'visual_plan' ? '🧭 Building visual plan…' :
                          job.stage === 'matching' ? '🔗 Matching footage to narration…' :
                          job.stage === 'resuming' ? '↻ Resuming saved analysis…' :
                          'Starting Footage Analyzer…'
                        )}
                      </p>
                      <span className="readout shrink-0">{job.progress || 0}%</span>
                    </div>
                    {job.current_file && (
                      <p className="text-xs text-ink2 truncate mt-2" title={job.current_file}>
                        {job.stage === 'transcription' ? 'audio · ' : 'video · '}{job.current_file}
                      </p>
                    )}
                    {job.status === 'failed' && (
                      <p className="text-[11px] text-muted mt-2 leading-relaxed">
                        Completed files and successful visual analyses were saved to the persistent index. Retry to continue with the remaining work.
                      </p>
                    )}
                  </div>
                </div>

                <div className="h-1.5 bg-paper rounded-full overflow-hidden">
                  <div className="h-full bg-accent transition-all" style={{width: `${job.progress || 0}%`}} />
                </div>

                <div className="grid grid-cols-2 gap-2 mt-3">
                  {job.stage === 'transcription' ? (
                    <div className="rounded-input border border-rule px-3 py-2">
                      <p className="readout">VOICEOVER</p>
                      <p className="text-xs text-ink2 truncate mt-1">{job.current_file || 'processing audio…'}</p>
                    </div>
                  ) : (
                    <div className="rounded-input border border-rule px-3 py-2">
                      <p className="readout">FOOTAGE</p>
                      <p className="text-xs text-ink2 truncate mt-1">{job.current_file || 'preparing video…'}</p>
                    </div>
                  )}
                  <div className="rounded-input border border-rule px-3 py-2">
                    <p className="readout">PROGRESS</p>
                    <p className="text-xs text-ink2 mt-1">
                      {job.stage === 'visual_analysis' && job.visual_stats
                        ? `scene ${job.visual_stats.done || 0}/${job.visual_stats.total || 0} · ${job.visual_stats.reused || 0} reused`
                        : job.index_stats
                          ? `file ${job.index_stats.done || 0}/${job.index_stats.total || 0} · ${job.index_stats.reused || 0} reused`
                          : job.status === 'failed' ? 'saved · retryable' : 'working…'}
                    </p>
                  </div>
                </div>

                {job.message && (
                  <p className="text-[11px] text-muted mt-3 truncate" title={job.message}>{job.message}</p>
                )}
              </div>
            )}

            {error && <div className="border border-rule rounded-input p-3 text-xs text-muted"><AlertTriangle size={14} className="inline mr-2 text-brass" />{error}</div>}

            <div className="border-t border-rule pt-4 grid grid-cols-3 gap-3 text-center">
              <div><Mic2 size={15} className="mx-auto text-brass mb-1" /><p className="readout">voiceover</p><p className="text-sm text-ink2 mt-1">{voiceover ? '✓ ready' : 'missing'}</p></div>
              <div><Film size={15} className="mx-auto text-brass mb-1" /><p className="readout">footage</p><p className="text-sm text-ink2 mt-1">{footageRoot ? '✓ ready' : resolvingFolder ? 'locating…' : 'missing'}</p></div>
              <div><Search size={15} className="mx-auto text-brass mb-1" /><p className="readout">matching</p><p className="text-sm text-ink2 mt-1">semantic</p></div>
            </div>
          </section>

          <section className="card p-5 min-h-[560px]">
            <div className="flex items-start justify-between gap-4 mb-5">
              <div>
                <p className="eyebrow mb-2">VISUAL TIMELINE</p>
                <h2 className="font-display lowercase text-xl text-ink">Voiceover → usable footage</h2>
              </div>
              {job?.status === 'complete' && <a className="btn-quiet" href={`${ANALYZER_URL}/api/footage-analyzer/jobs/${job.id}/edl/download`}><Download size={13} /> EDL</a>}
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
                      <ChevronDown size={14} className={`text-muted transition-transform ${expanded === i ? 'rotate-180' : ''}`} />
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
