import clsx from 'clsx';

interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  color?: 'accent' | 'green' | 'yellow' | 'orange' | 'danger';
  delay?: number;
}

const colorMap = {
  accent: 'text-vm-accent',
  green: 'text-vm-success',
  yellow: 'text-vm-warning',
  orange: 'text-vm-accent2',
  danger: 'text-vm-danger',
};

const barColorMap = {
  accent: 'bg-vm-accent',
  green: 'bg-vm-success',
  yellow: 'bg-vm-warning',
  orange: 'bg-vm-accent2',
  danger: 'bg-vm-danger',
};

export default function StatCard({ label, value, sub, color = 'accent', delay = 0 }: StatCardProps) {
  return (
    <div
      className="bg-vm-surface border border-vm-border rounded p-5 relative overflow-hidden hover:border-vm-border-bright hover:-translate-y-0.5 transition-all group"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className={clsx('absolute top-0 left-0 right-0 h-0.5', barColorMap[color])} />
      <div className="font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">{label}</div>
      <div className={clsx('font-code text-[32px] font-bold leading-none mb-1', colorMap[color])}>{value}</div>
      {sub && <div className="text-xs text-vm-text-dim font-mono">{sub}</div>}
    </div>
  );
}
