'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LayoutDashboard, Clock, RotateCcw, Database, FileText, Bell, Settings, Server, Archive } from 'lucide-react';
import clsx from 'clsx';

const navItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/servers', label: 'Servrar', icon: Server },
  { href: '/jobs', label: 'Backup Jobs', icon: Clock },
  { href: '/runs', label: 'Körningar', icon: Archive },
  { href: '/artifacts', label: 'Återställning', icon: RotateCcw },
  { href: '/storage', label: 'Lagring', icon: Database },
  { href: '/notifications', label: 'Notifikationer', icon: Bell },
  { href: '/settings', label: 'Inställningar', icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-[260px] bg-vm-surface border-r border-vm-border py-5 flex flex-col gap-2 shrink-0">
      <div className="px-4 mb-2">
        <div className="font-mono text-[10px] text-vm-text-dim tracking-[3px] uppercase px-2 mb-1.5">Navigation</div>
      </div>
      <nav className="flex flex-col gap-0.5 px-2">
        {navItems.map((item) => {
          const active = pathname === item.href || pathname?.startsWith(item.href + '/');
          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                'flex items-center gap-3 px-4 py-2.5 rounded text-[15px] font-semibold tracking-wide transition-all',
                active
                  ? 'bg-vm-accent/[0.08] text-vm-accent border-l-2 border-vm-accent -ml-0.5'
                  : 'text-vm-text-dim hover:bg-vm-surface2 hover:text-vm-text'
              )}
            >
              <item.icon className="w-[18px] h-[18px]" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
