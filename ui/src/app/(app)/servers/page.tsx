'use client';

import { useEffect, useState } from 'react';
import { getServers, createServer, deleteServer, testServer } from '@/lib/api';
import { formatRelative } from '@/lib/utils';
import Badge from '@/components/Badge';
import { Plus, Wifi, WifiOff, Trash2, TestTube, Server } from 'lucide-react';

export default function ServersPage() {
  const [servers, setServers] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', host: '', port: 22, auth_type: 'ssh_key', provider: 'custom', ssh_user: 'root', ssh_key_path: '', tags: '' });
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, any>>({});

  const load = () => getServers().then(setServers).catch(() => {});
  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    await createServer({ ...form, port: Number(form.port), tags: form.tags ? form.tags.split(',').map(t => t.trim()) : [] });
    setShowForm(false);
    setForm({ name: '', host: '', port: 22, auth_type: 'ssh_key', provider: 'custom', ssh_user: 'root', ssh_key_path: '', tags: '' });
    load();
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    try {
      const res = await testServer(id);
      setTestResult(prev => ({ ...prev, [id]: res }));
    } catch (e: any) {
      setTestResult(prev => ({ ...prev, [id]: { success: false, message: e.message } }));
    }
    setTesting(null);
  };

  const handleDelete = async (id: string) => {
    if (confirm('Ta bort server?')) { await deleteServer(id); load(); }
  };

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">Servrar</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">// ANSLUTNA SERVRAR · {servers.length} ST</div>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase hover:bg-[#33ddff] transition-all glow">
          <Plus className="w-4 h-4" /> Lägg till
        </button>
      </div>

      {showForm && (
        <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
          <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider">Ny server</h3>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Namn</label>
              <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder="my-server" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Host</label>
              <input value={form.host} onChange={e => setForm({...form, host: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder="192.168.1.42" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">SSH User</label>
              <input value={form.ssh_user} onChange={e => setForm({...form, ssh_user: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder="root" />
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Auth typ</label>
              <select value={form.auth_type} onChange={e => setForm({...form, auth_type: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent">
                <option value="ssh_key">SSH Key</option>
                <option value="ssh_password">SSH Password</option>
                <option value="api">API</option>
                <option value="local">Lokal</option>
              </select>
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Provider</label>
              <select value={form.provider} onChange={e => setForm({...form, provider: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent">
                <option value="custom">Custom</option>
                <option value="digitalocean">DigitalOcean</option>
                <option value="hetzner">Hetzner</option>
              </select>
            </div>
            <div>
              <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Taggar (komma-sep)</label>
              <input value={form.tags} onChange={e => setForm({...form, tags: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder="docker, postgresql, odoo" />
            </div>
          </div>
          <button onClick={handleCreate} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">Spara</button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        {servers.map((s: any) => (
          <div key={s.id} className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright hover:-translate-y-0.5 transition-all">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-11 h-11 bg-vm-accent/[0.08] border border-vm-border-bright rounded flex items-center justify-center">
                <Server className="w-5 h-5 text-vm-accent" />
              </div>
              <div className="flex-1">
                <div className="text-lg font-bold text-vm-text-bright">{s.name}</div>
                <div className="font-mono text-[11px] text-vm-text-dim">{s.host}:{s.port} · {s.auth_type}</div>
              </div>
              <div className="flex items-center gap-1.5 font-mono text-[11px]">
                {s.is_active && s.last_seen ? (
                  <><div className="w-2 h-2 rounded-full bg-vm-success shadow-[0_0_8px_theme(colors.vm.success)] animate-pulse-glow" /><span className="text-vm-success">ONLINE</span></>
                ) : (
                  <><div className="w-2 h-2 rounded-full bg-vm-danger" /><span className="text-vm-danger">OFFLINE</span></>
                )}
              </div>
            </div>
            {s.tags?.length > 0 && (
              <div className="flex gap-1.5 flex-wrap mb-4">
                {s.tags.map((t: string) => (
                  <span key={t} className="font-mono text-[10px] px-2.5 py-0.5 rounded-sm border border-vm-accent/40 bg-vm-accent/[0.08] text-vm-accent uppercase tracking-wider">{t}</span>
                ))}
              </div>
            )}
            <div className="font-mono text-[11px] text-vm-text-dim mb-3">Senast sedd: {formatRelative(s.last_seen)}</div>
            {testResult[s.id] && (
              <div className={`font-mono text-xs p-2 rounded mb-3 ${testResult[s.id].success ? 'bg-vm-success/10 text-vm-success border border-vm-success/30' : 'bg-vm-danger/10 text-vm-danger border border-vm-danger/30'}`}>
                {testResult[s.id].message}
              </div>
            )}
            <div className="flex gap-2">
              <button onClick={() => handleTest(s.id)} disabled={testing === s.id} className="flex items-center gap-1.5 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08] transition-all disabled:opacity-50">
                <TestTube className="w-3.5 h-3.5" /> {testing === s.id ? 'Testar...' : 'Testa'}
              </button>
              <button onClick={() => handleDelete(s.id)} className="flex items-center gap-1.5 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10 transition-all">
                <Trash2 className="w-3.5 h-3.5" /> Ta bort
              </button>
            </div>
          </div>
        ))}
        {servers.length === 0 && (
          <div className="col-span-2 text-center py-12 text-vm-text-dim font-mono">
            <Server className="w-12 h-12 mx-auto mb-3 opacity-40" />
            <div className="tracking-[2px]">Inga servrar konfigurerade</div>
          </div>
        )}
      </div>
    </div>
  );
}
