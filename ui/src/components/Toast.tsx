'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-react';

type ToastKind = 'success' | 'error' | 'info' | 'warning';

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
  ttl_ms: number;
}

interface ToastApi {
  push: (kind: ToastKind, message: string, ttl_ms?: number) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
  warning: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const push = useCallback((kind: ToastKind, message: string, ttl_ms = 4000) => {
    const id = Date.now() + Math.random();
    setToasts((cur) => [...cur, { id, kind, message, ttl_ms }]);
    setTimeout(() => {
      setToasts((cur) => cur.filter((t) => t.id !== id));
    }, ttl_ms);
  }, []);

  const api: ToastApi = {
    push,
    success: (m) => push('success', m),
    error: (m) => push('error', m, 6000),
    info: (m) => push('info', m),
    warning: (m) => push('warning', m, 5000),
  };

  const remove = (id: number) => setToasts((cur) => cur.filter((t) => t.id !== id));

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 max-w-md">
        {toasts.map((t) => {
          const colour =
            t.kind === 'success' ? 'border-vm-success text-vm-success' :
            t.kind === 'error' ? 'border-vm-danger text-vm-danger' :
            t.kind === 'warning' ? 'border-vm-warning text-vm-warning' :
            'border-vm-accent text-vm-accent';
          const Icon =
            t.kind === 'success' ? CheckCircle2 :
            t.kind === 'error' ? AlertTriangle :
            t.kind === 'warning' ? AlertTriangle : Info;
          return (
            <div
              key={t.id}
              className={`bg-vm-surface2 border ${colour} rounded shadow-2xl p-3 pr-2 flex items-start gap-2 animate-in fade-in slide-in-from-right-2`}
            >
              <Icon className="w-4 h-4 mt-0.5 shrink-0" />
              <div className="flex-1 font-mono text-xs text-vm-text-bright break-words">{t.message}</div>
              <button
                onClick={() => remove(t.id)}
                className="text-vm-text-dim hover:text-vm-text-bright shrink-0"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // Fallback that no-ops + console.warn so missing provider doesn't crash.
    return {
      push: (k, m) => console.warn('[toast]', k, m),
      success: (m) => console.warn('[toast.success]', m),
      error: (m) => console.warn('[toast.error]', m),
      info: (m) => console.warn('[toast.info]', m),
      warning: (m) => console.warn('[toast.warning]', m),
    };
  }
  return ctx;
}
