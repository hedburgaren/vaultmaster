'use client';

import { useEffect, useState, useMemo } from 'react';
import { getJobs, createJob, updateJob, deleteJob, triggerJob, getServers, getStorageDestinations, getRetentionPolicies, getServerDatabases, getServerDocker, browseServer, pruneDockerVolumes } from '@/lib/api';
import { backupTypeIcon, formatBytes } from '@/lib/utils';
import { useT } from '@/lib/i18n';
import Badge from '@/components/Badge';
import FormLabel from '@/components/FormLabel';
import TagInput from '@/components/TagInput';
import CronBuilder from '@/components/CronBuilder';
import { Plus, Play, Trash2, Clock, Lock, Pencil, X, FolderOpen, ArrowUp, Loader2, Database, Container, Terminal, HardDrive, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react';

const INPUT = "w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent";

const emptyForm = {
  name: '', backup_type: 'files', server_id: '', schedule_cron: '0 3 * * *', domain: '', tags: [] as string[], encrypt: false,
  // Source config fields
  source_paths: '', db_names: [] as string[], volume_names: [] as string[], script_type: 'bash', script_content: '', script_path: '',
  // Storage & retention
  destination_ids: [] as string[], storage_subdir: '', retention_id: '',
  // Advanced
  pre_script: '', post_script: '', max_retries: 2,
};

export default function JobsPage() {
  const t = useT();
  const [jobs, setJobs] = useState<any[]>([]);
  const [servers, setServers] = useState<any[]>([]);
  const [storageDests, setStorageDests] = useState<any[]>([]);
  const [retentionPolicies, setRetentionPolicies] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState({ ...emptyForm });
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Dynamic data from server
  const [databases, setDatabases] = useState<any[]>([]);
  const [dbLoading, setDbLoading] = useState(false);
  const [dbError, setDbError] = useState('');
  const [dockerInfo, setDockerInfo] = useState<any>(null);
  const [dockerLoading, setDockerLoading] = useState(false);
  const [dockerError, setDockerError] = useState('');

  // File browser state
  const [showBrowser, setShowBrowser] = useState(false);
  const [browserPath, setBrowserPath] = useState('/');
  const [browserEntries, setBrowserEntries] = useState<any[]>([]);
  const [browserLoading, setBrowserLoading] = useState(false);

  const load = () => {
    getJobs().then(setJobs).catch(() => {});
    getServers().then(setServers).catch(() => {});
    getStorageDestinations().then(setStorageDests).catch(() => {});
    getRetentionPolicies().then(setRetentionPolicies).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const allTags = useMemo(() => {
    const set = new Set<string>();
    jobs.forEach(j => j.tags?.forEach((t: string) => set.add(t)));
    return Array.from(set).sort();
  }, [jobs]);

  const selectedServer = useMemo(() => servers.find(s => s.id === form.server_id), [servers, form.server_id]);

  const openNew = () => { setEditId(null); setForm({ ...emptyForm }); setShowForm(true); setShowAdvanced(false); setDatabases([]); setDockerInfo(null); };
  const openEdit = (j: any) => {
    setEditId(j.id);
    const sc = j.source_config || {};
    setForm({
      name: j.name, backup_type: j.backup_type, server_id: j.server_id || '', schedule_cron: j.schedule_cron || '0 3 * * *',
      domain: j.domain || '', tags: j.tags || [], encrypt: j.encrypt || false,
      source_paths: (sc.paths || []).join('\n'), db_names: sc.db_names || [], volume_names: sc.volume_names || [],
      script_type: sc.script_type || 'bash', script_content: sc.script_content || '', script_path: sc.script_path || '',
      destination_ids: (j.destination_ids || []).map((id: any) => String(id)), storage_subdir: sc.subdir || '',
      retention_id: j.retention_id || '',
      pre_script: j.pre_script || '', post_script: j.post_script || '', max_retries: j.max_retries ?? 2,
    });
    setShowForm(true);
    setShowAdvanced(!!(j.pre_script || j.post_script || (j.max_retries != null && j.max_retries !== 2)));
  };
  const closeForm = () => { setShowForm(false); setEditId(null); setShowBrowser(false); };

  // Build source_config based on backup_type
  const buildSourceConfig = () => {
    switch (form.backup_type) {
      case 'files': return { paths: form.source_paths.split('\n').map(p => p.trim()).filter(Boolean), subdir: form.storage_subdir || undefined };
      case 'postgresql': case 'mysql': case 'mariadb': return { db_names: form.db_names, subdir: form.storage_subdir || undefined };
      case 'docker_volumes': return { volume_names: form.volume_names, subdir: form.storage_subdir || undefined };
      case 'custom': return { script_type: form.script_type, script_content: form.script_content || undefined, script_path: form.script_path || undefined, subdir: form.storage_subdir || undefined };
      default: return { subdir: form.storage_subdir || undefined };
    }
  };

  const handleSave = async () => {
    const payload: any = {
      name: form.name, backup_type: form.backup_type, server_id: form.server_id,
      source_config: buildSourceConfig(), schedule_cron: form.schedule_cron,
      destination_ids: form.destination_ids.filter(Boolean), retention_id: form.retention_id || null,
      tags: form.tags, domain: form.domain || null, encrypt: form.encrypt,
      pre_script: form.pre_script || null, post_script: form.post_script || null, max_retries: form.max_retries,
    };
    if (editId) { await updateJob(editId, payload); } else { await createJob(payload); }
    closeForm(); load();
  };

  const handleTrigger = async (id: string) => { await triggerJob(id); alert(t('jobs.backup_queued')); };
  const handleDelete = async (id: string) => { if (confirm(t('jobs.confirm_delete'))) { await deleteJob(id); load(); } };

  // Load databases when server changes and type is database
  const loadDatabases = async () => {
    if (!form.server_id || !selectedServer?.meta?.db_type) return;
    setDbLoading(true); setDbError('');
    try {
      const res = await getServerDatabases(form.server_id, selectedServer.meta.db_type);
      if (res.databases?.[0]?.error) { setDbError(res.databases[0].error); setDatabases([]); }
      else { setDatabases(res.databases || []); }
    } catch (e: any) { setDbError(e.message); setDatabases([]); }
    setDbLoading(false);
  };

  // Load Docker info when server changes and type is docker_volumes
  const loadDocker = async () => {
    if (!form.server_id) return;
    setDockerLoading(true); setDockerError('');
    try {
      const res = await getServerDocker(form.server_id);
      if (res.error) { setDockerError(res.error); setDockerInfo(null); }
      else { setDockerInfo(res); }
    } catch (e: any) { setDockerError(e.message); setDockerInfo(null); }
    setDockerLoading(false);
  };

  // File browser
  const browseTo = async (path: string) => {
    if (!form.server_id) return;
    setBrowserLoading(true);
    try {
      const res = await browseServer(form.server_id, path);
      setBrowserPath(res.path || path);
      setBrowserEntries(res.entries || []);
    } catch { setBrowserEntries([]); }
    setBrowserLoading(false);
  };

  const openBrowser = () => { setShowBrowser(true); browseTo('/'); };
  const addPathFromBrowser = (entry: any) => {
    const fullPath = browserPath === '/' ? `/${entry.name}` : `${browserPath}/${entry.name}`;
    const current = form.source_paths.trim();
    const newPaths = current ? `${current}\n${fullPath}` : fullPath;
    setForm({ ...form, source_paths: newPaths });
  };

  const toggleDestination = (id: string) => {
    setForm(f => ({ ...f, destination_ids: f.destination_ids.includes(id) ? f.destination_ids.filter(d => d !== id) : [...f.destination_ids, id] }));
  };

  const toggleDbName = (name: string) => {
    setForm(f => ({ ...f, db_names: f.db_names.includes(name) ? f.db_names.filter(d => d !== name) : [...f.db_names, name] }));
  };

  const toggleVolume = (name: string) => {
    setForm(f => ({ ...f, volume_names: f.volume_names.includes(name) ? f.volume_names.filter(v => v !== name) : [...f.volume_names, name] }));
  };

  // ── Type-specific source config section ──
  const sourceConfigSection = (() => {
    if (!form.server_id) return null;

    switch (form.backup_type) {
      case 'files':
        return (
          <div className="bg-vm-surface2 border border-vm-border rounded p-4 mb-4">
            <div className="flex items-center gap-2 mb-3">
              <FolderOpen className="w-4 h-4 text-vm-accent" />
              <span className="font-mono text-[10px] text-vm-accent tracking-[2px] uppercase">// {t('jobs.source_config')}</span>
            </div>
            <FormLabel label={t('jobs.source_path')} tooltip={t('jobs.source_path_tip')} />
            <textarea value={form.source_paths} onChange={e => setForm({...form, source_paths: e.target.value})} className={INPUT + ' h-24 resize-y'} placeholder={t('jobs.source_path_placeholder')} />
            <button type="button" onClick={openBrowser} disabled={!form.server_id} className="mt-2 flex items-center gap-1.5 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08] disabled:opacity-50">
              <FolderOpen className="w-3.5 h-3.5" /> {t('jobs.browse_files')}
            </button>
            {showBrowser && (
              <div className="mt-3 bg-vm-surface border border-vm-border rounded p-3 max-h-64 overflow-y-auto">
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-mono text-[10px] text-vm-accent tracking-[2px] uppercase">{t('jobs.file_browser')}</span>
                  <span className="font-mono text-[11px] text-vm-text-dim flex-1 truncate">{browserPath}</span>
                  <button onClick={() => setShowBrowser(false)} className="text-vm-text-dim hover:text-vm-text"><X className="w-4 h-4" /></button>
                </div>
                {browserLoading ? (
                  <div className="flex items-center gap-2 py-4 justify-center text-vm-text-dim"><Loader2 className="w-4 h-4 animate-spin" /> {t('common.loading')}</div>
                ) : (
                  <div className="space-y-0.5">
                    {browserPath !== '/' && (
                      <button onClick={() => browseTo(browserPath.split('/').slice(0, -1).join('/') || '/')} className="w-full flex items-center gap-2 px-2 py-1 rounded hover:bg-vm-surface2 text-left">
                        <ArrowUp className="w-3.5 h-3.5 text-vm-text-dim" />
                        <span className="font-mono text-xs text-vm-text-dim">{t('jobs.parent_dir')}</span>
                      </button>
                    )}
                    {browserEntries.filter(e => !e.error).map((entry, i) => (
                      <div key={i} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-vm-surface2 group">
                        {entry.type === 'directory' ? (
                          <button onClick={() => browseTo(browserPath === '/' ? `/${entry.name}` : `${browserPath}/${entry.name}`)} className="flex items-center gap-2 flex-1 text-left">
                            <FolderOpen className="w-3.5 h-3.5 text-vm-accent" />
                            <span className="font-mono text-xs text-vm-text-bright">{entry.name}/</span>
                          </button>
                        ) : (
                          <div className="flex items-center gap-2 flex-1">
                            <span className="w-3.5 h-3.5" />
                            <span className="font-mono text-xs text-vm-text-dim">{entry.name}</span>
                            {entry.size != null && <span className="font-mono text-[10px] text-vm-text-dim ml-auto">{formatBytes(entry.size)}</span>}
                          </div>
                        )}
                        <button onClick={() => addPathFromBrowser(entry)} className="opacity-0 group-hover:opacity-100 px-2 py-0.5 text-[10px] font-bold text-vm-accent border border-vm-accent/40 rounded uppercase tracking-wider hover:bg-vm-accent/10">
                          + {t('action.add')}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );

      case 'postgresql': case 'mysql': case 'mariadb':
        return (
          <div className="bg-vm-surface2 border border-vm-border rounded p-4 mb-4">
            <div className="flex items-center gap-2 mb-3">
              <Database className="w-4 h-4 text-vm-accent" />
              <span className="font-mono text-[10px] text-vm-accent tracking-[2px] uppercase">// {t('jobs.source_config')}</span>
            </div>
            <FormLabel label={t('jobs.db_name')} tooltip={t('jobs.db_name_tip')} />
            {!selectedServer?.meta?.db_type ? (
              <div className="font-mono text-xs text-vm-warning p-2 bg-vm-warning/10 border border-vm-warning/30 rounded">{t('jobs.db_no_config')}</div>
            ) : (
              <>
                <div className="flex gap-2 mb-2">
                  <button type="button" onClick={loadDatabases} disabled={dbLoading} className="flex items-center gap-1.5 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08] disabled:opacity-50">
                    {dbLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                    {dbLoading ? t('jobs.db_loading') : t('action.run')}
                  </button>
                  {databases.length > 0 && (
                    <button type="button" onClick={() => setForm(f => ({ ...f, db_names: databases.map(d => d.name) }))} className="px-3 py-1.5 text-xs font-bold text-vm-text-dim tracking-wider uppercase hover:text-vm-accent">
                      {t('jobs.db_select_all')}
                    </button>
                  )}
                </div>
                {dbError && <div className="font-mono text-xs text-vm-danger p-2 bg-vm-danger/10 border border-vm-danger/30 rounded mb-2">{t('jobs.db_error')}: {dbError}</div>}
                {databases.length > 0 && (
                  <div className="grid grid-cols-2 gap-1.5">
                    {databases.map(db => (
                      <button key={db.name} type="button" onClick={() => toggleDbName(db.name)}
                        className={`flex items-center gap-2 px-3 py-2 rounded border font-mono text-[11px] transition-all text-left ${form.db_names.includes(db.name) ? 'bg-vm-accent/10 border-vm-accent text-vm-accent' : 'bg-vm-surface border-vm-border text-vm-text-dim hover:border-vm-accent/50'}`}>
                        <span className={`w-3 h-3 rounded-sm border flex-shrink-0 ${form.db_names.includes(db.name) ? 'bg-vm-accent border-vm-accent' : 'border-vm-border'}`}>
                          {form.db_names.includes(db.name) && <span className="block w-full h-full text-center text-[8px] text-vm-bg leading-3">✓</span>}
                        </span>
                        <span className="truncate">{db.name}</span>
                        {db.size_bytes > 0 && <span className="ml-auto text-[10px] text-vm-text-dim flex-shrink-0">{formatBytes(db.size_bytes)}</span>}
                      </button>
                    ))}
                  </div>
                )}
                {databases.length === 0 && !dbLoading && !dbError && (
                  <div className="font-mono text-xs text-vm-text-dim py-2">{t('jobs.db_loading')} — {t('action.run')}</div>
                )}
              </>
            )}
          </div>
        );

      case 'docker_volumes':
        return (
          <div className="bg-vm-surface2 border border-vm-border rounded p-4 mb-4">
            <div className="flex items-center gap-2 mb-3">
              <Container className="w-4 h-4 text-vm-accent" />
              <span className="font-mono text-[10px] text-vm-accent tracking-[2px] uppercase">// {t('jobs.source_config')}</span>
            </div>
            <div className="flex gap-2 mb-3">
              <button type="button" onClick={loadDocker} disabled={dockerLoading} className="flex items-center gap-1.5 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08] disabled:opacity-50">
                {dockerLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                {dockerLoading ? t('jobs.docker_loading') : t('action.run')}
              </button>
            </div>
            {dockerError && <div className="font-mono text-xs text-vm-danger p-2 bg-vm-danger/10 border border-vm-danger/30 rounded mb-2">{t('jobs.docker_error')}: {dockerError}</div>}
            {dockerInfo && (
              <>
                {/* Containers overview */}
                {dockerInfo.containers?.length > 0 && (
                  <div className="mb-3">
                    <div className="font-mono text-[10px] text-vm-text-dim tracking-[2px] uppercase mb-1.5">// {t('jobs.docker_containers')} ({dockerInfo.containers.length})</div>
                    <div className="space-y-1 max-h-32 overflow-y-auto">
                      {dockerInfo.containers.map((c: any) => (
                        <div key={c.id} className="flex items-center gap-2 px-2 py-1 bg-vm-surface rounded font-mono text-[11px]">
                          <div className={`w-2 h-2 rounded-full ${c.state === 'running' ? 'bg-vm-success' : 'bg-vm-text-dim'}`} />
                          <span className="text-vm-text-bright">{c.name}</span>
                          <span className="text-vm-text-dim truncate">{c.image}</span>
                          <span className="ml-auto text-[10px] text-vm-text-dim">{c.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {/* Volume selection */}
                {(() => {
                  const usedVols = (dockerInfo.volumes || []).filter((v: any) => v.used_by?.length > 0);
                  const orphanVols = (dockerInfo.volumes || []).filter((v: any) => !v.used_by?.length);
                  const sortedVols = [...usedVols, ...orphanVols];
                  return <>
                    <div className="flex items-center justify-between mb-1.5">
                      <FormLabel label={t('jobs.docker_volumes')} tooltip={t('jobs.docker_volumes_tip')} />
                      {orphanVols.length > 0 && (
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[10px] text-vm-warning">{orphanVols.length} {t('jobs.docker_orphan_volumes')}</span>
                          <button type="button" onClick={async () => {
                            if (!confirm(t('jobs.docker_prune_confirm'))) return;
                            try {
                              const res = await pruneDockerVolumes(form.server_id);
                              if (res.success) { alert(t('jobs.docker_prune_success') + '\n' + (res.output || '')); loadDocker(); }
                              else { alert(t('jobs.docker_prune_error') + ': ' + res.error); }
                            } catch (e: any) { alert(e.message); }
                          }} className="flex items-center gap-1 px-2 py-1 border border-vm-warning/50 text-vm-warning rounded text-[10px] font-bold tracking-wider uppercase hover:bg-vm-warning/10">
                            <Trash2 className="w-3 h-3" /> {t('jobs.docker_prune')}
                          </button>
                        </div>
                      )}
                    </div>
                    {sortedVols.length > 0 ? (
                      <div className="grid grid-cols-2 gap-1.5">
                        {sortedVols.map((v: any) => {
                          const isOrphan = !v.used_by?.length;
                          return (
                            <button key={v.name} type="button" onClick={() => toggleVolume(v.name)}
                              className={`flex flex-col gap-1 px-3 py-2 rounded border font-mono text-[11px] transition-all text-left ${form.volume_names.includes(v.name) ? 'bg-vm-accent/10 border-vm-accent text-vm-accent' : isOrphan ? 'bg-vm-surface border-vm-border/50 text-vm-text-dim/60 hover:border-vm-warning/50' : 'bg-vm-surface border-vm-border text-vm-text-dim hover:border-vm-accent/50'}`}>
                              <div className="flex items-center gap-2 w-full">
                                <span className={`w-3 h-3 rounded-sm border flex-shrink-0 ${form.volume_names.includes(v.name) ? 'bg-vm-accent border-vm-accent' : 'border-vm-border'}`}>
                                  {form.volume_names.includes(v.name) && <span className="block w-full h-full text-center text-[8px] text-vm-bg leading-3">✓</span>}
                                </span>
                                <span className="truncate">{v.name}</span>
                                {isOrphan && <span className="text-[9px] px-1 py-0.5 rounded bg-vm-warning/10 border border-vm-warning/30 text-vm-warning flex-shrink-0">{t('jobs.docker_orphan')}</span>}
                                <span className="ml-auto text-[10px] text-vm-text-dim flex-shrink-0">{v.driver}</span>
                              </div>
                              {v.used_by?.length > 0 && (
                                <div className="flex flex-wrap gap-1 ml-5">
                                  {v.used_by.map((c: string) => (
                                    <span key={c} className="text-[9px] px-1.5 py-0.5 rounded bg-vm-surface2 border border-vm-border text-vm-text-dim">↳ {c}</span>
                                  ))}
                                </div>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="font-mono text-xs text-vm-text-dim py-2">{t('jobs.docker_no_volumes')}</div>
                    )}
                  </>;
                })()}
              </>
            )}
          </div>
        );

      case 'custom':
        return (
          <div className="bg-vm-surface2 border border-vm-border rounded p-4 mb-4">
            <div className="flex items-center gap-2 mb-3">
              <Terminal className="w-4 h-4 text-vm-accent" />
              <span className="font-mono text-[10px] text-vm-accent tracking-[2px] uppercase">// {t('jobs.source_config')}</span>
            </div>
            <div className="grid grid-cols-2 gap-4 mb-3">
              <div>
                <FormLabel label={t('jobs.script_type')} tooltip={t('jobs.script_type_tip')} />
                <select value={form.script_type} onChange={e => setForm({...form, script_type: e.target.value})} className={INPUT}>
                  <option value="bash">🐚 Bash</option>
                  <option value="python">🐍 Python</option>
                  <option value="node">📦 Node.js</option>
                  <option value="ruby">💎 Ruby</option>
                  <option value="perl">🐪 Perl</option>
                </select>
              </div>
              <div>
                <FormLabel label={t('jobs.script_path')} tooltip={t('jobs.script_path_tip')} />
                <input value={form.script_path} onChange={e => setForm({...form, script_path: e.target.value})} className={INPUT} placeholder="/opt/scripts/backup.sh" />
              </div>
            </div>
            <div>
              <FormLabel label={t('jobs.script_inline')} tooltip={t('jobs.script_content_tip')} />
              <textarea value={form.script_content} onChange={e => setForm({...form, script_content: e.target.value})} className={INPUT + ' h-32 resize-y font-mono text-xs'} placeholder="#!/bin/bash&#10;# Your backup script here..." />
              <div className="font-mono text-[10px] text-vm-text-dim mt-1">{t('jobs.script_or_path')}</div>
            </div>
          </div>
        );

      default: return null;
    }
  })();

  // ── Job form JSX (as variable, not component, to avoid focus loss) ──
  const jobForm = (
    <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-bold text-vm-text-bright uppercase tracking-wider">{editId ? t('jobs.edit') : t('jobs.new')}</h3>
        <button onClick={closeForm} className="text-vm-text-dim hover:text-vm-text"><X className="w-5 h-5" /></button>
      </div>

      {/* Basic fields */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <FormLabel label={t('jobs.name')} tooltip={t('jobs.name_tip')} />
          <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} className={INPUT} />
        </div>
        <div>
          <FormLabel label={t('jobs.backup_type')} tooltip={t('jobs.backup_type_tip')} />
          <select value={form.backup_type} onChange={e => setForm({...form, backup_type: e.target.value})} className={INPUT}>
            <option value="files">📁 Files & Directories</option>
            <option value="postgresql">🐘 PostgreSQL</option>
            <option value="mysql">🐬 MySQL</option>
            <option value="mariadb">🦭 MariaDB</option>
            <option value="docker_volumes">🐳 Docker Volumes</option>
            <option value="custom">⚡ Custom Script</option>
          </select>
        </div>
        <div>
          <FormLabel label={t('jobs.server')} tooltip={t('jobs.server_tip')} />
          <select value={form.server_id} onChange={e => setForm({...form, server_id: e.target.value})} className={INPUT}>
            <option value="">{t('jobs.select_server')}</option>
            {servers.map((s: any) => (
              <option key={s.id} value={s.id}>{s.name} ({s.host}) {s.meta?.db_type ? `· ${s.meta.db_type}` : ''}</option>
            ))}
          </select>
        </div>
        <div>
          <FormLabel label={t('jobs.project')} tooltip={t('jobs.project_tip')} />
          <input value={form.domain} onChange={e => setForm({...form, domain: e.target.value})} className={INPUT} placeholder="myproject.com" />
        </div>
        <div className="col-span-2">
          <FormLabel label={t('jobs.schedule')} tooltip={t('jobs.schedule_tip')} />
          <CronBuilder value={form.schedule_cron} onChange={cron => setForm({...form, schedule_cron: cron})} />
        </div>
      </div>

      {/* Type-specific source config */}
      {sourceConfigSection}

      {/* Storage destination picker */}
      <div className="bg-vm-surface2 border border-vm-border rounded p-4 mb-4">
        <div className="flex items-center gap-2 mb-3">
          <HardDrive className="w-4 h-4 text-vm-accent" />
          <span className="font-mono text-[10px] text-vm-accent tracking-[2px] uppercase">// {t('jobs.storage_dest')}</span>
        </div>
        <FormLabel label={t('jobs.storage_dest')} tooltip={t('jobs.storage_dest_tip')} />
        {storageDests.length > 0 ? (
          <div className="grid grid-cols-2 gap-1.5 mb-3">
            {storageDests.map(d => (
              <button key={d.id} type="button" onClick={() => toggleDestination(d.id)}
                className={`flex items-center gap-2 px-3 py-2 rounded border font-mono text-[11px] transition-all text-left ${form.destination_ids.includes(d.id) ? 'bg-vm-accent/10 border-vm-accent text-vm-accent' : 'bg-vm-surface border-vm-border text-vm-text-dim hover:border-vm-accent/50'}`}>
                <span className={`w-3 h-3 rounded-sm border flex-shrink-0 ${form.destination_ids.includes(d.id) ? 'bg-vm-accent border-vm-accent' : 'border-vm-border'}`}>
                  {form.destination_ids.includes(d.id) && <span className="block w-full h-full text-center text-[8px] text-vm-bg leading-3">✓</span>}
                </span>
                <span className="truncate">{d.name}</span>
                <span className="ml-auto text-[10px] text-vm-text-dim">{d.backend}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="font-mono text-xs text-vm-text-dim py-2">{t('jobs.storage_none')}</div>
        )}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <FormLabel label={t('jobs.storage_subdir')} tooltip={t('jobs.storage_subdir_tip')} />
            <input value={form.storage_subdir} onChange={e => setForm({...form, storage_subdir: e.target.value})} className={INPUT} placeholder="auto" />
          </div>
          <div>
            <FormLabel label={t('jobs.retention')} tooltip={t('jobs.retention_tip')} />
            <select value={form.retention_id} onChange={e => setForm({...form, retention_id: e.target.value})} className={INPUT}>
              <option value="">{t('jobs.retention_none')}</option>
              {retentionPolicies.map((p: any) => (
                <option key={p.id} value={p.id}>{p.name} (D{p.keep_daily}/W{p.keep_weekly}/M{p.keep_monthly})</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Tags & Encrypt */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="col-span-2">
          <FormLabel label={t('jobs.tags')} tooltip={t('jobs.tags_tip')} />
          <TagInput value={form.tags} onChange={tags => setForm({...form, tags})} suggestions={allTags} placeholder="critical, daily, production" />
        </div>
        <div className="col-span-2 flex items-center gap-3">
          <button type="button" onClick={() => setForm({...form, encrypt: !form.encrypt})}
            className={`flex items-center gap-2 px-4 py-2 rounded border text-sm font-bold tracking-wider uppercase transition-all ${form.encrypt ? 'bg-vm-accent/10 border-vm-accent text-vm-accent' : 'bg-vm-surface2 border-vm-border text-vm-text-dim hover:border-vm-accent'}`}>
            <Lock className="w-4 h-4" />
            {form.encrypt ? t('jobs.encrypt_on') : t('jobs.encrypt')}
          </button>
          <span className="font-mono text-[10px] text-vm-text-dim">{t('jobs.encrypt_desc')}</span>
        </div>
      </div>

      {/* Advanced section (collapsible) */}
      <button type="button" onClick={() => setShowAdvanced(!showAdvanced)} className="flex items-center gap-2 mb-3 text-vm-text-dim hover:text-vm-accent transition-colors">
        {showAdvanced ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        <span className="font-mono text-[10px] tracking-[2px] uppercase">{t('jobs.advanced')}</span>
      </button>
      {showAdvanced && (
        <div className="bg-vm-surface2 border border-vm-border rounded p-4 mb-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <FormLabel label={t('jobs.pre_script')} tooltip={t('jobs.pre_script_tip')} />
              <input value={form.pre_script} onChange={e => setForm({...form, pre_script: e.target.value})} className={INPUT} placeholder="systemctl stop myapp" />
            </div>
            <div>
              <FormLabel label={t('jobs.post_script')} tooltip={t('jobs.post_script_tip')} />
              <input value={form.post_script} onChange={e => setForm({...form, post_script: e.target.value})} className={INPUT} placeholder="systemctl start myapp" />
            </div>
            <div>
              <FormLabel label={t('jobs.max_retries')} tooltip={t('jobs.max_retries_tip')} />
              <input type="number" min="0" max="10" value={form.max_retries} onChange={e => setForm({...form, max_retries: Number(e.target.value)})} className={INPUT} />
            </div>
          </div>
        </div>
      )}

      <div className="flex gap-3">
        <button onClick={handleSave} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">{editId ? t('action.update') : t('action.save')}</button>
        <button onClick={closeForm} className="px-4 py-2.5 text-vm-text-dim font-bold text-sm tracking-wider uppercase hover:text-vm-text">{t('action.cancel')}</button>
      </div>
    </div>
  );

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">{t('jobs.title')}</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">{t('jobs.subtitle_prefix')} {jobs.length} {t('common.total')}</div>
        </div>
        <button onClick={openNew} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase hover:bg-[#33ddff] transition-all glow">
          <Plus className="w-4 h-4" /> {t('jobs.new')}
        </button>
      </div>

      {showForm && jobForm}

      <div className="bg-vm-surface border border-vm-border rounded overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-vm-surface2 border-b border-vm-border">
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('jobs.type')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('jobs.name')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('jobs.schedule')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('jobs.project_col')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('jobs.status')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal"></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j: any) => (
              <tr key={j.id} className="border-b border-vm-border/50 hover:bg-vm-surface2 transition-colors">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2 font-semibold">
                    <span className="text-lg">{backupTypeIcon(j.backup_type)}</span>
                    {j.backup_type}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="text-sm font-semibold text-vm-text-bright">{j.name}</div>
                  {j.tags?.length > 0 && (
                    <div className="flex gap-1 mt-1">
                      {j.tags.map((tag: string) => (
                        <span key={tag} className="font-mono text-[9px] px-1.5 py-0.5 rounded-sm border border-vm-accent/30 bg-vm-accent/[0.06] text-vm-accent uppercase tracking-wider">{tag}</span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-vm-text-dim"><Clock className="w-3 h-3 inline mr-1" />{j.schedule_cron}</td>
                <td className="px-4 py-3 font-mono text-xs text-vm-accent">{j.domain || '—'}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1.5">
                    <Badge status={j.is_active ? 'success' : 'cancelled'} label={j.is_active ? t('jobs.active') : t('jobs.inactive')} />
                    {j.encrypt && <Lock className="w-3 h-3 text-vm-accent" />}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button onClick={() => openEdit(j)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08]"><Pencil className="w-3 h-3" /> {t('action.edit')}</button>
                    <button onClick={() => handleTrigger(j.id)} className="flex items-center gap-1 px-3 py-1.5 bg-vm-accent text-vm-bg rounded text-xs font-bold tracking-wider uppercase"><Play className="w-3 h-3" /> {t('action.run')}</button>
                    <button onClick={() => handleDelete(j.id)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10"><Trash2 className="w-3 h-3" /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {jobs.length === 0 && (
          <div className="text-center py-12 text-vm-text-dim font-mono tracking-[2px]">{t('jobs.none')}</div>
        )}
      </div>
    </div>
  );
}
