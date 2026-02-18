export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export function formatDate(date: string | null | undefined): string {
  if (!date) return '—';
  return new Date(date).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' });
}

export function formatRelative(date: string | null | undefined): string {
  if (!date) return '—';
  const now = Date.now();
  const d = new Date(date).getTime();
  const diff = now - d;
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

export function formatCountdown(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export function statusColor(status: string): string {
  switch (status) {
    case 'success': return 'text-vm-success';
    case 'running': return 'text-vm-accent';
    case 'failed': return 'text-vm-danger';
    case 'pending': return 'text-vm-warning';
    case 'cancelled': return 'text-vm-text-dim';
    case 'partial': return 'text-vm-accent2';
    default: return 'text-vm-text-dim';
  }
}

export function statusBg(status: string): string {
  switch (status) {
    case 'success': return 'bg-vm-success/10 border-vm-success/30 text-vm-success';
    case 'running': return 'bg-vm-accent/10 border-vm-accent/30 text-vm-accent';
    case 'failed': return 'bg-vm-danger/10 border-vm-danger/30 text-vm-danger';
    case 'pending': return 'bg-vm-warning/10 border-vm-warning/30 text-vm-warning';
    case 'cancelled': return 'bg-vm-text-dim/10 border-vm-text-dim/30 text-vm-text-dim';
    default: return 'bg-vm-surface2 border-vm-border text-vm-text-dim';
  }
}

export function backupTypeIcon(type: string): string {
  switch (type) {
    case 'postgresql': return '🐘';
    case 'docker_volumes': return '🐳';
    case 'files': return '📁';
    case 'do_snapshot': return '📸';
    case 'custom': return '⚡';
    default: return '💾';
  }
}
