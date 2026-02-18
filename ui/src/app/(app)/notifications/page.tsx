'use client';

import { useEffect, useState } from 'react';
import { getNotificationChannels, createNotificationChannel, deleteNotificationChannel, testNotificationChannel } from '@/lib/api';
import { Plus, Trash2, TestTube, Bell, Send } from 'lucide-react';

export default function NotificationsPage() {
  const [channels, setChannels] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', channel_type: 'slack', config: '{}', triggers: 'run.success,run.failed' });
  const [testResults, setTestResults] = useState<Record<string, any>>({});

  const load = () => getNotificationChannels().then(setChannels).catch(() => {});
  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    await createNotificationChannel({ ...form, config: JSON.parse(form.config || '{}'), triggers: form.triggers.split(',').map((t: string) => t.trim()) });
    setShowForm(false); load();
  };

  const handleTest = async (id: string) => {
    const res = await testNotificationChannel(id);
    setTestResults((p: any) => ({ ...p, [id]: res }));
  };

  const typeLabel: Record<string, string> = { slack: 'Slack', ntfy: 'ntfy', telegram: 'Telegram', email: 'Email', webhook: 'Webhook' };

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">Notifications</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">// NOTIFICATION CHANNELS · {channels.length} TOTAL</div>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase hover:bg-[#33ddff] transition-all glow">
          <Plus className="w-4 h-4" /> New Channel
        </button>
      </div>

      {showForm && (
        <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Name</label>
              <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Type</label>
              <select value={form.channel_type} onChange={e => setForm({...form, channel_type: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent">
                <option value="slack">Slack</option>
                <option value="ntfy">ntfy</option>
                <option value="telegram">Telegram</option>
                <option value="email">Email</option>
                <option value="webhook">Webhook</option>
              </select>
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Config (JSON)</label>
              <input value={form.config} onChange={e => setForm({...form, config: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder='{"webhook_url": "..."}' />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Triggers (comma-separated)</label>
              <input value={form.triggers} onChange={e => setForm({...form, triggers: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
            </div>
          </div>
          <button onClick={handleCreate} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">Save</button>
        </div>
      )}

      <div className="space-y-3">
        {channels.map((c: any) => (
          <div key={c.id} className="bg-vm-surface border border-vm-border rounded p-5 flex items-center gap-4 hover:border-vm-border-bright transition-all">
            <div className="w-10 h-10 rounded bg-vm-accent/10 flex items-center justify-center text-vm-accent"><Send className="w-5 h-5" /></div>
            <div className="flex-1">
              <div className="font-semibold text-vm-text-bright">{c.name}</div>
              <div className="font-mono text-[11px] text-vm-text-dim">{typeLabel[c.channel_type] || c.channel_type} · {c.triggers?.join(', ') || 'No triggers'}</div>
            </div>
            {testResults[c.id] && (
              <div className={`font-mono text-xs px-3 py-1 rounded ${testResults[c.id].success ? 'bg-vm-success/10 text-vm-success' : 'bg-vm-danger/10 text-vm-danger'}`}>
                {testResults[c.id].message}
              </div>
            )}
            <div className="flex gap-2">
              <button onClick={() => handleTest(c.id)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08]">
                <TestTube className="w-3 h-3" /> Test
              </button>
              <button onClick={async () => { if (confirm('Delete?')) { await deleteNotificationChannel(c.id); load(); }}} className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10">
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          </div>
        ))}
        {channels.length === 0 && (
          <div className="text-center py-12 text-vm-text-dim font-mono">
            <Bell className="w-12 h-12 mx-auto mb-3 opacity-40" />
            <div className="tracking-[2px]">No notification channels configured</div>
          </div>
        )}
      </div>
    </div>
  );
}
