'use client';

import { useEffect, useState } from 'react';
import { getDashboard } from '@/lib/api';
import { formatBytes, formatCountdown, formatRelative } from '@/lib/utils';
import StatCard from '@/components/StatCard';
import Badge from '@/components/Badge';
import { Play, AlertTriangle, Server, HardDrive, Clock, Shield, Archive, Activity } from 'lucide-react';
import { useT } from '@/lib/i18n';

export default function DashboardPage() {
  const t = useT();
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
  if (!data) return <div className="text-vm-text-dim font-mono p-8 animate-pulse">{t('dash.loading')}</div>;

  const backupAgeColor = data.hours_since_last_backup === null ? 'text-vm-text-dim' : data.hours_since_last_backup > 48 ? 'text-vm-danger' : data.hours_since_last_backup > 24 ? 'text-vm-warning' : 'text-vm-success';
  const backupAgeLabel = data.hours_since_last_backup === null ? t('dash.no_backups_yet') : data.hours_since_last_backup < 1 ? t('dash.less_than_1h') : `${Math.round(data.hours_since_last_backup)}${t('dash.hours_ago')}`;

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">{t('dash.title')}</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">{t('dash.subtitle')}</div>
        </div>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <StatCard label={t('dash.servers_online')} value={`${data.servers_online}/${data.servers_total}`} sub={`${data.servers_total} ${t('dash.total')}`} color="accent" />
        <StatCard label={t('dash.successful_24h')} value={data.runs_success_24h} sub={`${data.success_rate}% ${t('dash.success_rate')}`} color="green" delay={50} />
        <StatCard label={t('dash.active_jobs')} value={data.jobs_active} sub={`${data.jobs_total} ${t('dash.total')}`} color="yellow" delay={100} />
        <StatCard label={t('dash.failed_24h')} value={data.runs_failed_24h} sub={data.runs_failed_24h > 0 ? t('dash.check_logs') : t('dash.all_clear')} color={data.runs_failed_24h > 0 ? 'danger' : 'green'} delay={150} />
      </div>

      {/* Health widgets row */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        {/* Last backup age */}
        <div className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright transition-all">
          <div className="flex items-center gap-2 mb-3">
            <Clock className={`w-5 h-5 ${backupAgeColor}`} />
            <div className="font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase">{t('dash.last_backup')}</div>
          </div>
          <div className={`font-code text-2xl font-bold ${backupAgeColor}`}>{backupAgeLabel}</div>
          {data.last_successful_backup && (
            <div className="font-mono text-[10px] text-vm-text-dim mt-1">{new Date(data.last_successful_backup).toLocaleString('en-GB')}</div>
          )}
        </div>

        {/* Total artifacts */}
        <div className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright transition-all">
          <div className="flex items-center gap-2 mb-3">
            <Archive className="w-5 h-5 text-vm-accent" />
            <div className="font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase">{t('dash.backup_vault')}</div>
          </div>
          <div className="font-code text-2xl font-bold text-vm-accent">{data.total_artifacts}</div>
          <div className="font-mono text-[10px] text-vm-text-dim mt-1">{formatBytes(data.total_artifact_bytes)} {t('dash.total')}</div>
        </div>

        {/* System health summary */}
        <div className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright transition-all">
          <div className="flex items-center gap-2 mb-3">
            <Activity className="w-5 h-5 text-vm-success" />
            <div className="font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase">{t('dash.system_health')}</div>
          </div>
          {(() => {
            const issues: string[] = [];
            if (data.runs_failed_24h > 0) issues.push(`${data.runs_failed_24h} ${t('dash.failed_backups')}`);
            if (data.storage_warnings?.length > 0) issues.push(`${data.storage_warnings.length} ${t('dash.storage_warnings')}`);
            const offlineServers = data.server_health?.filter((s: any) => !s.online).length || 0;
            if (offlineServers > 0) issues.push(`${offlineServers} ${t('dash.servers_offline')}`);
            if (data.hours_since_last_backup !== null && data.hours_since_last_backup > 48) issues.push(t('dash.no_backup_48h'));
            if (issues.length === 0) {
              return (
                <div>
                  <div className="font-code text-2xl font-bold text-vm-success">{t('dash.healthy')}</div>
                  <div className="font-mono text-[10px] text-vm-text-dim mt-1">{t('dash.all_operational')}</div>
                </div>
              );
            }
            return (
              <div>
                <div className="font-code text-2xl font-bold text-vm-danger">{issues.length} {issues.length > 1 ? t('dash.issues') : t('dash.issue')}</div>
                <div className="space-y-0.5 mt-1">
                  {issues.map((issue, i) => (
                    <div key={i} className="font-mono text-[10px] text-vm-danger flex items-center gap-1">
                      <div className="w-1 h-1 rounded-full bg-vm-danger shrink-0" />
                      {issue}
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}
        </div>
      </div>

      {/* Active runs */}
      {data.active_runs.length > 0 && (
        <div className="mb-6">
          {data.active_runs.map((run: any) => (
            <div key={run.id} className="bg-vm-surface border border-vm-accent rounded p-5 relative overflow-hidden glow mb-4">
              <div className="absolute top-3 right-4 font-mono text-[11px] text-vm-accent tracking-[3px] animate-blink">LIVE</div>
              <div className="text-base font-bold text-vm-text-bright tracking-wide mb-1">{t('dash.active_run')}</div>
              <div className="font-mono text-xs text-vm-text-dim">{t('dash.started')}: {run.started_at || '—'}</div>
            </div>
          ))}
        </div>
      )}

      {/* Storage warnings */}
      {data.storage_warnings?.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2.5 mb-4">
            <div className="w-0.5 h-[18px] bg-vm-warning rounded" />
            <h2 className="text-base font-bold text-vm-text-bright tracking-[2px] uppercase">{t('dash.storage_warnings_title')}</h2>
          </div>
          <div className="space-y-2">
            {data.storage_warnings.map((w: any) => (
              <div key={w.id} className={`bg-vm-surface border rounded p-4 flex items-center gap-3 ${w.level === 'critical' ? 'border-vm-danger/50' : 'border-vm-warning/50'}`}>
                <HardDrive className={`w-5 h-5 shrink-0 ${w.level === 'critical' ? 'text-vm-danger' : 'text-vm-warning'}`} />
                <div className="flex-1">
                  <div className="font-semibold text-vm-text-bright">{w.name}</div>
                  <div className="font-mono text-[11px] text-vm-text-dim">{w.backend}</div>
                </div>
                <div className={`font-code text-lg font-bold ${w.level === 'critical' ? 'text-vm-danger' : 'text-vm-warning'}`}>
                  {w.percent_used}%
                </div>
                <Badge status={w.level === 'critical' ? 'failed' : 'running'} label={w.level.toUpperCase()} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Server health */}
      {data.server_health?.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2.5 mb-4">
            <div className="w-0.5 h-[18px] bg-vm-accent rounded" />
            <h2 className="text-base font-bold text-vm-text-bright tracking-[2px] uppercase">{t('dash.server_health')}</h2>
          </div>
          <div className="grid grid-cols-4 gap-3">
            {data.server_health.map((s: any) => (
              <div key={s.id} className={`bg-vm-surface border rounded p-4 hover:border-vm-border-bright transition-all ${s.online ? 'border-vm-border' : 'border-vm-danger/40'}`}>
                <div className="flex items-center gap-2 mb-2">
                  <div className={`w-2 h-2 rounded-full ${s.online ? 'bg-vm-success shadow-[0_0_6px_theme(colors.vm.success)]' : 'bg-vm-danger'}`} />
                  <span className="font-semibold text-sm text-vm-text-bright truncate">{s.name}</span>
                </div>
                <div className="font-mono text-[10px] text-vm-text-dim">{s.host}</div>
                <div className="font-mono text-[10px] text-vm-text-dim mt-1">
                  {s.online ? (
                    <span className="text-vm-success">{t('dash.online')}</span>
                  ) : (
                    <span className="text-vm-danger">{t('dash.offline')}{s.last_seen_hours_ago !== null ? ` · ${t('dash.last_seen')} ${Math.round(s.last_seen_hours_ago)}${t('dash.hours_ago')}` : ''}</span>
                  )}
                </div>
                {s.tags?.length > 0 && (
                  <div className="flex gap-1 mt-2 flex-wrap">
                    {s.tags.slice(0, 3).map((t: string) => (
                      <span key={t} className="font-mono text-[8px] px-1.5 py-0.5 rounded-sm bg-vm-accent/[0.06] text-vm-accent border border-vm-accent/20 uppercase">{t}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Storage overview */}
      {data.storage_destinations.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2.5 mb-4">
            <div className="w-0.5 h-[18px] bg-vm-accent rounded" />
            <h2 className="text-base font-bold text-vm-text-bright tracking-[2px] uppercase">{t('dash.storage_destinations')}</h2>
          </div>
          <div className="grid grid-cols-3 gap-4">
            {data.storage_destinations.map((s: any) => (
              <div key={s.id} className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright hover:-translate-y-0.5 transition-all">
                <div className="font-semibold text-vm-text-bright mb-3">{s.name}</div>
                <div className="flex justify-between font-mono text-[11px] text-vm-text-dim mb-1.5">
                  <span>{t('dash.used')}</span>
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
            <h2 className="text-base font-bold text-vm-text-bright tracking-[2px] uppercase">{t('dash.upcoming_runs')}</h2>
          </div>
          <div className="bg-vm-surface border border-vm-border rounded overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-vm-surface2 border-b border-vm-border">
                  <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('dash.job')}</th>
                  <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('dash.next_run')}</th>
                  <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('dash.countdown')}</th>
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
            <h2 className="text-base font-bold text-vm-text-bright tracking-[2px] uppercase">{t('dash.recent_errors')}</h2>
          </div>
          <div className="space-y-2">
            {data.recent_errors.map((e: any) => (
              <div key={e.id} className="bg-vm-surface border border-vm-danger/30 rounded p-4 flex items-center gap-3">
                <AlertTriangle className="w-5 h-5 text-vm-danger shrink-0" />
                <div className="flex-1">
                  <div className="font-mono text-xs text-vm-danger">{e.error || t('dash.unknown_error')}</div>
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
