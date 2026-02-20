'use client';

import { useEffect, useState } from 'react';
import { getUsers, createUser, updateUser, deleteUser } from '@/lib/api';
import Badge from '@/components/Badge';
import FormLabel from '@/components/FormLabel';
import { Plus, Trash2, Users, Shield, Eye, EyeOff } from 'lucide-react';
import { useT } from '@/lib/i18n';

const INPUT = "w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent";

const ROLE_COLORS: Record<string, string> = {
  admin: 'bg-vm-danger/10 border-vm-danger/30 text-vm-danger',
  operator: 'bg-vm-accent/10 border-vm-accent/30 text-vm-accent',
  viewer: 'bg-vm-surface3 border-vm-border text-vm-text-dim',
};

export default function UsersPage() {
  const t = useT();
  const [users, setUsers] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const [form, setForm] = useState({ username: '', password: '', role: 'viewer', email_addresses: '' });
  const [error, setError] = useState('');

  const load = () => getUsers().then(setUsers).catch((e: any) => {
    if (e.message?.includes('403')) setError('Admin access required');
  });
  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    setError('');
    try {
      await createUser({
        username: form.username,
        password: form.password,
        role: form.role,
        email_addresses: form.email_addresses ? form.email_addresses.split(',').map(e => e.trim()).filter(Boolean) : [],
      });
      setShowForm(false);
      setForm({ username: '', password: '', role: 'viewer', email_addresses: '' });
      load();
    } catch (e: any) { setError(e.message); }
  };

  const handleToggleActive = async (id: string, currentActive: boolean) => {
    await updateUser(id, { is_active: !currentActive });
    load();
  };

  const handleChangeRole = async (id: string, role: string) => {
    await updateUser(id, { role });
    load();
  };

  const handleDelete = async (id: string, username: string) => {
    if (confirm(t('users.confirm_delete').replace('{name}', username))) {
      try {
        await deleteUser(id);
        load();
      } catch (e: any) { setError(e.message); }
    }
  };

  if (error === 'Admin access required') {
    return (
      <div className="text-center py-20 text-vm-text-dim font-mono">
        <Shield className="w-16 h-16 mx-auto mb-4 opacity-40" />
        <div className="text-lg tracking-[2px]">{t('users.admin_required')}</div>
        <div className="text-[11px] mt-2">{t('users.admin_required_desc')}</div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">{t('users.title')}</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">{t('users.subtitle_prefix')} {users.length} {t('users.accounts')} · RBAC</div>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase hover:bg-[#33ddff] transition-all glow">
          <Plus className="w-4 h-4" /> {t('users.new')}
        </button>
      </div>

      {error && error !== 'Admin access required' && (
        <div className="mb-4 p-3 bg-vm-danger/10 border border-vm-danger/30 rounded font-mono text-xs text-vm-danger">{error}</div>
      )}

      {showForm && (
        <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
          <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider">{t('users.create')}</h3>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <FormLabel label={t('users.username')} tooltip={t('users.username_tip')} />
              <input value={form.username} onChange={e => setForm({...form, username: e.target.value})} className={INPUT} placeholder="johndoe" />
            </div>
            <div>
              <FormLabel label={t('users.password')} tooltip={t('users.password_tip')} />
              <div className="relative">
                <input type={showPw ? 'text' : 'password'} value={form.password} onChange={e => setForm({...form, password: e.target.value})} className={INPUT + ' pr-10'} placeholder={t('users.min_chars')} />
                <button type="button" onClick={() => setShowPw(!showPw)} className="absolute right-3 top-1/2 -translate-y-1/2 text-vm-text-dim hover:text-vm-accent">
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
            <div>
              <FormLabel label={t('users.role')} tooltip={t('users.role_tip')} />
              <select value={form.role} onChange={e => setForm({...form, role: e.target.value})} className={INPUT}>
                <option value="viewer">{t('users.viewer')}</option>
                <option value="operator">{t('users.operator')}</option>
                <option value="admin">{t('users.admin')}</option>
              </select>
            </div>
            <div>
              <FormLabel label={t('users.email')} tooltip={t('users.email_tip')} />
              <input value={form.email_addresses} onChange={e => setForm({...form, email_addresses: e.target.value})} className={INPUT} placeholder="user@example.com" />
            </div>
          </div>
          <button onClick={handleCreate} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">{t('action.create')}</button>
        </div>
      )}

      <div className="bg-vm-surface border border-vm-border rounded overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-vm-surface2 border-b border-vm-border">
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('users.col_user')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('users.col_role')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('users.col_status')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('users.col_2fa')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('users.col_api_key')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal">{t('users.col_created')}</th>
              <th className="px-4 py-3 text-left font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase font-normal"></th>
            </tr>
          </thead>
          <tbody>
            {users.map((u: any) => (
              <tr key={u.id} className="border-b border-vm-border/50 hover:bg-vm-surface2 transition-colors">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded bg-vm-accent/10 flex items-center justify-center text-vm-accent font-bold text-sm">
                      {u.username?.[0]?.toUpperCase() || '?'}
                    </div>
                    <div>
                      <div className="text-sm font-semibold text-vm-text-bright">{u.username}</div>
                      {u.email_addresses?.length > 0 && (
                        <div className="font-mono text-[10px] text-vm-text-dim">{u.email_addresses[0]}</div>
                      )}
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <select
                    value={u.role || (u.is_admin ? 'admin' : 'viewer')}
                    onChange={e => handleChangeRole(u.id, e.target.value)}
                    className={`px-2.5 py-1 rounded-sm font-mono text-[11px] tracking-wider font-bold border cursor-pointer ${ROLE_COLORS[u.role] || ROLE_COLORS.viewer}`}
                  >
                    <option value="viewer">VIEWER</option>
                    <option value="operator">OPERATOR</option>
                    <option value="admin">ADMIN</option>
                  </select>
                </td>
                <td className="px-4 py-3">
                  <button onClick={() => handleToggleActive(u.id, u.is_active)}>
                    <Badge status={u.is_active ? 'success' : 'cancelled'} label={u.is_active ? t('users.active') : t('users.disabled')} />
                  </button>
                </td>
                <td className="px-4 py-3">
                  <span className={`font-mono text-[10px] ${u.totp_enabled ? 'text-vm-success' : 'text-vm-text-dim'}`}>
                    {u.totp_enabled ? `✓ ${t('common.enabled')}` : '—'}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono text-[10px] text-vm-text-dim">
                  {u.api_key_prefix || '—'}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-vm-text-dim">
                  {u.created_at ? new Date(u.created_at).toLocaleDateString('en-GB') : '—'}
                </td>
                <td className="px-4 py-3">
                  <button onClick={() => handleDelete(u.id, u.username)} className="p-1.5 border border-vm-danger text-vm-danger rounded hover:bg-vm-danger/10 transition-colors">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {users.length === 0 && (
          <div className="text-center py-12 text-vm-text-dim font-mono">
            <Users className="w-12 h-12 mx-auto mb-3 opacity-40" />
            <div className="tracking-[2px]">{t('users.none')}</div>
          </div>
        )}
      </div>
    </div>
  );
}
