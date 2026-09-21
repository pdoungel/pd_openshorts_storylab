import React, { useState, useEffect, useMemo } from 'react';
import { Loader2, Download, Film, FolderOpen, HardDrive, Trash2, Sparkles, ChevronDown } from 'lucide-react';
import { apiJson } from '../lib/api';

// The signed-in user's saved video library (stored in R2). Private, signed links.
// Videos are grouped by project (job); re-openable projects get a "reopen"
// action that restores the whole job for further editing in the Clip Generator.
export default function HistoryTab({ onReopenProject, local = false }) {
  const [videos, setVideos] = useState(null);
  const [projects, setProjects] = useState({});
  const [reopening, setReopening] = useState(null);
  const [reopenError, setReopenError] = useState('');
  const [error, setError] = useState('');

  const [storage, setStorage] = useState({});
  const [storageOpen, setStorageOpen] = useState({});
  const [storageLoading, setStorageLoading] = useState({});
  const [storageError, setStorageError] = useState({});
  const [storageAction, setStorageAction] = useState(null);

  useEffect(() => {
    loadLibrary();
  }, []);

  const loadLibrary = async () => {
    setError('');

    if (local) {
      try {
        const d = await apiJson('/api/local-projects');

        const localProjects = (d.projects || []).map((project) => ({
          job_id: project.job_id,
          project_id: project.job_id,
          title: project.title,
          filename: project.title,
          size_bytes: project.size_bytes,
          created_at: project.created_at,
          updated_at: project.updated_at,
          clip_count: project.clip_count,
          videos: [],
        }));

        setVideos(localProjects);
        setProjects({});
      } catch (e) {
        setError('Could not load local projects.');
      }
      return;
    }

    try {
      const d = await apiJson('/api/history');
      setVideos(d.videos || []);
    } catch (e) {
      setError('Could not load your library.');
    }

    try {
      const d = await apiJson('/api/projects');
      const map = {};
      for (const p of d.projects || []) map[p.job_id] = p;
      setProjects(map);
    } catch (e) {
      // History can still be displayed even if project metadata is unavailable.
    }
  };

  const loadStorage = async (jobId) => {
    setStorageLoading((prev) => ({ ...prev, [jobId]: true }));
    setStorageError((prev) => ({ ...prev, [jobId]: '' }));

    try {
      const data = await apiJson(`/api/projects/${jobId}/storage`);
      setStorage((prev) => ({ ...prev, [jobId]: data }));
    } catch (e) {
      setStorageError((prev) => ({
        ...prev,
        [jobId]: 'Could not inspect project storage.',
      }));
    } finally {
      setStorageLoading((prev) => ({ ...prev, [jobId]: false }));
    }
  };

  const toggleStorage = async (jobId) => {
    const nextOpen = !storageOpen[jobId];

    setStorageOpen((prev) => ({ ...prev, [jobId]: nextOpen }));

    if (nextOpen && !storage[jobId]) {
      await loadStorage(jobId);
    }
  };

  const handleDeleteSource = async (jobId) => {
    const info = storage[jobId];

    if (!info?.source?.exists) return;

    const filename = info.source.filename || 'the original source video';
    const confirmed = window.confirm(
      `Delete the original source video "${filename}"?\n\n` +
      `This will free ${formatBytes(info.source.size_bytes)}.\n\n` +
      `Generated clips and project information will be preserved.`
    );

    if (!confirmed) return;

    setStorageAction(`${jobId}:source`);

    try {
      await apiJson(`/api/projects/${jobId}/source`, {
        method: 'DELETE',
      });
      await loadStorage(jobId);
    } catch (e) {
      window.alert('Could not delete the source video. Please try again.');
    } finally {
      setStorageAction(null);
    }
  };

  const handleCleanProject = async (jobId) => {
    const info = storage[jobId];

    const temporaryBytes = (info?.temporary_files || [])
      .reduce((sum, file) => sum + (file.size_bytes || 0), 0);

    const sourceBytes = info?.source?.size_bytes || 0;
    const reclaimable = sourceBytes + temporaryBytes;

    const confirmed = window.confirm(
      `Clean this project?\n\n` +
      `This will remove the original source video and disposable temporary files.\n\n` +
      `Approximately ${formatBytes(reclaimable)} will be freed.\n\n` +
      `Generated clips, final videos, metadata, and project information will be preserved.`
    );

    if (!confirmed) return;

    setStorageAction(`${jobId}:clean`);

    try {
      await apiJson(`/api/projects/${jobId}/clean`, {
        method: 'POST',
      });
      await loadStorage(jobId);
    } catch (e) {
      window.alert('Could not clean this project. Please try again.');
    } finally {
      setStorageAction(null);
    }
  };

  const fmtDate = (value) => {
    if (!value) return '';

    const date = typeof value === 'number'
      ? new Date(value * 1000)
      : new Date(value);

    if (Number.isNaN(date.getTime())) return '';

    return date.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  const formatBytes = (bytes) => {
    if (!bytes || bytes <= 0) return '0 B';

    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const exponent = Math.min(
      Math.floor(Math.log(bytes) / Math.log(1024)),
      units.length - 1
    );

    return `${(bytes / Math.pow(1024, exponent)).toFixed(exponent === 0 ? 0 : 1)} ${units[exponent]}`;
  };

  const temporarySize = (info) => (
    (info?.temporary_files || [])
      .reduce((sum, file) => sum + (file.size_bytes || 0), 0)
  );

  // Group videos by job, preserving the newest-first order of /api/history.
  const groups = useMemo(() => {
    const byJob = new Map();

    for (const v of videos || []) {
      const key = v.job_id || v.id;

      if (!byJob.has(key)) {
        byJob.set(key, []);
      }

      byJob.get(key).push(v);
    }

    return [...byJob.entries()];
  }, [videos]);

  const handleReopen = async (jobId) => {
    if (!onReopenProject || reopening) return;

    setReopening(jobId);
    setReopenError('');

    try {
      await onReopenProject(jobId);
    } catch (e) {
      setReopenError('Could not reopen this project. Please try again.');
      setReopening(null);
    }
  };

  if (videos === null && !error) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="animate-spin text-brass" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-8 max-w-5xl mx-auto animate-fade">
      <p className="eyebrow mb-1.5">06 · HISTORY</p>

      <h1 className="font-display lowercase text-2xl text-ink mb-2">
        Your library
      </h1>

      <p className="text-muted text-sm mb-8 lowercase">
        All the shorts you've generated, saved while your plan is active. Kept
        for 7 days after your plan ends. Reopen a project to keep editing its clips.
      </p>

      {error && <p className="text-danger text-sm">{error}</p>}
      {reopenError && (
        <p className="text-danger text-sm mb-4">{reopenError}</p>
      )}

      {videos && videos.length === 0 && (
        <div className="text-center py-20 text-muted">
          <Film size={40} className="mx-auto mb-4 text-muted" />
          <p className="lowercase">
            No videos yet. Generate your first short from the Clip Generator.
          </p>
        </div>
      )}

      <div className="space-y-10">
        {groups.map(([jobId, vids]) => {
          const project = projects[jobId];
          const info = storage[jobId];
          const isStorageOpen = !!storageOpen[jobId];
          const isLoading = !!storageLoading[jobId];
          const isSourceAction = storageAction === `${jobId}:source`;
          const isCleanAction = storageAction === `${jobId}:clean`;
          const tempBytes = temporarySize(info);

          return (
            <section key={jobId}>
              <div className="flex flex-wrap items-center justify-between gap-3 mb-4 pb-2 border-b border-rule">
                <div className="min-w-0">
                  <p
                    className="text-sm text-ink font-medium truncate"
                    title={project?.title || vids[0]?.title}
                  >
                    {project?.title || vids[0]?.title || 'Project'}
                  </p>

                  <p className="readout mt-0.5">
                    {fmtDate(local ? project?.created_at : vids[0]?.created_at)} · {local ? (project?.clip_count || 0) : vids.length} clip
                    {(local ? (project?.clip_count || 0) : vids.length) === 1 ? '' : 's'}
                  </p>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => toggleStorage(jobId)}
                    className="btn-ghost px-3 py-2 text-xs"
                    title="View project storage and cleanup controls"
                  >
                    <HardDrive size={14} />
                    storage
                    <ChevronDown
                      size={14}
                      className={`transition-transform ${isStorageOpen ? 'rotate-180' : ''}`}
                    />
                  </button>

                  {project && onReopenProject && (
                    <button
                      onClick={() => handleReopen(jobId)}
                      disabled={!!reopening}
                      className="btn-ghost px-3 py-2 text-xs"
                      title="Restore this project in the Clip Generator to keep editing subtitles, hooks, effects and dubbing"
                    >
                      {reopening === jobId
                        ? (
                          <>
                            <Loader2 size={14} className="animate-spin" />
                            reopening…
                          </>
                        )
                        : (
                          <>
                            <FolderOpen size={14} />
                            reopen project
                          </>
                        )}
                    </button>
                  )}
                </div>
              </div>

              {isStorageOpen && (
                <div className="card mb-5 p-4 animate-fade">
                  {isLoading && (
                    <div className="flex items-center gap-2 text-muted text-sm">
                      <Loader2 size={15} className="animate-spin" />
                      Inspecting project storage…
                    </div>
                  )}

                  {!isLoading && storageError[jobId] && (
                    <p className="text-danger text-sm">
                      {storageError[jobId]}
                    </p>
                  )}

                  {!isLoading && info && (
                    <>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-5">
                        <div>
                          <p className="text-micro font-mono uppercase text-muted">
                            Project
                          </p>
                          <p className="text-sm text-ink mt-1">
                            {formatBytes(info.project_size_bytes)}
                          </p>
                        </div>

                        <div>
                          <p className="text-micro font-mono uppercase text-muted">
                            Source
                          </p>
                          <p className="text-sm text-ink mt-1">
                            {info.source?.exists
                              ? formatBytes(info.source.size_bytes)
                              : 'Deleted'}
                          </p>
                        </div>

                        <div>
                          <p className="text-micro font-mono uppercase text-muted">
                            Temporary
                          </p>
                          <p className="text-sm text-ink mt-1">
                            {formatBytes(tempBytes)}
                          </p>
                        </div>

                        <div>
                          <p className="text-micro font-mono uppercase text-muted">
                            Preserved
                          </p>
                          <p className="text-sm text-ink mt-1">
                            {formatBytes(
                              (info.preserved_files || [])
                                .reduce(
                                  (sum, file) => sum + (file.size_bytes || 0),
                                  0
                                )
                            )}
                          </p>
                        </div>
                      </div>

                      {info.source?.exists && (
                        <div className="border-t border-rule pt-4 mb-4">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-sm text-ink font-medium">
                                Source video
                              </p>
                              <p
                                className="text-xs text-muted truncate mt-1"
                                title={info.source.filename}
                              >
                                {info.source.filename}
                              </p>
                              <p className="readout mt-1">
                                {formatBytes(info.source.size_bytes)}
                              </p>
                            </div>

                            <button
                              onClick={() => handleDeleteSource(jobId)}
                              disabled={!!storageAction}
                              className="btn-ghost px-3 py-2 text-xs text-danger"
                            >
                              {isSourceAction
                                ? (
                                  <>
                                    <Loader2 size={14} className="animate-spin" />
                                    deleting…
                                  </>
                                )
                                : (
                                  <>
                                    <Trash2 size={14} />
                                    delete source video
                                  </>
                                )}
                            </button>
                          </div>
                        </div>
                      )}

                      <div className="border-t border-rule pt-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <p className="text-sm text-ink font-medium">
                              Clean project
                            </p>
                            <p className="text-xs text-muted mt-1">
                              Remove the source and disposable temporary files.
                              Generated clips and project data remain.
                            </p>
                          </div>

                          <button
                            onClick={() => handleCleanProject(jobId)}
                            disabled={!!storageAction}
                            className="btn-ghost px-3 py-2 text-xs"
                          >
                            {isCleanAction
                              ? (
                                <>
                                  <Loader2 size={14} className="animate-spin" />
                                  cleaning…
                                </>
                              )
                              : (
                                <>
                                  <Sparkles size={14} />
                                  clean project
                                </>
                              )}
                          </button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )}

              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5">
                {vids.map((v) => (
                  <div
                    key={v.id}
                    className="card card-hover overflow-hidden group"
                  >
                    <div className="aspect-[9/16] bg-black">
                      <video
                        src={v.view_url}
                        controls
                        preload="metadata"
                        className="w-full h-full object-contain"
                      />
                    </div>

                    <div className="p-3">
                      <p
                        className="text-sm text-ink font-medium line-clamp-2 mb-1"
                        title={v.title}
                      >
                        {v.title || 'Short'}
                      </p>

                      <div className="flex items-center justify-between">
                        <span className="readout">
                          {fmtDate(v.created_at)}
                        </span>

                        <a
                          href={v.download_url}
                          className="text-micro font-mono uppercase text-brass hover:text-ink flex items-center gap-1 transition-colors"
                          title="Download"
                        >
                          <Download size={14} /> Download
                        </a>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
