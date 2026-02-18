'use client';

import { useEffect, useState } from 'react';
import { getRuns, cancelRun } from '@/lib/api';
import { formatBytes, formatDate, formatRelative } from '@/lib/utils';
import Badge from '@/components/Badge';
import { XCircle, Archive } from 'lucide-react';

export default function RunsPage() {
  const [runs, setRuns] = useState<any[]>([]);
  const load = () => getRuns().then(setRuns).catch(() => {});
  useEffect(() => { load(); const i = setInterval(load, 10000); return () => clearInterval(i); }, []);

  const handleCancel = async (id: string) => {
    if (confirm('Avbryt körning?')) { await cancelRun(id); load(); }
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">Körningar</h1>
        <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">// BACKUP RUNS · {runs.length} ST</div>
      </div>

      <div className="bg-vm-surface border border-vm-border rounded overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-vm-surface2 border-b border-vm-border">
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Status</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Startad</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Klar</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Storlek</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Trigger</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal"></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r: any) => (
              <tr key={r.id} className="border-b border-vm-border/50 hover:bg-vm-surface2 transition-colors">
                <td className="px-4 py-3"><Badge status={r.status} /></td>
                <td className="px-4 py-3 font-mono text-xs text-vm-text-dim">{formatDate(r.started_at)}</td>
                <td className="px-4 py-3 font-mono text-xs text-vm-text-dim">{formatDate(r.finished_at)}</td>
                <td className="px-4 py-3 font-code text-sm">{formatBytes(r.size_bytes)}</td>
                <td className="px-4 py-3 font-mono text-xs text-vm-text-dim">{r.triggered_by}</td>
                <td className="px-4 py-3">
                  {r.status === 'running' && (
                    <button onClick={() => handleCancel(r.id)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10">
                      <XCircle className="w-3 h-3" /> Avbryt
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {runs.length === 0 && (
          <div className="text-center py-12 text-vm-text-dim font-mono">
            <Archive className="w-12 h-12 mx-auto mb-3 opacity-40" />
            <div className="tracking-[2px]">Inga körningar ännu</div>
          </div>
        )}
      </div>
    </div>
  );
}
