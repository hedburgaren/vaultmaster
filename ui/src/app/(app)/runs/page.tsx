'use client';

import { Fragment, Suspense, useEffect, useState, useMemo } from 'react';
import { useSearchParams } from 'next/navigation';
import { getRuns, cancelRun, getJobs } from '@/lib/api';
import { formatBytes, formatDate, formatRelative } from '@/lib/utils';
import Badge from '@/components/Badge';
import { XCircle, Archive, ChevronDown, ChevronUp, AlertTriangle, Terminal } from 'lucide-react';
import { useT } from '@/lib/i18n';

// useSearchParams() must be inside a Suspense boundary for Next.js 14
// static prerender, otherwise the page bails out of CSR.
export default function RunsPage() {
  return (
    <Suspense fallback={<div className="font-mono text-xs text-vm-text-dim">Loading…</div>}>
      <RunsPageInner />
    </Suspense>
  );
}

function RunsPageInner() {
  const t = useT();
  const searchParams = useSearchParams();
  const expandFromUrl = searchParams.get('expand');
  const [runs, setRuns] = useState<any[]>([]);
  const [jobs, setJobs] = useState<any[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(() => expandFromUrl ? new Set([expandFromUrl]) : new Set());
  const load = () => { getRuns().then(setRuns).catch(() => {}); };
  useEffect(() => { load(); getJobs().then(setJobs).catch(() => {}); const i = setInterval(load, 10000); return () => clearInterval(i); }, []);
  useEffect(() => {
    if (!expandFromUrl) return;
    const el = document.getElementById(`run-${expandFromUrl}`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [expandFromUrl, runs.length]);

  const jobMap = useMemo(() => {
    const m: Record<string, string> = {};
    jobs.forEach((j: any) => { m[j.id] = j.name; });
    return m;
  }, [jobs]);

  const toggleExpand = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleCancel = async (id: string) => {
    if (confirm(t('runs.confirm_cancel'))) { await cancelRun(id); load(); }
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">{t('runs.title')}</h1>
        <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">{t('runs.subtitle_prefix')} {runs.length} {t('common.total')}</div>
      </div>

      <div className="bg-vm-surface border border-vm-border rounded overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-vm-surface2 border-b border-vm-border">
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('runs.status')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('runs.job')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('runs.started')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('runs.finished')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('runs.size')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('runs.trigger')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal"></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r: any) => {
              const isExpanded = expanded.has(r.id);
              const hasError = r.status === 'failed' && (r.error_message || (r.log_lines && r.log_lines.length > 0));
              const lastError = r.log_lines?.filter((l: any) => l.level === 'error').pop();
              return (
                <Fragment key={r.id}>
                  <tr id={`run-${r.id}`} onClick={() => toggleExpand(r.id)} className={`border-b border-vm-border/50 hover:bg-vm-surface2 transition-colors cursor-pointer ${isExpanded ? 'bg-vm-surface2' : ''}`}>
                    <td className="px-4 py-3"><Badge status={r.status} /></td>
                    <td className="px-4 py-3 font-mono text-xs text-vm-text-bright">{jobMap[r.job_id] || <span className="text-vm-text-dim">{r.job_id?.slice(0, 8)}</span>}</td>
                    <td className="px-4 py-3 font-mono text-xs text-vm-text-dim">{formatDate(r.started_at)}</td>
                    <td className="px-4 py-3 font-mono text-xs text-vm-text-dim">{formatDate(r.finished_at)}</td>
                    <td className="px-4 py-3 font-code text-sm">{formatBytes(r.size_bytes)}</td>
                    <td className="px-4 py-3 font-mono text-xs text-vm-text-dim">{r.triggered_by}</td>
                    <td className="px-4 py-3 flex items-center gap-2">
                      {r.status === 'running' && (
                        <button onClick={(e) => { e.stopPropagation(); handleCancel(r.id); }} className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10">
                          <XCircle className="w-3 h-3" /> {t('runs.cancel')}
                        </button>
                      )}
                      {hasError && !isExpanded && <AlertTriangle className="w-3.5 h-3.5 text-vm-danger" />}
                      {isExpanded ? <ChevronUp className="w-3.5 h-3.5 text-vm-text-dim" /> : <ChevronDown className="w-3.5 h-3.5 text-vm-text-dim" />}
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr className="border-b border-vm-border/50">
                      <td colSpan={7} className="px-4 py-3 bg-vm-bg/50">
                        {/* Error message */}
                        {r.error_message && (
                          <div className="flex items-start gap-2 mb-3 p-2.5 bg-vm-danger/10 border border-vm-danger/30 rounded">
                            <AlertTriangle className="w-4 h-4 text-vm-danger shrink-0 mt-0.5" />
                            <div className="font-mono text-xs text-vm-danger break-all">{r.error_message}</div>
                          </div>
                        )}
                        {/* Log lines */}
                        {r.log_lines && r.log_lines.length > 0 ? (
                          <div className="space-y-0.5">
                            <div className="flex items-center gap-1.5 mb-1.5">
                              <Terminal className="w-3.5 h-3.5 text-vm-accent" />
                              <span className="font-mono text-[10px] text-vm-accent tracking-[2px] uppercase">{t('runs.log')} ({r.log_lines.length})</span>
                            </div>
                            <div className="bg-vm-surface border border-vm-border rounded p-2 max-h-48 overflow-y-auto">
                              {r.log_lines.map((line: any, i: number) => (
                                <div key={i} className={`font-mono text-[11px] py-0.5 ${line.level === 'error' ? 'text-vm-danger' : line.level === 'warn' ? 'text-yellow-400' : 'text-vm-text-dim'}`}>
                                  <span className="text-vm-text-dim/50 mr-2">{line.ts?.split('T')[1]?.split('.')[0] || ''}</span>
                                  <span className={`mr-2 px-1 rounded text-[9px] uppercase ${line.level === 'error' ? 'bg-vm-danger/20 text-vm-danger' : line.level === 'warn' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-vm-accent/10 text-vm-accent'}`}>{line.level}</span>
                                  <span className="break-all">{line.msg}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : (
                          <div className="font-mono text-[11px] text-vm-text-dim">{t('runs.no_logs')}</div>
                        )}
                      </td>
                    </tr>
                  )}
                  {/* Inline error preview (when not expanded) */}
                  {!isExpanded && lastError && (
                    <tr className="border-b border-vm-border/50">
                      <td colSpan={7} className="px-4 py-1.5 bg-vm-danger/[0.03]">
                        <div className="font-mono text-[10px] text-vm-danger/80 truncate"><AlertTriangle className="w-3 h-3 inline mr-1.5" />{lastError.msg}</div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        {runs.length === 0 && (
          <div className="text-center py-12 text-vm-text-dim font-mono">
            <Archive className="w-12 h-12 mx-auto mb-3 opacity-40" />
            <div className="tracking-[2px]">{t('runs.none')}</div>
          </div>
        )}
      </div>
    </div>
  );
}
