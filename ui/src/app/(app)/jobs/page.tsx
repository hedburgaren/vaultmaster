'use client';

import { useEffect, useState } from 'react';
import { getJobs, createJob, deleteJob, triggerJob, getServers } from '@/lib/api';
import { backupTypeIcon } from '@/lib/utils';
import Badge from '@/components/Badge';
import { Plus, Play, Trash2, Clock } from 'lucide-react';

export default function JobsPage() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [servers, setServers] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', backup_type: 'postgresql', server_id: '', schedule_cron: '0 3 * * *', domain: '', tags: '', encrypt: false });

  const load = () => { getJobs().then(setJobs).catch(() => {}); getServers().then(setServers).catch(() => {}); };
  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    await createJob({ ...form, tags: form.tags ? form.tags.split(',').map((t: string) => t.trim()) : [], source_config: {} });
    setShowForm(false);
    load();
  };

  const handleTrigger = async (id: string) => {
    await triggerJob(id);
    alert('Backup queued!');
  };

  const handleDelete = async (id: string) => {
    if (confirm('Delete this job?')) { await deleteJob(id); load(); }
  };

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">Backup Jobs</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">// SCHEDULED JOBS · {jobs.length} TOTAL</div>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase hover:bg-[#33ddff] transition-all glow">
          <Plus className="w-4 h-4" /> New Job
        </button>
      </div>

      {showForm && (
        <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
          <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider">New Backup Job</h3>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Name</label>
              <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Type</label>
              <select value={form.backup_type} onChange={e => setForm({...form, backup_type: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent">
                <option value="postgresql">PostgreSQL</option>
                <option value="docker_volumes">Docker Volumes</option>
                <option value="files">Files</option>
                <option value="do_snapshot">DO Snapshot</option>
                <option value="custom">Custom Script</option>
              </select>
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Server</label>
              <select value={form.server_id} onChange={e => setForm({...form, server_id: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent">
                <option value="">Select server...</option>
                {servers.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Schedule (cron)</label>
              <input value={form.schedule_cron} onChange={e => setForm({...form, schedule_cron: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder="0 3 * * *" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Domain</label>
              <input value={form.domain} onChange={e => setForm({...form, domain: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder="plastshop" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Tags</label>
              <input value={form.tags} onChange={e => setForm({...form, tags: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder="critical, daily" />
            </div>
          </div>
          <button onClick={handleCreate} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">Save</button>
        </div>
      )}

      <div className="bg-vm-surface border border-vm-border rounded overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-vm-surface2 border-b border-vm-border">
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Type</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Name</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Schedule</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Domain</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Status</th>
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
                <td className="px-4 py-3 text-sm font-semibold text-vm-text-bright">{j.name}</td>
                <td className="px-4 py-3 font-mono text-xs text-vm-text-dim"><Clock className="w-3 h-3 inline mr-1" />{j.schedule_cron}</td>
                <td className="px-4 py-3 font-mono text-xs text-vm-accent">{j.domain || '—'}</td>
                <td className="px-4 py-3"><Badge status={j.is_active ? 'success' : 'cancelled'} label={j.is_active ? 'ACTIVE' : 'INACTIVE'} /></td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button onClick={() => handleTrigger(j.id)} className="flex items-center gap-1 px-3 py-1.5 bg-vm-accent text-vm-bg rounded text-xs font-bold tracking-wider uppercase"><Play className="w-3 h-3" /> Run</button>
                    <button onClick={() => handleDelete(j.id)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10"><Trash2 className="w-3 h-3" /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {jobs.length === 0 && (
          <div className="text-center py-12 text-vm-text-dim font-mono tracking-[2px]">No backup jobs configured</div>
        )}
      </div>
    </div>
  );
}
