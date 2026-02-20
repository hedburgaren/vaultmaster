'use client';

import { useEffect, useState, useMemo } from 'react';
import { getJobs, createJob, updateJob, deleteJob, triggerJob, getServers } from '@/lib/api';
import { backupTypeIcon } from '@/lib/utils';
import { useT } from '@/lib/i18n';
import Badge from '@/components/Badge';
import FormLabel from '@/components/FormLabel';
import TagInput from '@/components/TagInput';
import CronBuilder from '@/components/CronBuilder';
import { Plus, Play, Trash2, Clock, Lock, Pencil, X } from 'lucide-react';

const INPUT = "w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent";

const emptyForm = { name: '', backup_type: 'postgresql', server_id: '', schedule_cron: '0 3 * * *', domain: '', tags: [] as string[], encrypt: false };

export default function JobsPage() {
  const t = useT();
  const [jobs, setJobs] = useState<any[]>([]);
  const [servers, setServers] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState({ ...emptyForm });

  const load = () => { getJobs().then(setJobs).catch(() => {}); getServers().then(setServers).catch(() => {}); };
  useEffect(() => { load(); }, []);

  const allTags = useMemo(() => {
    const set = new Set<string>();
    jobs.forEach(j => j.tags?.forEach((t: string) => set.add(t)));
    return Array.from(set).sort();
  }, [jobs]);

  const openNew = () => { setEditId(null); setForm({ ...emptyForm }); setShowForm(true); };
  const openEdit = (j: any) => {
    setEditId(j.id);
    setForm({ name: j.name, backup_type: j.backup_type, server_id: j.server_id || '', schedule_cron: j.schedule_cron || '0 3 * * *', domain: j.domain || '', tags: j.tags || [], encrypt: j.encrypt || false });
    setShowForm(true);
  };
  const closeForm = () => { setShowForm(false); setEditId(null); };

  const handleSave = async () => {
    if (editId) {
      await updateJob(editId, { ...form, source_config: {} });
    } else {
      await createJob({ ...form, source_config: {} });
    }
    closeForm();
    load();
  };

  const handleTrigger = async (id: string) => {
    await triggerJob(id);
    alert(t('jobs.backup_queued'));
  };

  const handleDelete = async (id: string) => {
    if (confirm(t('jobs.confirm_delete'))) { await deleteJob(id); load(); }
  };

  const jobForm = (
    <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-bold text-vm-text-bright uppercase tracking-wider">{editId ? t('jobs.edit') : t('jobs.new')}</h3>
        <button onClick={closeForm} className="text-vm-text-dim hover:text-vm-text"><X className="w-5 h-5" /></button>
      </div>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <FormLabel label={t('jobs.name')} tooltip={t('jobs.name_tip')} />
          <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} className={INPUT} />
        </div>
        <div>
          <FormLabel label={t('jobs.backup_type')} tooltip={t('jobs.backup_type_tip')} />
          <select value={form.backup_type} onChange={e => setForm({...form, backup_type: e.target.value})} className={INPUT}>
            <option value="postgresql">🐘 PostgreSQL Database</option>
            <option value="docker_volumes">🐳 Docker Volumes</option>
            <option value="files">📁 Files & Directories</option>
            <option value="do_snapshot">📸 DigitalOcean Snapshot</option>
            <option value="custom">⚡ Custom Script</option>
          </select>
        </div>
        <div>
          <FormLabel label={t('jobs.server')} tooltip={t('jobs.server_tip')} />
          <select value={form.server_id} onChange={e => setForm({...form, server_id: e.target.value})} className={INPUT}>
            <option value="">{t('jobs.select_server')}</option>
            {servers.map((s: any) => <option key={s.id} value={s.id}>{s.name} ({s.host})</option>)}
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
