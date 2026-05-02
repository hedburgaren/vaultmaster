'use client';

import { useEffect } from 'react';
import { AlertTriangle, X } from 'lucide-react';

interface ConfirmModalProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onCancel]);

  if (!open) return null;

  const confirmCls = destructive
    ? 'bg-vm-danger text-white hover:bg-vm-danger/90'
    : 'bg-vm-accent text-vm-bg hover:bg-vm-accent/90';

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="bg-vm-surface2 border border-vm-border-bright rounded shadow-2xl w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-vm-border">
          <div className="flex items-center gap-2">
            {destructive && <AlertTriangle className="w-4 h-4 text-vm-danger" />}
            <span className="font-mono text-xs uppercase tracking-[2px] text-vm-text-bright">{title}</span>
          </div>
          <button onClick={onCancel} className="text-vm-text-dim hover:text-vm-text-bright">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-5 py-4 font-mono text-sm text-vm-text whitespace-pre-wrap">{message}</div>
        <div className="px-5 py-3 border-t border-vm-border flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-surface3"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            className={`px-3 py-1.5 rounded text-xs font-bold tracking-wider uppercase ${confirmCls}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
