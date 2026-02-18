'use client';

import { Lock, Plus } from 'lucide-react';
import { logout } from '@/lib/api';

export default function Topbar() {
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
        <button onClick={logout} className="font-mono text-xs text-vm-text-dim hover:text-vm-danger transition-colors">
          Log out
        </button>
      </div>
    </header>
  );
}
