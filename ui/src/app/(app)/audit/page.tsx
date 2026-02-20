'use client';

import { useEffect, useState } from 'react';
import { getAuditLogs } from '@/lib/api';
import { formatDate } from '@/lib/utils';
import { Shield, User, Server, Clock, Filter } from 'lucide-react';
import { useT } from '@/lib/i18n';

const ACTION_COLORS: Record<string, string> = {
  create: 'text-vm-success',
  delete: 'text-vm-danger',
  trigger: 'text-vm-accent',
  restore: 'text-vm-warning',
  login: 'text-vm-accent',
  update: 'text-vm-text',
};

function actionColor(action: string): string {
  for (const [key, color] of Object.entries(ACTION_COLORS)) {
    if (action.includes(key)) return color;
  }
  return 'text-vm-text-dim';
}

export default function AuditPage() {
  const t = useT();
  const [logs, setLogs] = useState<any[]>([]);
  const [filter, setFilter] = useState('');

  const load = () => {
    const params = new URLSearchParams();
    if (filter) params.set('action', filter);
    params.set('limit', '100');
    getAuditLogs(params.toString()).then(setLogs).catch(() => {});
  };

  useEffect(() => { load(); }, [filter]);

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">{t('audit.title')}</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">{t('audit.subtitle_prefix')} {logs.length} {t('audit.entries')}</div>
        </div>
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-vm-text-dim" />
          <input
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder={t('audit.filter_placeholder')}
            className="bg-vm-surface border border-vm-border rounded px-3 py-2 text-vm-text font-mono text-sm outline-none focus:border-vm-accent w-56"
          />
        </div>
      </div>

      <div className="bg-vm-surface border border-vm-border rounded overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-vm-surface2 border-b border-vm-border">
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('audit.time')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('audit.user')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('audit.action')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('audit.resource')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('audit.detail')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('audit.ip')}</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((l: any) => (
              <tr key={l.id} className="border-b border-vm-border/50 hover:bg-vm-surface2 transition-colors">
                <td className="px-4 py-3 font-mono text-xs text-vm-text-dim whitespace-nowrap">
                  <Clock className="w-3 h-3 inline mr-1" />
                  {l.created_at ? formatDate(l.created_at) : '—'}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1.5">
                    <User className="w-3.5 h-3.5 text-vm-text-dim" />
                    <span className="font-mono text-sm text-vm-text-bright">{l.username || '—'}</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className={`font-mono text-xs font-bold tracking-wider uppercase ${actionColor(l.action)}`}>
                    {l.action}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {l.resource_type && (
                    <span className="font-mono text-[10px] px-2 py-0.5 rounded-sm bg-vm-surface3 text-vm-text-dim border border-vm-border">
                      {l.resource_type}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-vm-text-dim max-w-[300px] truncate">{l.detail || '—'}</td>
                <td className="px-4 py-3 font-mono text-[10px] text-vm-text-dim">{l.ip_address || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {logs.length === 0 && (
          <div className="text-center py-12 text-vm-text-dim font-mono">
            <Shield className="w-12 h-12 mx-auto mb-3 opacity-40" />
            <div className="tracking-[2px]">{t('audit.none')}</div>
            <div className="text-[11px] mt-1">{t('audit.none_desc')}</div>
          </div>
        )}
      </div>
    </div>
  );
}
