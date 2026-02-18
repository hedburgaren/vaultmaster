'use client';

import { useEffect, useState } from 'react';
import { Lock, Bell } from 'lucide-react';
import { logout, getDashboard } from '@/lib/api';

export default function Topbar() {
  const [failedCount, setFailedCount] = useState(0);
  const [errorCount, setErrorCount] = useState(0);
  const [showPanel, setShowPanel] = useState(false);
  const [errors, setErrors] = useState<any[]>([]);

  useEffect(() => {
    const load = () => {
      getDashboard().then((d: any) => {
        setFailedCount(d.runs_failed_24h || 0);
        setErrorCount(d.recent_errors?.length || 0);
        setErrors(d.recent_errors || []);
      }).catch(() => {});
    };
    load();
    const i = setInterval(load, 30000);
    return () => clearInterval(i);
  }, []);

  const bellColor = failedCount > 0 ? 'text-vm-danger' : errorCount > 0 ? 'text-vm-warning' : 'text-vm-text-dim';
  const badgeColor = failedCount > 0 ? 'bg-vm-danger' : errorCount > 0 ? 'bg-vm-warning' : '';
  const totalAlerts = failedCount + errorCount;

  return (
    <header className="flex items-center justify-between px-6 h-[60px] bg-vm-surface/95 border-b border-vm-border sticky top-0 z-50 backdrop-blur-xl">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 border-2 border-vm-accent flex items-center justify-center bg-vm-accent/10 glow" style={{ clipPath: 'polygon(10% 0%, 90% 0%, 100% 10%, 100% 90%, 90% 100%, 10% 100%, 0% 90%, 0% 10%)' }}>
          <Lock className="w-5 h-5 text-vm-accent" />
        </div>
        <div>
          <div className="font-code text-lg font-bold text-vm-text-bright tracking-[4px] uppercase">VAULTMASTER</div>
          <div className="font-mono text-[10px] text-vm-accent tracking-[3px] uppercase">Backup Control Center</div>
        </div>
      </div>
      <div className="flex items-center gap-5">
        <div className="font-mono text-xs text-vm-text-dim text-right">
          <div>System</div>
          <span className="text-vm-success text-sm">ONLINE</span>
        </div>

        {/* Notification bell */}
        <div className="relative">
          <button onClick={() => setShowPanel(!showPanel)} className={`relative p-1.5 rounded hover:bg-vm-surface2 transition-colors ${bellColor}`}>
            <Bell className="w-5 h-5" />
            {totalAlerts > 0 && (
              <span className={`absolute -top-0.5 -right-0.5 w-4 h-4 ${badgeColor} rounded-full flex items-center justify-center text-[9px] font-bold text-white`}>
                {totalAlerts > 9 ? '9+' : totalAlerts}
              </span>
            )}
          </button>
          {showPanel && (
            <div className="absolute right-0 top-full mt-2 w-80 bg-vm-surface2 border border-vm-border-bright rounded shadow-2xl z-50">
              <div className="px-4 py-3 border-b border-vm-border flex items-center justify-between">
                <span className="font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase">Notifications</span>
                {failedCount > 0 && <span className="font-mono text-[10px] text-vm-danger">{failedCount} failed (24h)</span>}
              </div>
              <div className="max-h-64 overflow-y-auto">
                {errors.length === 0 ? (
                  <div className="px-4 py-6 text-center font-mono text-xs text-vm-text-dim">
                    <Bell className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    All clear — no recent errors
                  </div>
                ) : (
                  errors.map((e: any, i: number) => (
                    <div key={i} className="px-4 py-3 border-b border-vm-border/50 hover:bg-vm-surface3 transition-colors">
                      <div className="flex items-center gap-2 mb-1">
                        <div className="w-1.5 h-1.5 rounded-full bg-vm-danger shrink-0" />
                        <span className="font-mono text-[10px] text-vm-text-dim">{e.created_at ? new Date(e.created_at).toLocaleString('en-GB') : '—'}</span>
                      </div>
                      <div className="font-mono text-xs text-vm-danger pl-3.5 truncate">{e.error || 'Unknown error'}</div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        <button onClick={logout} className="font-mono text-xs text-vm-text-dim hover:text-vm-danger transition-colors">
          Log out
        </button>
      </div>
    </header>
  );
}
