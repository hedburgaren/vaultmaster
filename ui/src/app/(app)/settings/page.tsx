'use client';

import { useEffect, useState } from 'react';
import { getRetentionPolicies, createRetentionPolicy, deleteRetentionPolicy, previewRotation } from '@/lib/api';
import { Plus, Trash2, Eye, Settings } from 'lucide-react';

export default function SettingsPage() {
  const [policies, setPolicies] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', keep_hourly: 0, keep_daily: 7, keep_weekly: 4, keep_monthly: 3, keep_yearly: 0, max_age_days: 365 });
  const [previews, setPreviews] = useState<Record<string, any>>({});

  const load = () => getRetentionPolicies().then(setPolicies).catch(() => {});
  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    await createRetentionPolicy({ ...form, keep_hourly: Number(form.keep_hourly), keep_daily: Number(form.keep_daily), keep_weekly: Number(form.keep_weekly), keep_monthly: Number(form.keep_monthly), keep_yearly: Number(form.keep_yearly), max_age_days: Number(form.max_age_days) });
    setShowForm(false); load();
  };

  const handlePreview = async (id: string) => {
    const res = await previewRotation(id);
    setPreviews((p: any) => ({ ...p, [id]: res }));
  };

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">Inställningar</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">// RETENTION POLICIES & CONFIGURATION</div>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase hover:bg-[#33ddff] transition-all glow">
          <Plus className="w-4 h-4" /> Ny policy
        </button>
      </div>

      {showForm && (
        <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
          <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider">Ny retention policy (GFS)</h3>
          <div className="grid grid-cols-4 gap-4 mb-4">
            <div className="col-span-2">
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Namn</label>
              <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder="PostgreSQL Kritisk" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Hourly</label>
              <input type="number" value={form.keep_hourly} onChange={e => setForm({...form, keep_hourly: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Daily</label>
              <input type="number" value={form.keep_daily} onChange={e => setForm({...form, keep_daily: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Weekly</label>
              <input type="number" value={form.keep_weekly} onChange={e => setForm({...form, keep_weekly: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Monthly</label>
              <input type="number" value={form.keep_monthly} onChange={e => setForm({...form, keep_monthly: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Yearly</label>
              <input type="number" value={form.keep_yearly} onChange={e => setForm({...form, keep_yearly: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Max dagar</label>
              <input type="number" value={form.max_age_days} onChange={e => setForm({...form, max_age_days: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
            </div>
          </div>
          <button onClick={handleCreate} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">Spara</button>
        </div>
      )}

      <div className="space-y-3">
        {policies.map((p: any) => (
          <div key={p.id} className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright transition-all">
            <div className="flex items-center justify-between mb-3">
              <div className="font-semibold text-vm-text-bright text-lg">{p.name}</div>
              <div className="flex gap-2">
                <button onClick={() => handlePreview(p.id)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08]">
                  <Eye className="w-3 h-3" /> Preview
                </button>
                <button onClick={async () => { if (confirm('Ta bort?')) { await deleteRetentionPolicy(p.id); load(); }}} className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10">
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            </div>
            <div className="grid grid-cols-6 gap-3">
              {[['Hourly', p.keep_hourly], ['Daily', p.keep_daily], ['Weekly', p.keep_weekly], ['Monthly', p.keep_monthly], ['Yearly', p.keep_yearly], ['Max dagar', p.max_age_days]].map(([label, val]) => (
                <div key={label as string} className="text-center p-2.5 bg-vm-surface2 rounded border border-vm-border">
                  <div className="font-code text-lg font-bold text-vm-accent">{val}</div>
                  <div className="font-mono text-[10px] text-vm-text-dim mt-0.5">{label}</div>
                </div>
              ))}
            </div>
            {previews[p.id] && (
              <div className="mt-3 p-3 bg-vm-surface2 rounded border border-vm-border font-mono text-xs text-vm-text-dim">
                Totalt: {previews[p.id].total_artifacts} · Behåller: {previews[p.id].would_keep} · Tar bort: <span className="text-vm-danger">{previews[p.id].would_delete}</span>
              </div>
            )}
          </div>
        ))}
        {policies.length === 0 && (
          <div className="text-center py-12 text-vm-text-dim font-mono">
            <Settings className="w-12 h-12 mx-auto mb-3 opacity-40" />
            <div className="tracking-[2px]">Inga retention policies konfigurerade</div>
          </div>
        )}
      </div>
    </div>
  );
}
