'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { getSetupStatus, setupAdmin } from '@/lib/api';
import { Shield } from 'lucide-react';
import { useT } from '@/lib/i18n';

export default function SetupPage() {
  const t = useT();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const router = useRouter();

  useEffect(() => {
    getSetupStatus()
      .then((res) => {
        if (!res.needs_setup) {
          router.replace('/login');
        } else {
          setChecking(false);
        }
      })
      .catch(() => setChecking(false));
  }, [router]);

  const handleSetup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (username.length < 2) {
      setError(t('setup.err_username'));
      return;
    }
    if (password.length < 8) {
      setError(t('setup.err_password'));
      return;
    }
    if (password !== confirmPassword) {
      setError(t('setup.err_mismatch'));
      return;
    }

    setLoading(true);
    try {
      await setupAdmin(username, password);
      router.push('/dashboard');
    } catch (err: any) {
      setError(err.message || t('setup.err_failed'));
    }
    setLoading(false);
  };

  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center relative z-[1]">
        <div className="font-mono text-vm-text-dim tracking-[3px] animate-pulse">{t('setup.checking')}</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center relative z-[1]">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-16 h-16 mx-auto mb-4 border-2 border-vm-success flex items-center justify-center bg-vm-success/10" style={{ clipPath: 'polygon(10% 0%, 90% 0%, 100% 10%, 100% 90%, 90% 100%, 10% 100%, 0% 90%, 0% 10%)' }}>
            <Shield className="w-8 h-8 text-vm-success" />
          </div>
          <h1 className="font-code text-2xl font-bold text-vm-text-bright tracking-[6px] uppercase">VAULTMASTER</h1>
          <div className="font-mono text-xs text-vm-success tracking-[3px] mt-1">{t('setup.title')}</div>
          <div className="font-mono text-[11px] text-vm-text-dim mt-3 max-w-xs mx-auto leading-relaxed">
            {t('setup.desc')}
          </div>
        </div>

        <form onSubmit={handleSetup} className="bg-vm-surface border border-vm-border rounded-lg p-8">
          {error && (
            <div className="mb-4 p-3 bg-vm-danger/10 border border-vm-danger/30 rounded text-vm-danger font-mono text-sm">{error}</div>
          )}
          <div className="mb-5">
            <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">{t('setup.admin_username')}</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)} className="w-full bg-vm-surface2 border border-vm-border rounded px-4 py-3 text-vm-text font-mono text-sm outline-none focus:border-vm-success transition-colors" placeholder="admin" autoFocus />
          </div>
          <div className="mb-5">
            <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">{t('setup.password')}</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} className="w-full bg-vm-surface2 border border-vm-border rounded px-4 py-3 text-vm-text font-mono text-sm outline-none focus:border-vm-success transition-colors" placeholder={t('setup.min_chars')} />
          </div>
          <div className="mb-6">
            <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">{t('setup.confirm_password')}</label>
            <input type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} className="w-full bg-vm-surface2 border border-vm-border rounded px-4 py-3 text-vm-text font-mono text-sm outline-none focus:border-vm-success transition-colors" />
          </div>
          <button type="submit" disabled={loading} className="w-full py-3 bg-vm-success text-vm-bg rounded font-bold text-sm tracking-[3px] uppercase hover:brightness-110 transition-all disabled:opacity-50">
            {loading ? t('setup.creating') : t('setup.submit')}
          </button>
        </form>
      </div>
    </div>
  );
}
