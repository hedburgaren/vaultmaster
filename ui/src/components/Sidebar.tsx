'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LayoutDashboard, Clock, RotateCcw, Database, Bell, Settings, Server, Archive, Shield, Users, HardDrive, CalendarClock } from 'lucide-react';
import clsx from 'clsx';
import { useT } from '@/lib/i18n';

const navItems = [
  // Overview
  { href: '/dashboard', i18nKey: 'nav.dashboard', icon: LayoutDashboard },
  // Setup (logical order: storage → servers → jobs)
  { href: '/storage', i18nKey: 'nav.storage', icon: HardDrive },
  { href: '/servers', i18nKey: 'nav.servers', icon: Server },
  { href: '/jobs', i18nKey: 'nav.jobs', icon: Clock },
  // Operations
  { href: '/runs', i18nKey: 'nav.runs', icon: Archive },
  { href: '/artifacts', i18nKey: 'nav.artifacts', icon: RotateCcw },
  // System
  { href: '/notifications', i18nKey: 'nav.notifications', icon: Bell },
  { href: '/audit', i18nKey: 'nav.audit', icon: Shield },
  { href: '/users', i18nKey: 'nav.users', icon: Users },
  { href: '/settings', i18nKey: 'nav.settings', icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();
  const t = useT();

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
              {t(item.i18nKey)}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
