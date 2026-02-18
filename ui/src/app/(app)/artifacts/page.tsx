'use client';

import { useEffect, useState } from 'react';
import { getArtifacts, restoreArtifact, verifyArtifact } from '@/lib/api';
import { formatBytes, formatDate, backupTypeIcon } from '@/lib/utils';
import Badge from '@/components/Badge';
import { RotateCcw, ShieldCheck, Search } from 'lucide-react';

export default function ArtifactsPage() {
  const [artifacts, setArtifacts] = useState<any[]>([]);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');

  const load = () => {
    const params = new URLSearchParams();
    if (search) params.set('q', search);
    if (typeFilter) params.set('backup_type', typeFilter);
    getArtifacts(params.toString()).then(setArtifacts).catch(() => {});
  };

  useEffect(() => { load(); }, [search, typeFilter]);

  const handleRestore = async (id: string) => {
    if (confirm('Starta återställning?')) {
      const res = await restoreArtifact(id);
      alert(`Återställning köad: ${res.task_id}`);
    }
  };

  const handleVerify = async (id: string) => {
    const res = await verifyArtifact(id);
    alert(`Verifiering köad: ${res.task_id}`);
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">Återställning</h1>
        <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">// BACKUP ARTIFACTS · VÄLJ OCH ÅTERSTÄLL</div>
      </div>

      <div className="flex gap-4 mb-6">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-vm-text-dim" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Sök backups..." className="w-full bg-vm-surface border border-vm-border rounded pl-10 pr-4 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
        </div>
        <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} className="bg-vm-surface border border-vm-border rounded px-4 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent">
          <option value="">Alla typer</option>
          <option value="postgresql">PostgreSQL</option>
          <option value="docker_volumes">Docker</option>
          <option value="files">Filer</option>
          <option value="do_snapshot">Snapshot</option>
        </select>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {artifacts.map((a: any) => (
          <div key={a.id} className="bg-vm-surface2 border border-vm-border rounded p-4 flex items-center gap-3 hover:border-vm-accent hover:bg-vm-accent/[0.03] transition-all cursor-pointer">
            <div className="w-10 h-10 rounded bg-vm-surface3 flex items-center justify-center text-xl shrink-0">{backupTypeIcon(a.backup_type)}</div>
            <div className="flex-1 min-w-0">
              <div className="text-[15px] font-bold text-vm-text-bright truncate">{a.filename}</div>
              <div className="font-mono text-[11px] text-vm-text-dim mt-0.5">
                {a.server_name} · {a.domain || '—'} · {a.is_encrypted ? '🔒' : ''} {formatDate(a.created_at)}
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className="font-code text-sm font-bold text-vm-accent">{formatBytes(a.size_bytes)}</div>
              <div className="flex gap-1.5 mt-2">
                <button onClick={() => handleRestore(a.id)} className="flex items-center gap-1 px-2.5 py-1 bg-vm-success text-vm-bg rounded text-[10px] font-bold tracking-wider uppercase glow-success">
                  <RotateCcw className="w-3 h-3" /> Återställ
                </button>
                <button onClick={() => handleVerify(a.id)} className="flex items-center gap-1 px-2.5 py-1 border border-vm-accent text-vm-accent rounded text-[10px] font-bold tracking-wider uppercase">
                  <ShieldCheck className="w-3 h-3" /> Verifiera
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
      {artifacts.length === 0 && (
        <div className="text-center py-12 text-vm-text-dim font-mono">
          <RotateCcw className="w-12 h-12 mx-auto mb-3 opacity-40" />
          <div className="tracking-[2px]">Inga backups hittade</div>
        </div>
      )}
    </div>
  );
}
