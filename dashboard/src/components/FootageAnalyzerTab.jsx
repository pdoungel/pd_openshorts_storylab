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
  const [uploadProgress, setUploadProgress] = useState(0);
  const folderInputRef = useRef(null);
  const pollRef = useRef(null);
  const pollAbortRef = useRef(null);
  const mountedRef = useRef(true);
  const pollingRef = useRef(false);

  const [inputMode, setInputMode] = useState('voiceover');
  const [script, setScript] = useState('');
  const [visualCues, setVisualCues] = useState('');
  const [copied, setCopied] = useState('');
  const [aspect, setAspect] = useState(() => { try { return localStorage.getItem('fa_aspect') || '9:16'; } catch (_) { return '9:16'; } });
  const [fit, setFit] = useState(() => { try { return localStorage.getItem('fa_fit') || 'blur'; } catch (_) { return 'blur'; } });
  useEffect(() => { try { localStorage.setItem('fa_aspect', aspect); localStorage.setItem('fa_fit', fit); } catch (_) { /* storage unavailable */ } }, [aspect, fit]);
  const hasNarration = inputMode === 'voiceover' ? !!voiceover : !!script.trim();
  const [pastedPath, setPastedPath] = useState('');
  const [pastedCount, setPastedCount] = useState(0);
  const footageCount = footage.length || pastedCount;
  const totalSize = useMemo(() => footage.reduce((n, f) => n + (f.size || 0), 0), [footage]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (pollRef.current) window.clearTimeout(pollRef.current);
      if (pollAbortRef.current) pollAbortRef.current.abort();
    };
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

    // Poll one request at a time. Do not use setInterval here: an in-flight
    // request can otherwise overlap the next request or be aborted by a
    // subsequent poll, leaving the UI stuck on the POST response (often 1%).
    const tick = async () => {
      if (!mountedRef.current) return;
      const controller = new AbortController();
      pollAbortRef.current = controller;
      try {
        const url = `${ANALYZER_URL}/api/footage-analyzer/jobs/${id}?_=${Date.now()}`;
        const res = await fetch(url, {
          signal: controller.signal,
          cache: 'no-store',
          headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' }
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        if (!mountedRef.current) return;

        setJob(data);
        if (data.index_stats) setIndexInfo(data.index_stats);

        if (data.status === 'complete') {
          setTimeline(data.result?.clips || []);
          stopPolling();
          refreshIndex(data.footage_root || footageRoot);
          return;
        }
        if (data.status === 'failed') {
          setError(data.error?.message || data.message || 'Analysis failed');
          stopPolling();
          return;
        }
      } catch (e) {
        if (e?.name === 'AbortError') return;
        if (mountedRef.current) setError(e.message || 'Could not reach Footage Analyzer');
      } finally {
        if (pollAbortRef.current === controller) pollAbortRef.current = null;
      }

      if (mountedRef.current) pollRef.current = window.setTimeout(tick, 500);
    };

    tick();
  };

  const startAnalysis = async () => {
    if (!hasNarration || !footageRoot.trim()) {
      setError(`Add a ${inputMode === 'voiceover' ? 'voiceover' : 'script'} and choose a footage folder that can be located by the analyzer.`);
      return;
    }
    setError('');
    setTimeline([]);
    setUploadProgress(0);
    setJob({ status: 'queued', stage: 'queued', progress: 0, message: 'Sending to Footage Analyzer…' });
    try {
      const form = new FormData();
      if (inputMode === 'voiceover') form.append('voiceover', voiceover);
      else form.append('script', script);
      form.append('footage_root', footageRoot.trim());
      form.append('instruction', instruction);
      form.append('visual_cues', visualCues);
      form.append('aspect', aspect);
      form.append('fit', fit);
      // Use XMLHttpRequest for the multipart upload. Some desktop/webview
      // clients can close a fetch request while a File-backed FormData body is
      // being sent; XHR keeps the upload request alive until the response arrives.
      const data = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', `${ANALYZER_URL}/api/footage-analyzer/jobs`, true);
        xhr.responseType = 'text';
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable && mountedRef.current) {
            const pct = Math.round((event.loaded / event.total) * 100);
            setUploadProgress(pct);
            setJob(prev => prev?.status === 'queued' ? { ...prev, message: `Uploading voiceover… ${pct}%` } : prev);
          }
        };
        xhr.onload = () => {
          let body = {};
          try { body = xhr.responseText ? JSON.parse(xhr.responseText) : {}; } catch {}
          if (xhr.status >= 200 && xhr.status < 300) resolve(body);
          else reject(new Error(body.detail || body.message || `Could not start analysis (HTTP ${xhr.status})`));
        };
        xhr.onerror = () => reject(new Error('Could not connect to Footage Analyzer. Check that the analyzer service is running.'));
        xhr.onabort = () => reject(new Error('The upload request was aborted before Footage Analyzer received it.'));
        xhr.ontimeout = () => reject(new Error('Timed out while starting Footage Analyzer.'));
        // Do not impose a short wall-clock timeout: the browser may be uploading
        // a large WAV before the backend can create the job and return its ID.
        xhr.timeout = 0;
        xhr.send(form);
      });
      if (!data?.id) throw new Error(data?.detail || 'Footage Analyzer did not return a job ID');
      setUploadProgress(100);
      setJob(data);
      pollJob(data.id);
    } catch (e) {
      setError(e.message || 'Could not start analysis');
      setUploadProgress(0);
      setJob(null);
    }
  };

  const resolveSelectedFolder = async (folderName, files) => {
    if (!folderName || !files.length) throw new Error('Select a footage folder containing supported video files.');

    const resolveData = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', ANALYZER_URL + '/api/footage-analyzer/resolve-folder', true);
      xhr.setRequestHeader('Content-Type', 'application/json');
      xhr.timeout = 20000;
      xhr.onload = () => {
        let body = {};
        try { body = xhr.responseText ? JSON.parse(xhr.responseText) : {}; } catch {}
        if (xhr.status >= 200 && xhr.status < 300) resolve(body);
        else {
          const detail = typeof body.detail === 'string'
            ? body.detail
            : body.detail?.message || 'Could not resolve the selected footage folder.';
          reject(new Error(detail));
        }
      };
      xhr.onerror = () => reject(new Error('Could not connect to Footage Analyzer while resolving the folder.'));
      xhr.ontimeout = () => reject(new Error('Timed out while resolving the selected footage folder.'));
      xhr.onabort = () => reject(new Error('Folder resolution was aborted.'));
      xhr.send(JSON.stringify({
        folder_name: folderName,
        samples: files.slice(0, 20).map(file => ({
          name: file.name,
          relative_path: file.webkitRelativePath || file.name,
          size: file.size
        }))
      }));
    });

    if (!resolveData.path) throw new Error('Footage Analyzer resolved the selection but returned no folder path.');
    setFootage(files);
    setFootageFolderName(resolveData.folder_name || folderName);
    setFootageRoot(resolveData.path);
    setFolderResolutionError('');
    setError('');
    // The folder is fully resolved at this point. The Analyze action is
    // intentionally driven by footageRoot, not by the temporary File list.
    if (mountedRef.current) setResolvingFolder(false);
    return resolveData;
  };

  const handleFolderFiles = async (fileList) => {
    const all = Array.from(fileList || []);
    const videos = all.filter(file =>
      file?.type?.startsWith('video/') ||
      /\.(mp4|mov|mkv|m4v|webm|avi|mts|m2ts|ts)$/i.test(file?.name || '')
    );
    if (!videos.length) throw new Error('The selected folder contains no supported video files.');

    const firstRelative = videos[0].webkitRelativePath || '';
    const folderName = firstRelative.split('/')[0] || '';
    if (!folderName) {
      throw new Error('OpenShorts received video files without their folder path. Use the folder selector rather than selecting individual files.');
    }
    await resolveSelectedFolder(folderName, videos);
  };

  const chooseFootageFolder = async () => {
    if (resolvingFolder) return;
    setError('');
    setFolderResolutionError('');
    setFootageRoot('');
    setFootage([]);
    setPastedCount(0);
    setFootageFolderName('');
    setIndexInfo(null);
    setResolvingFolder(true);
    try {
      if (typeof window.showDirectoryPicker === 'function') {
        const handle = await window.showDirectoryPicker({ id: 'openshorts-footage', mode: 'read' });
        const files = [];
        const walk = async (dir, prefix = '') => {
          for await (const entry of dir.values()) {
            if (entry.name.startsWith('.')) continue;
            if (entry.kind === 'directory') {
              await walk(entry, prefix ? prefix + '/' + entry.name : entry.name);
            } else if (entry.kind === 'file') {
              const file = await entry.getFile();
              if (file.type.startsWith('video/') || /\.(mp4|mov|mkv|m4v|webm|avi|mts|m2ts|ts)$/i.test(file.name)) {
                try {
                  Object.defineProperty(file, 'webkitRelativePath', {
                    configurable: true,
                    value: handle.name + '/' + (prefix ? prefix + '/' : '') + file.name
                  });
                } catch (_) {}
                files.push(file);
              }
            }
          }
        };
        await walk(handle);
        await resolveSelectedFolder(handle.name, files);
      } else {
        // Fallback for Chromium/Electron builds without File System Access:
        // webkitdirectory opens the OS directory chooser and returns its
        // contents. The UI never asks the user to choose individual videos.
        folderInputRef.current?.click();
      }
    } catch (err) {
      if (err?.name !== 'AbortError') {
        const message = err?.message || 'Could not select the footage folder.';
        setFolderResolutionError(message);
        setError(message);
      }
    } finally {
      if (typeof window.showDirectoryPicker === 'function' && mountedRef.current) setResolvingFolder(false);
    }
  };

  const rerender = async () => {
    if (!job?.id) return;
    setError('');
    try {
      const res = await fetch(`${ANALYZER_URL}/api/footage-analyzer/jobs/${job.id}/render`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ aspect, fit })
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Re-render failed to start');
      setJob(body);
      pollJob(job.id);
    } catch (e) {
      setError(e.message || 'Re-render failed to start');
    }
  };

  const applyPastedPath = async () => {
    const root = pastedPath.trim().replace(/^["']|["']$/g, '');
    if (!root || resolvingFolder) return;
    setError('');
    setFolderResolutionError('');
    setFootage([]);
    setResolvingFolder(true);
    try {
      const res = await fetch(`${ANALYZER_URL}/api/footage-analyzer/index?root=${encodeURIComponent(root)}`, { cache: 'no-store' });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'The analyzer cannot access this folder.');
      setPastedCount(body.video_count || 0);
      setFootageFolderName(root.split(/[\\/]/).filter(Boolean).pop() || root);
      setFootageRoot(body.root || root);
    } catch (err) {
      setFootageRoot('');
      setFolderResolutionError(err?.message || 'The analyzer cannot access this folder.');
    } finally {
      if (mountedRef.current) setResolvingFolder(false);
    }
  };

  const onFolderInputChange = async (event) => {
    try {
      await handleFolderFiles(event.target.files);
    } catch (err) {
      const message = err?.message || 'Could not select the footage folder.';
      setFolderResolutionError(message);
      setError(message);
    } finally {
      event.target.value = '';
      if (mountedRef.current) setResolvingFolder(false);
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

            <div className="flex gap-2" role="tablist" aria-label="Narration source">
              {[['voiceover', 'voiceover file'], ['script', 'script → AI voiceover']].map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  role="tab"
                  aria-selected={inputMode === mode}
                  className={`btn-quiet text-xs ${inputMode === mode ? 'border-brass text-ink' : ''}`}
                  onClick={() => setInputMode(mode)}
                >{label}</button>
              ))}
            </div>

            {inputMode === 'script' ? (
              <label className="block">
                <span className="readout block mb-2">script · narrated with Gemini TTS, then used as the timeline</span>
                <textarea className="input-field min-h-[160px] resize-y" placeholder="Paste the full narration script. Blank lines separate paragraphs." value={script} onChange={e => setScript(e.target.value)} />
                <p className="text-[11px] text-muted mt-1">{script.trim() ? `${script.trim().split(/\s+/).length} words · about ${Math.max(1, Math.round(script.trim().split(/\s+/).length / 150))} min of narration` : 'The generated voiceover is included in the final video.'}</p>
              </label>
            ) : (
              <label className="block">
                <span className="readout block mb-2">voiceover · wav / mp3 / m4a</span>
                <input type="file" accept="audio/*" className="input-field" onChange={e => setVoiceover(e.target.files?.[0] || null)} />
              </label>
            )}
            {inputMode === 'voiceover' && voiceover && (
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
              <button
                type="button"
                className="btn-quiet inline-flex items-center gap-2"
                disabled={resolvingFolder}
                onClick={chooseFootageFolder}
              >
                <FolderOpen size={14} />
                {resolvingFolder ? ' locating folder…' : ' choose footage folder'}
              </button>
              <input
                ref={folderInputRef}
                type="file"
                hidden
                multiple
                webkitdirectory=""
                directory=""
                onChange={onFolderInputChange}
                aria-label="Choose footage folder"
              />
              <p className="text-[11px] text-muted mt-2">
                Select one footage folder. OpenShorts recursively discovers supported videos; individual video selection is not required.
              </p>
              <div className="flex gap-2 mt-3">
                <input
                  type="text"
                  className="flex-1 min-w-0 rounded-input border border-rule bg-paper px-3 py-2 text-sm text-ink2 placeholder:text-muted outline-none focus:border-brass"
                  placeholder="or paste folder path, e.g. D:\Footage\Project"
                  value={pastedPath}
                  onChange={e => setPastedPath(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') applyPastedPath(); }}
                  aria-label="Footage folder path"
                />
                <button type="button" className="btn-quiet" disabled={!pastedPath.trim() || resolvingFolder} onClick={applyPastedPath}>use path</button>
              </div>
            </div>

            <div className="rounded-input border border-rule bg-paper p-3 flex items-start gap-3">
              {resolvingFolder && !footageRoot ? <Loader2 size={17} className="text-brass mt-0.5 shrink-0 animate-spin" /> : footageRoot ? <CheckCircle2 size={17} className="text-brass mt-0.5 shrink-0" /> : folderResolutionError ? <AlertTriangle size={17} className="text-brass mt-0.5 shrink-0" /> : <FolderOpen size={17} className="text-muted mt-0.5 shrink-0" />}
              <div className="min-w-0 flex-1">
                <p className="text-sm text-ink2">{resolvingFolder && !footageRoot ? 'Checking analyzer access…' : footageFolderName || 'No footage folder selected'}</p>
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
                  <p className="text-xs text-muted mt-1">{footageCount ? `${footageCount} video files detected · checking analyzer access…` : 'Choose a footage folder or paste its path.'}</p>
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

            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="readout block mb-2">video format</span>
                <select className="input-field" value={aspect} onChange={e => setAspect(e.target.value)}>
                  <option value="9:16">9:16 vertical (Shorts, Reels, TikTok)</option>
                  <option value="16:9">16:9 horizontal (YouTube)</option>
                  <option value="1:1">1:1 square</option>
                  <option value="4:5">4:5 portrait feed</option>
                </select>
              </label>
              <label className="block">
                <span className="readout block mb-2">fit footage</span>
                <select className="input-field" value={fit} onChange={e => setFit(e.target.value)}>
                  <option value="blur">fit + blurred background</option>
                  <option value="crop">fill (crop center)</option>
                  <option value="pad">fit + black bars</option>
                </select>
              </label>
            </div>

            <label className="block">
              <span className="readout block mb-2">optional visual cues · alternatives to search for</span>
              <input type="text" className="input-field" placeholder="e.g. city skyline at night, hands typing, crowds, maps" value={visualCues} onChange={e => setVisualCues(e.target.value)} />
            </label>

            <label className="block">
              <span className="readout block mb-2">optional editorial direction</span>
              <textarea className="input-field min-h-[92px] resize-y" placeholder="e.g. Prefer archival-looking footage and wide establishing shots when exact subjects are unavailable." value={instruction} onChange={e => setInstruction(e.target.value)} />
            </label>

            {hasNarration && footageRoot && (
              <div className="rounded-input border border-rule bg-paper p-3 flex items-center gap-3">
                <CheckCircle2 size={18} className="text-brass shrink-0" />
                <div>
                  <p className="text-sm text-ink2">Ready to analyze</p>
                  <p className="text-xs text-muted mt-1">{indexInfo?.files_indexed ? `Resumable index: ${indexInfo.files_indexed} files already completed; unchanged files will be skipped.` : 'A persistent index will be created. Progress is saved after every file.'}</p>
                </div>
              </div>
            )}

            <div className="flex items-center gap-3">
              <button className="btn-primary flex-1" disabled={!hasNarration || !footageRoot.trim() || job?.status === 'processing' || job?.status === 'queued'} onClick={startAnalysis}>
                {job?.status === 'processing' ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                {job?.status === 'queued' ? ` uploading… ${uploadProgress}%` : job?.status === 'processing' ? ' analyzing…' : job?.status === 'failed' ? ' retry analysis' : ' analyze footage'}
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
                        {job.status === 'queued' ? 'Uploading voiceover…' : job.status === 'failed' ? 'Analysis stopped — saved progress is available' : (
                          job.stage === 'voiceover_synthesis' ? '🗣️ Generating voiceover from script…' :
                          job.stage === 'transcription' ? '🎙️ Transcribing audio…' :
                          job.stage === 'metadata' ? '📝 Writing title, description and tags…' :
                          job.stage === 'rendering' ? '🎬 Rendering final video…' :
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
                    {job.status === 'queued' ? (
                      <div className="mt-2 rounded-input border border-rule bg-paper p-3 space-y-1">
                        <p className="readout">VOICEOVER UPLOAD</p>
                        <p className="text-sm text-ink2">{uploadProgress}% · sending audio to analyzer</p>
                        <div className="h-1.5 bg-paper rounded-full overflow-hidden"><div className="h-full bg-accent transition-all" style={{width: `${uploadProgress}%`}} /></div>
                      </div>
                    ) : job.stage === 'transcription' ? (
                      <div className="mt-2 rounded-input border border-rule bg-paper p-3 space-y-1">
                        <p className="readout">UPLOADED VOICEOVER · ACTUALLY PROCESSING</p>
                        <p className="text-sm text-ink2 truncate" title={job.voiceover_original_name || job.current_file}>
                          🎙️ {job.voiceover_original_name || job.current_file || 'unknown file'}
                        </p>
                        {job.voiceover_job_path && (
                          <p className="text-[10px] text-muted truncate" title={job.voiceover_job_path}>
                            worker file · {job.voiceover_job_path}
                          </p>
                        )}
                        {job.voiceover_sha256 && (
                          <p className="text-[10px] text-muted font-mono truncate" title={job.voiceover_sha256}>
                            SHA256 · {job.voiceover_sha256}
                          </p>
                        )}
                      </div>
                    ) : job.current_file ? (
                      <p className="text-xs text-ink2 truncate mt-2" title={job.current_file}>
                        video · {job.current_file}
                      </p>
                    ) : null}
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
              <div><Mic2 size={15} className="mx-auto text-brass mb-1" /><p className="readout">{inputMode === 'script' ? 'script' : 'voiceover'}</p><p className="text-sm text-ink2 mt-1">{hasNarration ? '✓ ready' : 'missing'}</p></div>
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
              {job?.status === 'complete' && job.id && <a className="btn-quiet" href={`${ANALYZER_URL}/api/footage-analyzer/jobs/${job.id}/edl/download`}><Download size={13} /> EDL</a>}
            </div>

            {job?.status === 'complete' && job.id && (
              <div className="space-y-4 mb-5">
                {(job.result?.warnings || []).map(w => (
                  <div key={w} className="border border-rule rounded-input p-3 text-xs text-muted leading-relaxed"><AlertTriangle size={13} className="inline mr-2 text-brass" />{w}</div>
                ))}
                {job.render_error && (
                  <div className="border border-rule rounded-input p-3 text-xs text-muted"><AlertTriangle size={13} className="inline mr-2 text-brass" />Render failed: {job.render_error}</div>
                )}
                {job.video_path && (
                  <div className="border border-rule rounded-input overflow-hidden bg-paper">
                    <div className="bg-black flex justify-center">
                      <video
                        key={job.updated_at}
                        className={`bg-black ${['9:16', '4:5'].includes(job.aspect) ? 'max-h-[640px] w-auto' : 'w-full'}`}
                        style={{ aspectRatio: (job.aspect || '16:9').replace(':', ' / ') }}
                        controls
                        preload="metadata"
                        src={`${ANALYZER_URL}/api/footage-analyzer/jobs/${job.id}/video?v=${job.updated_at}`}
                      />
                    </div>
                    <div className="p-3 space-y-2">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-xs text-muted">Final video · {job.aspect || '16:9'} · {formatTime(job.result?.voiceover_duration)}</p>
                        <a className="btn-quiet text-xs" href={`${ANALYZER_URL}/api/footage-analyzer/jobs/${job.id}/video?download=true`}><Download size={13} /> MP4</a>
                      </div>
                      {job.export_path && (
                        <p className="text-[11px] text-muted break-all">Saved to <span className="text-ink2">{job.export_path}</span> (YouTube text beside it as .youtube.txt)</p>
                      )}
                    </div>
                  </div>
                )}
                {job.result && (
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="readout">re-render as</span>
                    <select className="input-field !w-auto !py-1 text-xs" value={aspect} onChange={e => setAspect(e.target.value)}>
                      <option value="9:16">9:16</option><option value="16:9">16:9</option><option value="1:1">1:1</option><option value="4:5">4:5</option>
                    </select>
                    <select className="input-field !w-auto !py-1 text-xs" value={fit} onChange={e => setFit(e.target.value)}>
                      <option value="blur">blurred background</option><option value="crop">crop center</option><option value="pad">black bars</option>
                    </select>
                    <button type="button" className="btn-quiet text-xs" onClick={rerender}><RefreshCw size={13} /> re-render</button>
                    <span className="text-muted">no re-analysis needed</span>
                  </div>
                )}
                {job.metadata && (() => {
                  const m = job.metadata;
                  const tagText = (m.tags || []).join(', ');
                  const copy = async (key, text) => {
                    try { await navigator.clipboard.writeText(text); setCopied(key); setTimeout(() => setCopied(''), 1500); } catch (_) { setCopied(''); }
                  };
                  const CopyBtn = ({ k, text }) => (
                    <button type="button" className="text-[11px] text-muted hover:text-ink2" onClick={() => copy(k, text)}>{copied === k ? 'copied' : 'copy'}</button>
                  );
                  return (
                    <div className="border border-rule rounded-input p-4 bg-paper space-y-4">
                      <p className="eyebrow">YOUTUBE PACKAGE{m.provider === 'fallback' ? ' · basic (Gemini unavailable)' : ''}</p>
                      <div>
                        <div className="flex items-center justify-between"><span className="readout">title</span><CopyBtn k="title" text={m.title} /></div>
                        <p className="text-sm text-ink2 mt-1">{m.title}</p>
                        {(m.title_options || []).filter(t => t !== m.title).length > 0 && (
                          <ul className="mt-2 space-y-1">
                            {m.title_options.filter(t => t !== m.title).map(t => (
                              <li key={t} className="flex items-center justify-between gap-3 text-xs text-muted"><span>{t}</span><CopyBtn k={t} text={t} /></li>
                            ))}
                          </ul>
                        )}
                      </div>
                      <div>
                        <div className="flex items-center justify-between"><span className="readout">description</span><CopyBtn k="description" text={m.description} /></div>
                        <p className="text-xs text-muted mt-1 whitespace-pre-line leading-relaxed max-h-56 overflow-y-auto custom-scrollbar">{m.description}</p>
                      </div>
                      <div>
                        <div className="flex items-center justify-between"><span className="readout">tags · {(m.tags || []).length}</span><CopyBtn k="tags" text={tagText} /></div>
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {(m.tags || []).map(t => <span key={t} className="text-[11px] text-ink2 border border-rule rounded-full px-2 py-0.5">{t}</span>)}
                        </div>
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}

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
                      <div className="min-w-0 flex-1"><p className="text-sm text-ink2 truncate">{clip.description || clip.visual_query || 'Visual match'}</p><p className="text-xs text-muted mt-1 truncate">#{clip.sequence || i + 1} · narration {Number(clip.narration_index) + 1} · {clip.source_path} · {formatTime(clip.source_start)}–{formatTime(clip.source_end)}</p></div>
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
