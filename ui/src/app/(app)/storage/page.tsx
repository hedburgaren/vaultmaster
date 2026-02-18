'use client';

import { useEffect, useState } from 'react';
import { getStorageDestinations, createStorageDestination, deleteStorageDestination, testStorage } from '@/lib/api';
import { formatBytes } from '@/lib/utils';
import { Plus, Trash2, TestTube, Database, HardDrive, Cloud } from 'lucide-react';

export default function StoragePage() {
  const [dests, setDests] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', backend: 'local', config: '{}', capacity_bytes: '' });
  const [testResults, setTestResults] = useState<Record<string, any>>({});

  const load = () => getStorageDestinations().then(setDests).catch(() => {});
  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    await createStorageDestination({ ...form, config: JSON.parse(form.config || '{}'), capacity_bytes: form.capacity_bytes ? Number(form.capacity_bytes) : null });
    setShowForm(false); load();
  };

  const handleTest = async (id: string) => {
    const res = await testStorage(id);
    setTestResults((p: any) => ({ ...p, [id]: res }));
  };

  const backendIcon = (b: string) => b === 'local' ? <HardDrive className="w-5 h-5" /> : <Cloud className="w-5 h-5" />;

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">Lagring</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">// STORAGE DESTINATIONS · {dests.length} ST</div>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase hover:bg-[#33ddff] transition-all glow">
          <Plus className="w-4 h-4" /> Lägg till
        </button>
      </div>

      {showForm && (
        <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Namn</label>
              <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Backend</label>
              <select value={form.backend} onChange={e => setForm({...form, backend: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent">
                <option value="local">Lokal</option>
                <option value="s3">S3 / DO Spaces</option>
                <option value="gdrive">Google Drive</option>
                <option value="sftp">SFTP</option>
                <option value="b2">Backblaze B2</option>
              </select>
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Config (JSON)</label>
              <input value={form.config} onChange={e => setForm({...form, config: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder='{"path": "/mnt/backup"}' />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Kapacitet (bytes)</label>
              <input value={form.capacity_bytes} onChange={e => setForm({...form, capacity_bytes: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder="2000000000000" />
            </div>
          </div>
          <button onClick={handleCreate} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">Spara</button>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        {dests.map((d: any) => {
          const pct = d.capacity_bytes ? Math.round((d.used_bytes || 0) / d.capacity_bytes * 100) : null;
          return (
            <div key={d.id} className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright hover:-translate-y-0.5 transition-all">
              <div className="flex items-center gap-2.5 mb-4">
                <div className="w-9 h-9 rounded bg-vm-accent/10 flex items-center justify-center text-vm-accent">{backendIcon(d.backend)}</div>
                <div>
                  <div className="font-semibold text-vm-text-bright">{d.name}</div>
                  <div className="font-mono text-[11px] text-vm-text-dim">{d.backend}</div>
                </div>
              </div>
              {pct !== null && (
                <div className="mb-3">
                  <div className="flex justify-between font-mono text-[11px] text-vm-text-dim mb-1.5">
                    <span>Använt</span>
                    <strong className="text-vm-text">{formatBytes(d.used_bytes)} / {formatBytes(d.capacity_bytes)}</strong>
                  </div>
                  <div className="h-1.5 bg-vm-surface3 rounded overflow-hidden">
                    <div className={`h-full rounded ${pct > 90 ? 'bg-vm-danger' : pct > 70 ? 'bg-vm-warning' : 'bg-vm-success'}`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )}
              {testResults[d.id] && (
                <div className={`font-mono text-xs p-2 rounded mb-3 ${testResults[d.id].success ? 'bg-vm-success/10 text-vm-success border border-vm-success/30' : 'bg-vm-danger/10 text-vm-danger border border-vm-danger/30'}`}>
                  {testResults[d.id].message}
                </div>
              )}
              <div className="flex gap-2">
                <button onClick={() => handleTest(d.id)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08]">
                  <TestTube className="w-3 h-3" /> Testa
                </button>
                <button onClick={async () => { if (confirm('Ta bort?')) { await deleteStorageDestination(d.id); load(); }}} className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10">
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            </div>
          );
        })}
        {dests.length === 0 && (
          <div className="col-span-3 text-center py-12 text-vm-text-dim font-mono">
            <Database className="w-12 h-12 mx-auto mb-3 opacity-40" />
            <div className="tracking-[2px]">Inga lagringsplatser konfigurerade</div>
          </div>
        )}
      </div>
    </div>
  );
}
