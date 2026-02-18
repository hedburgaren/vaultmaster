'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { login, getSetupStatus } from '@/lib/api';
import { Lock } from 'lucide-react';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  useEffect(() => {
    getSetupStatus()
      .then((res) => { if (res.needs_setup) router.replace('/setup'); })
      .catch(() => {});
  }, [router]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      await login(username, password);
      router.push('/dashboard');
    } catch (err: any) {
      setError(err.message || 'Login failed');
    }
    setLoading(false);
  };

  return (
    <div className="min-h-screen flex items-center justify-center relative z-[1]">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-16 h-16 mx-auto mb-4 border-2 border-vm-accent flex items-center justify-center bg-vm-accent/10 glow" style={{ clipPath: 'polygon(10% 0%, 90% 0%, 100% 10%, 100% 90%, 90% 100%, 10% 100%, 0% 90%, 0% 10%)' }}>
            <Lock className="w-8 h-8 text-vm-accent" />
          </div>
          <h1 className="font-code text-2xl font-bold text-vm-text-bright tracking-[6px] uppercase">VAULTMASTER</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[3px] mt-1">BACKUP CONTROL CENTER</div>
        </div>

        <form onSubmit={handleLogin} className="bg-vm-surface border border-vm-border rounded-lg p-8">
          {error && (
            <div className="mb-4 p-3 bg-vm-danger/10 border border-vm-danger/30 rounded text-vm-danger font-mono text-sm">{error}</div>
          )}
          <div className="mb-5">
            <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Username</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)} className="w-full bg-vm-surface2 border border-vm-border rounded px-4 py-3 text-vm-text font-mono text-sm outline-none focus:border-vm-accent transition-colors" placeholder="admin" autoFocus />
          </div>
          <div className="mb-6">
            <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} className="w-full bg-vm-surface2 border border-vm-border rounded px-4 py-3 text-vm-text font-mono text-sm outline-none focus:border-vm-accent transition-colors" />
          </div>
          <button type="submit" disabled={loading} className="w-full py-3 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-[3px] uppercase hover:bg-[#33ddff] transition-all glow disabled:opacity-50">
            {loading ? 'Logging in...' : 'Log in'}
          </button>
        </form>
      </div>
    </div>
  );
}
