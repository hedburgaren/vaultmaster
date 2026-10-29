'use client';

import { useEffect, useState } from 'react';
import { getArtifacts, restoreArtifact, verifyArtifact, getServers } from '@/lib/api';
import { formatBytes, formatDate, formatRelative, backupTypeIcon } from '@/lib/utils';
import Badge from '@/components/Badge';
import { RotateCcw, ShieldCheck, Search, Lock, Calendar, Server, Globe, Tag, HardDrive, X, AlertTriangle } from 'lucide-react';
import { useT } from '@/lib/i18n';
import { useToast } from '@/components/Toast';
import { ConfirmModal } from '@/components/ConfirmModal';

const INPUT = "w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2 text-vm-text font-mono text-sm outline-none focus:border-vm-accent";
const LABEL = "block font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim mb-1";

export default function ArtifactsPage() {
  const t = useT();
  const toast = useToast();
  const [artifacts, setArtifacts] = useState<any[]>([]);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [restoreFor, setRestoreFor] = useState<any | null>(null);
  const [servers, setServers] = useState<any[]>([]);

  const load = () => {
    const params = new URLSearchParams();
    if (search) params.set('q', search);
    if (typeFilter) params.set('backup_type', typeFilter);
    getArtifacts(params.toString()).then(setArtifacts).catch(() => {});
  };

  useEffect(() => { load(); }, [search, typeFilter]);
  useEffect(() => { getServers().then(setServers).catch(() => {}); }, []);

  const handleVerify = async (id: string) => {
    try {
      const res = await verifyArtifact(id);
      toast.success(`${t('artifacts.verify_queued')}: ${String(res.task_id).slice(0, 8)}…`);
    } catch (e: any) {
      toast.error(e.message || 'Verify failed');
    }
  };

  const sel = artifacts.find(a => a.id === selected);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">{t('artifacts.title')}</h1>
        <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">{t('artifacts.subtitle_prefix')} {artifacts.length} {t('artifacts.found')} · {t('artifacts.search_restore')}</div>
      </div>

      <div className="flex gap-4 mb-6">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-vm-text-dim" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder={t('artifacts.search_placeholder')} className="w-full bg-vm-surface border border-vm-border rounded pl-10 pr-4 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
        </div>
        <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} className="bg-vm-surface border border-vm-border rounded px-4 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent">
          <option value="">{t('common.all_types')}</option>
          <option value="postgresql">🐘 PostgreSQL</option>
          <option value="docker_volumes">🐳 Docker</option>
          <option value="files">📁 Files</option>
          <option value="do_snapshot">📸 Snapshot</option>
          <option value="custom">⚡ Custom</option>
        </select>
      </div>

      <div className="flex gap-4">
        {/* Artifact list */}
        <div className={`${selected ? 'w-3/5' : 'w-full'} transition-all`}>
          <div className="bg-vm-surface border border-vm-border rounded overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-vm-surface2 border-b border-vm-border">
                  <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('artifacts.type')}</th>
                  <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('artifacts.backup')}</th>
                  <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('artifacts.server')}</th>
                  <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('artifacts.date')}</th>
                  <th className="px-4 py-3 text-right font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('artifacts.size')}</th>
                  <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal"></th>
                </tr>
              </thead>
              <tbody>
                {artifacts.map((a: any) => (
                  <tr
                    key={a.id}
                    onClick={() => setSelected(selected === a.id ? null : a.id)}
                    className={`border-b border-vm-border/50 hover:bg-vm-surface2 transition-colors cursor-pointer ${selected === a.id ? 'bg-vm-accent/[0.05] border-l-2 border-l-vm-accent' : ''}`}
                  >
                    <td className="px-4 py-3">
                      <span className="text-lg">{backupTypeIcon(a.backup_type)}</span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-sm font-semibold text-vm-text-bright truncate max-w-[200px]">{a.filename}</div>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        {a.domain && <span className="font-mono text-[10px] px-1.5 py-0.5 rounded-sm bg-vm-accent/[0.08] text-vm-accent border border-vm-accent/20">{a.domain}</span>}
                        {a.is_encrypted && <Lock className="w-3 h-3 text-vm-accent" />}
                        {a.tags?.map((t: string) => (
                          <span key={t} className="font-mono text-[9px] px-1.5 py-0.5 rounded-sm bg-vm-surface3 text-vm-text-dim border border-vm-border">{t}</span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-vm-text-dim">{a.server_name || '—'}</td>
                    <td className="px-4 py-3 font-mono text-xs text-vm-text-dim">{formatRelative(a.created_at)}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm font-bold text-vm-accent">{formatBytes(a.size_bytes)}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1.5">
                        <button onClick={(e) => { e.stopPropagation(); setRestoreFor(a); }} className="flex items-center gap-1 px-2.5 py-1 bg-vm-success text-vm-bg rounded text-[10px] font-bold tracking-wider uppercase">
                          <RotateCcw className="w-3 h-3" /> {t('action.restore')}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {artifacts.length === 0 && (
              <div className="text-center py-12 text-vm-text-dim font-mono">
                <RotateCcw className="w-12 h-12 mx-auto mb-3 opacity-40" />
                <div className="tracking-[2px]">{t('artifacts.none')}</div>
                <div className="text-[11px] mt-1">{t('artifacts.none_desc')}</div>
              </div>
            )}
          </div>
        </div>

        {/* Detail panel */}
        {sel && (
          <div className="w-2/5 bg-vm-surface border border-vm-border rounded p-5 self-start sticky top-[76px]">
            <div className="flex items-center gap-2 mb-4">
              <span className="text-2xl">{backupTypeIcon(sel.backup_type)}</span>
              <div>
                <div className="text-lg font-bold text-vm-text-bright">{t('artifacts.details')}</div>
                <div className="font-mono text-[10px] text-vm-accent tracking-[2px] uppercase">{sel.backup_type}</div>
              </div>
            </div>

            <div className="space-y-3 mb-5">
              <div className="flex items-center gap-2 text-sm">
                <HardDrive className="w-4 h-4 text-vm-text-dim shrink-0" />
                <span className="text-vm-text-dim">{t('artifacts.filename')}:</span>
                <span className="font-mono text-vm-text-bright truncate">{sel.filename}</span>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <Server className="w-4 h-4 text-vm-text-dim shrink-0" />
                <span className="text-vm-text-dim">{t('artifacts.server')}:</span>
                <span className="text-vm-text-bright">{sel.server_name || '—'}</span>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <Globe className="w-4 h-4 text-vm-text-dim shrink-0" />
                <span className="text-vm-text-dim">{t('artifacts.project')}:</span>
                <span className="text-vm-accent">{sel.domain || '—'}</span>
              </div>
              {sel.db_name && (
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-lg">🐘</span>
                  <span className="text-vm-text-dim">{t('artifacts.database')}:</span>
                  <span className="text-vm-text-bright">{sel.db_name}</span>
                </div>
              )}
              <div className="flex items-center gap-2 text-sm">
                <Calendar className="w-4 h-4 text-vm-text-dim shrink-0" />
                <span className="text-vm-text-dim">{t('artifacts.created')}:</span>
                <span className="text-vm-text-bright">{formatDate(sel.created_at)}</span>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <HardDrive className="w-4 h-4 text-vm-text-dim shrink-0" />
                <span className="text-vm-text-dim">{t('artifacts.size')}:</span>
                <span className="font-bold text-vm-accent">{formatBytes(sel.size_bytes)}</span>
              </div>
              {sel.is_encrypted && (
                <div className="flex items-center gap-2 text-sm">
                  <Lock className="w-4 h-4 text-vm-accent shrink-0" />
                  <span className="text-vm-accent font-semibold">{t('artifacts.encrypted')}</span>
                </div>
              )}
              {sel.tags?.length > 0 && (
                <div className="flex items-center gap-2 text-sm flex-wrap">
                  <Tag className="w-4 h-4 text-vm-text-dim shrink-0" />
                  {sel.tags.map((t: string) => (
                    <span key={t} className="font-mono text-[10px] px-2 py-0.5 rounded-sm border border-vm-accent/30 bg-vm-accent/[0.06] text-vm-accent uppercase tracking-wider">{t}</span>
                  ))}
                </div>
              )}
              {sel.expires_at && (
                <div className="flex items-center gap-2 text-sm">
                  <Calendar className="w-4 h-4 text-vm-warning shrink-0" />
                  <span className="text-vm-warning">{t('artifacts.expires')}: {formatDate(sel.expires_at)}</span>
                </div>
              )}
            </div>

            <div className="font-mono text-[10px] text-vm-text-dim mb-3 break-all">
              SHA-256: {sel.checksum_sha256 || '—'}
            </div>

            <div className="flex gap-2">
              <button onClick={() => setRestoreFor(sel)} className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-vm-success text-vm-bg rounded font-bold text-sm tracking-wider uppercase">
                <RotateCcw className="w-4 h-4" /> {t('action.restore')}
              </button>
              <button onClick={() => handleVerify(sel.id)} className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 border border-vm-accent text-vm-accent rounded font-bold text-sm tracking-wider uppercase hover:bg-vm-accent/[0.08]">
                <ShieldCheck className="w-4 h-4" /> {t('action.verify')}
              </button>
            </div>
          </div>
        )}
      </div>

      {restoreFor && (
        <RestoreModal
          artifact={restoreFor}
          servers={servers}
          onClose={() => setRestoreFor(null)}
        />
      )}
    </div>
  );
}

function RestoreModal({ artifact, servers, onClose }: { artifact: any; servers: any[]; onClose: () => void }) {
  const t = useT();
  const toast = useToast();
  const [serverId, setServerId] = useState('');
  const [dbName, setDbName] = useState('');
  const [targetPath, setTargetPath] = useState('');
  const [overwrite, setOverwrite] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const bt = artifact.backup_type;

  const submit = async () => {
    if (!serverId) { toast.warning(t('restore.need_server')); return; }
    if (bt === 'postgresql' && !dbName.trim()) { toast.warning(t('restore.need_db')); return; }
    if (bt === 'files' && !targetPath.trim().startsWith('/')) { toast.warning(t('restore.need_path')); return; }
    setSubmitting(true);
    try {
      const res = await restoreArtifact(artifact.id, {
        target_server_id: serverId,
        target_db_name: dbName.trim() || null,
        target_path: targetPath.trim() || null,
        confirm_overwrite: overwrite,
      });
      toast.success(`${t('artifacts.restore_queued')}: ${String(res.task_id).slice(0, 8)}…`);
      onClose();
    } catch (e: any) {
      toast.error(e.message || 'Restore failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-vm-surface2 border border-vm-border-bright rounded shadow-2xl w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-vm-border flex items-center justify-between">
          <span className="font-mono text-xs uppercase tracking-[2px] text-vm-text-bright truncate">{t('restore.title')}: {artifact.filename}</span>
          <button onClick={onClose} className="text-vm-text-dim hover:text-vm-text-bright"><X className="w-4 h-4" /></button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <div>
            <label className={LABEL}>{t('restore.target_server')}</label>
            <select value={serverId} onChange={(e) => setServerId(e.target.value)} className={INPUT}>
              <option value="">…</option>
              {servers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>

          {bt === 'postgresql' && (
            <div>
              <label className={LABEL}>{t('restore.db_name')}</label>
              <input value={dbName} onChange={(e) => setDbName(e.target.value)} className={INPUT} placeholder="t.ex. produktdb_restore" />
              <div className="font-mono text-[10px] text-vm-danger mt-1">{t('restore.db_warning')}</div>
            </div>
          )}

          {bt === 'files' && (
            <div>
              <label className={LABEL}>{t('restore.path')}</label>
              <input value={targetPath} onChange={(e) => setTargetPath(e.target.value)} className={INPUT} placeholder="/restore/artifact-xy" />
              <div className="font-mono text-[10px] text-vm-text-dim mt-1">{t('restore.path_hint')}</div>
            </div>
          )}

          {bt === 'docker_volumes' && (
            <>
              <div>
                <label className={LABEL}>{t('restore.path_optional')}</label>
                <input value={targetPath} onChange={(e) => setTargetPath(e.target.value)} className={INPUT} placeholder="/var/lib/docker/volumes" />
                <div className="font-mono text-[10px] text-vm-text-dim mt-1">{t('restore.volumes_hint')}</div>
              </div>
              <label className="flex items-start gap-2 cursor-pointer">
                <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} className="mt-0.5 accent-[var(--vm-danger)]" />
                <span className="font-mono text-[10px] text-vm-danger">{t('restore.overwrite_volumes')}</span>
              </label>
            </>
          )}

          <div className="flex items-start gap-2 p-2.5 bg-vm-warning/10 border border-vm-warning/30 rounded">
            <AlertTriangle className="w-4 h-4 text-vm-warning shrink-0 mt-0.5" />
            <div className="font-mono text-[11px] text-vm-warning">{t('restore.overwrite_warning')}</div>
          </div>
        </div>
        <div className="px-5 py-3 border-t border-vm-border flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase">{t('cred.cancel')}</button>
          <button onClick={submit} disabled={submitting} className="px-3 py-1.5 bg-vm-success text-vm-bg rounded text-xs font-bold tracking-wider uppercase disabled:opacity-50">
            {submitting ? '…' : t('action.restore')}
          </button>
        </div>
      </div>
    </div>
  );
}
