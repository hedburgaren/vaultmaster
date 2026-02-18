import clsx from 'clsx';
import { statusBg } from '@/lib/utils';

export default function Badge({ status, label }: { status: string; label?: string }) {
  const text = label || status.toUpperCase();
  return (
    <span className={clsx('inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-sm font-mono text-[11px] tracking-wider font-bold border', statusBg(status))}>
      <span className={clsx('w-1.5 h-1.5 rounded-full', {
        'bg-vm-success shadow-[0_0_6px_theme(colors.vm.success)]': status === 'success',
        'bg-vm-accent shadow-[0_0_6px_theme(colors.vm.accent)] animate-pulse-glow': status === 'running',
        'bg-vm-danger': status === 'failed',
        'bg-vm-warning animate-pulse-glow': status === 'pending',
        'bg-vm-text-dim': status === 'cancelled',
      })} />
      {text}
    </span>
  );
}
