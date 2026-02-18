'use client';

import { useEffect, useState, useMemo } from 'react';
import { getJobs, createJob, deleteJob, triggerJob, getServers } from '@/lib/api';
import { backupTypeIcon } from '@/lib/utils';
import Badge from '@/components/Badge';
import FormLabel from '@/components/FormLabel';
import TagInput from '@/components/TagInput';
import CronBuilder from '@/components/CronBuilder';
import { Plus, Play, Trash2, Clock, Lock } from 'lucide-react';

const INPUT = "w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent";

export default function JobsPage() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [servers, setServers] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', backup_type: 'postgresql', server_id: '', schedule_cron: '0 3 * * *', domain: '', tags: [] as string[], encrypt: false });

  const load = () => { getJobs().then(setJobs).catch(() => {}); getServers().then(setServers).catch(() => {}); };
  useEffect(() => { load(); }, []);

  const allTags = useMemo(() => {
    const set = new Set<string>();
    jobs.forEach(j => j.tags?.forEach((t: string) => set.add(t)));
    return Array.from(set).sort();
  }, [jobs]);

  const handleCreate = async () => {
    await createJob({ ...form, tags: form.tags, source_config: {} });
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
              <FormLabel label="Name" tooltip="A descriptive name for this backup job, e.g. 'Nightly PostgreSQL' or 'Weekly Files'." />
              <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} className={INPUT} />
            </div>
            <div>
              <FormLabel label="Backup Type" tooltip="What kind of data to back up. Each type uses a specialized strategy." />
              <select value={form.backup_type} onChange={e => setForm({...form, backup_type: e.target.value})} className={INPUT}>
                <option value="postgresql">🐘 PostgreSQL Database</option>
                <option value="docker_volumes">🐳 Docker Volumes</option>
                <option value="files">📁 Files & Directories</option>
                <option value="do_snapshot">📸 DigitalOcean Snapshot</option>
                <option value="custom">⚡ Custom Script</option>
              </select>
            </div>
            <div>
              <FormLabel label="Server" tooltip="Which server to run this backup on. Add servers in the Servers page first." />
              <select value={form.server_id} onChange={e => setForm({...form, server_id: e.target.value})} className={INPUT}>
                <option value="">Select server...</option>
                {servers.map((s: any) => <option key={s.id} value={s.id}>{s.name} ({s.host})</option>)}
              </select>
            </div>
            <div>
              <FormLabel label="Project / Domain" tooltip="Group backups by project or domain name. Useful for filtering and organizing artifacts. Example: 'plastshop.se', 'myapp-prod'." />
              <input value={form.domain} onChange={e => setForm({...form, domain: e.target.value})} className={INPUT} placeholder="myproject.com" />
            </div>
            <div className="col-span-2">
              <FormLabel label="Schedule" tooltip="When this backup should run automatically. Choose a preset or write a custom cron expression." />
              <CronBuilder value={form.schedule_cron} onChange={cron => setForm({...form, schedule_cron: cron})} />
            </div>
            <div className="col-span-2">
              <FormLabel label="Tags" tooltip="Categorize this job with tags. Press Enter or comma to add. Useful for filtering and retention policies." />
              <TagInput value={form.tags} onChange={tags => setForm({...form, tags})} suggestions={allTags} placeholder="critical, daily, production" />
            </div>
            <div className="col-span-2 flex items-center gap-3">
              <button
                type="button"
                onClick={() => setForm({...form, encrypt: !form.encrypt})}
                className={`flex items-center gap-2 px-4 py-2 rounded border text-sm font-bold tracking-wider uppercase transition-all ${form.encrypt ? 'bg-vm-accent/10 border-vm-accent text-vm-accent' : 'bg-vm-surface2 border-vm-border text-vm-text-dim hover:border-vm-accent'}`}
              >
                <Lock className="w-4 h-4" />
                {form.encrypt ? 'Encryption ON' : 'Encrypt backup'}
              </button>
              <span className="font-mono text-[10px] text-vm-text-dim">Encrypts backup files using age (AES-256). Requires AGE_PUBLIC_KEY in .env.</span>
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
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Project</th>
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
                <td className="px-4 py-3">
                  <div className="text-sm font-semibold text-vm-text-bright">{j.name}</div>
                  {j.tags?.length > 0 && (
                    <div className="flex gap-1 mt-1">
                      {j.tags.map((t: string) => (
                        <span key={t} className="font-mono text-[9px] px-1.5 py-0.5 rounded-sm border border-vm-accent/30 bg-vm-accent/[0.06] text-vm-accent uppercase tracking-wider">{t}</span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-vm-text-dim"><Clock className="w-3 h-3 inline mr-1" />{j.schedule_cron}</td>
                <td className="px-4 py-3 font-mono text-xs text-vm-accent">{j.domain || '—'}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1.5">
                    <Badge status={j.is_active ? 'success' : 'cancelled'} label={j.is_active ? 'ACTIVE' : 'INACTIVE'} />
                    {j.encrypt && <Lock className="w-3 h-3 text-vm-accent" />}
                  </div>
                </td>
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
