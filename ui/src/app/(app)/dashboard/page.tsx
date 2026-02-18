'use client';

import { useEffect, useState } from 'react';
import { getDashboard } from '@/lib/api';
import { formatBytes, formatCountdown } from '@/lib/utils';
import StatCard from '@/components/StatCard';
import Badge from '@/components/Badge';
import { Play, Plus, AlertTriangle } from 'lucide-react';

export default function DashboardPage() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    getDashboard().then(setData).catch((e) => setError(e.message));
    const interval = setInterval(() => {
      getDashboard().then(setData).catch(() => {});
    }, 15000);
    return () => clearInterval(interval);
  }, []);

  if (error) return <div className="text-vm-danger font-mono p-8">{error}</div>;
  if (!data) return <div className="text-vm-text-dim font-mono p-8 animate-pulse">Loading dashboard...</div>;

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">Dashboard</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">// BACKUP CONTROL CENTER · v1.0</div>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4 mb-6">
        <StatCard label="Servers online" value={`${data.servers_online}/${data.servers_total}`} sub={`${data.servers_total} total`} color="accent" />
        <StatCard label="Successful (24h)" value={data.runs_success_24h} sub={`${data.success_rate}% success rate`} color="green" delay={50} />
        <StatCard label="Active jobs" value={data.jobs_active} sub={`${data.jobs_total} total`} color="yellow" delay={100} />
        <StatCard label="Failed (24h)" value={data.runs_failed_24h} sub={data.runs_failed_24h > 0 ? 'Check logs' : 'No errors'} color={data.runs_failed_24h > 0 ? 'danger' : 'green'} delay={150} />
      </div>

      {/* Active runs */}
      {data.active_runs.length > 0 && (
        <div className="mb-6">
          {data.active_runs.map((run: any) => (
            <div key={run.id} className="bg-vm-surface border border-vm-accent rounded p-5 relative overflow-hidden glow mb-4">
              <div className="absolute top-3 right-4 font-mono text-[11px] text-vm-accent tracking-[3px] animate-blink">LIVE</div>
              <div className="text-base font-bold text-vm-text-bright tracking-wide mb-1">Active run</div>
              <div className="font-mono text-xs text-vm-text-dim">Started: {run.started_at || '—'}</div>
            </div>
          ))}
        </div>
      )}

      {/* Storage overview */}
      {data.storage_destinations.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2.5 mb-4">
            <div className="w-0.5 h-[18px] bg-vm-accent rounded" />
            <h2 className="text-base font-bold text-vm-text-bright tracking-[2px] uppercase">Storage Destinations</h2>
          </div>
          <div className="grid grid-cols-3 gap-4">
            {data.storage_destinations.map((s: any) => (
              <div key={s.id} className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright hover:-translate-y-0.5 transition-all">
                <div className="font-semibold text-vm-text-bright mb-3">{s.name}</div>
                <div className="flex justify-between font-mono text-[11px] text-vm-text-dim mb-1.5">
                  <span>Used</span>
                  <strong className="text-vm-text">{formatBytes(s.used_bytes)} / {s.capacity_bytes ? formatBytes(s.capacity_bytes) : '∞'}</strong>
                </div>
                {s.percent_used !== null && (
                  <div className="h-1.5 bg-vm-surface3 rounded overflow-hidden">
                    <div
                      className={`h-full rounded transition-all ${s.percent_used > 90 ? 'bg-gradient-to-r from-vm-danger to-red-700' : s.percent_used > 70 ? 'bg-gradient-to-r from-vm-warning to-amber-600' : 'bg-gradient-to-r from-vm-success to-green-600'}`}
                      style={{ width: `${Math.min(s.percent_used, 100)}%` }}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Next scheduled runs */}
      {data.next_runs.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2.5 mb-4">
            <div className="w-0.5 h-[18px] bg-vm-accent rounded" />
            <h2 className="text-base font-bold text-vm-text-bright tracking-[2px] uppercase">Upcoming Runs</h2>
          </div>
          <div className="bg-vm-surface border border-vm-border rounded overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-vm-surface2 border-b border-vm-border">
                  <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Job</th>
                  <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Next Run</th>
                  <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">Countdown</th>
                </tr>
              </thead>
              <tbody>
                {data.next_runs.slice(0, 8).map((r: any) => (
                  <tr key={r.job_id} className="border-b border-vm-border/50 hover:bg-vm-surface2 transition-colors">
                    <td className="px-4 py-3 text-sm font-semibold">{r.job_name}</td>
                    <td className="px-4 py-3 font-mono text-xs text-vm-text-dim">{new Date(r.next_run).toLocaleString('en-GB')}</td>
                    <td className="px-4 py-3 font-mono text-xs text-vm-accent">{formatCountdown(r.seconds_until)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recent errors */}
      {data.recent_errors.length > 0 && (
        <div>
          <div className="flex items-center gap-2.5 mb-4">
            <div className="w-0.5 h-[18px] bg-vm-danger rounded" />
            <h2 className="text-base font-bold text-vm-text-bright tracking-[2px] uppercase">Recent Errors</h2>
          </div>
          <div className="space-y-2">
            {data.recent_errors.map((e: any) => (
              <div key={e.id} className="bg-vm-surface border border-vm-danger/30 rounded p-4 flex items-center gap-3">
                <AlertTriangle className="w-5 h-5 text-vm-danger shrink-0" />
                <div className="flex-1">
                  <div className="font-mono text-xs text-vm-danger">{e.error || 'Unknown error'}</div>
                  <div className="font-mono text-[10px] text-vm-text-dim mt-1">{e.created_at}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
