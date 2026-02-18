'use client';

import { useEffect, useState } from 'react';
import {
  getRetentionPolicies, createRetentionPolicy, deleteRetentionPolicy, previewRotation,
  getProfile, updateProfile, changePassword, generateApiKey, revokeApiKey,
} from '@/lib/api';
import { Plus, Trash2, Eye, Settings, User, Key, Mail, Lock, Copy, RefreshCw } from 'lucide-react';
import FormLabel from '@/components/FormLabel';

export default function SettingsPage() {
  const [tab, setTab] = useState<'profile' | 'retention'>('profile');

  // Profile state
  const [profile, setProfile] = useState<any>(null);
  const [emails, setEmails] = useState<string[]>([]);
  const [newEmail, setNewEmail] = useState('');
  const [pwForm, setPwForm] = useState({ current: '', new: '', confirm: '' });
  const [pwMsg, setPwMsg] = useState('');
  const [profileMsg, setProfileMsg] = useState('');
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [apiKeyMsg, setApiKeyMsg] = useState('');

  // Retention state
  const [policies, setPolicies] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', keep_hourly: 0, keep_daily: 7, keep_weekly: 4, keep_monthly: 3, keep_yearly: 0, max_age_days: 365 });
  const [previews, setPreviews] = useState<Record<string, any>>({});

  const loadProfile = () => getProfile().then((p: any) => { setProfile(p); setEmails(p.email_addresses || []); }).catch(() => {});
  const loadPolicies = () => getRetentionPolicies().then(setPolicies).catch(() => {});

  useEffect(() => { loadProfile(); loadPolicies(); }, []);

  const handleAddEmail = () => {
    if (newEmail && !emails.includes(newEmail)) {
      const updated = [...emails, newEmail];
      setEmails(updated);
      setNewEmail('');
      updateProfile({ email_addresses: updated }).then(() => { setProfileMsg('Emails updated'); loadProfile(); setTimeout(() => setProfileMsg(''), 3000); });
    }
  };

  const handleRemoveEmail = (email: string) => {
    const updated = emails.filter(e => e !== email);
    setEmails(updated);
    updateProfile({ email_addresses: updated }).then(() => { setProfileMsg('Email removed'); loadProfile(); setTimeout(() => setProfileMsg(''), 3000); });
  };

  const handleChangePassword = async () => {
    setPwMsg('');
    if (pwForm.new !== pwForm.confirm) { setPwMsg('Passwords do not match'); return; }
    if (pwForm.new.length < 8) { setPwMsg('Password must be at least 8 characters'); return; }
    try {
      await changePassword(pwForm.current, pwForm.new);
      setPwMsg('Password changed successfully');
      setPwForm({ current: '', new: '', confirm: '' });
    } catch (e: any) { setPwMsg(e.message); }
    setTimeout(() => setPwMsg(''), 5000);
  };

  const handleGenerateApiKey = async () => {
    try {
      const res = await generateApiKey();
      setApiKey(res.api_key);
      setApiKeyMsg('Key generated — copy it now, it will not be shown again.');
      loadProfile();
    } catch (e: any) { setApiKeyMsg(e.message); }
  };

  const handleRevokeApiKey = async () => {
    if (confirm('Revoke API key? Any integrations using it will stop working.')) {
      await revokeApiKey();
      setApiKey(null);
      setApiKeyMsg('API key revoked');
      loadProfile();
      setTimeout(() => setApiKeyMsg(''), 3000);
    }
  };

  const handleCreatePolicy = async () => {
    await createRetentionPolicy({ ...form, keep_hourly: Number(form.keep_hourly), keep_daily: Number(form.keep_daily), keep_weekly: Number(form.keep_weekly), keep_monthly: Number(form.keep_monthly), keep_yearly: Number(form.keep_yearly), max_age_days: Number(form.max_age_days) });
    setShowForm(false); loadPolicies();
  };

  const handlePreview = async (id: string) => {
    const res = await previewRotation(id);
    setPreviews((p: any) => ({ ...p, [id]: res }));
  };

  const tabClass = (t: string) => `px-5 py-2.5 font-bold text-sm tracking-wider uppercase transition-all ${tab === t ? 'text-vm-accent border-b-2 border-vm-accent' : 'text-vm-text-dim hover:text-vm-text'}`;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">Settings</h1>
        <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">// PROFILE · API KEYS · RETENTION POLICIES</div>
      </div>

      <div className="flex gap-1 border-b border-vm-border mb-6">
        <button onClick={() => setTab('profile')} className={tabClass('profile')}><User className="w-4 h-4 inline mr-1.5" />Profile & API</button>
        <button onClick={() => setTab('retention')} className={tabClass('retention')}><Settings className="w-4 h-4 inline mr-1.5" />Retention</button>
      </div>

      {tab === 'profile' && profile && (
        <div className="space-y-6">
          {/* Account info */}
          <div className="bg-vm-surface border border-vm-border rounded p-6">
            <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider flex items-center gap-2"><User className="w-5 h-5 text-vm-accent" /> Account</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-1">Username</div>
                <div className="font-mono text-sm text-vm-text-bright">{profile.username}</div>
              </div>
              <div>
                <div className="font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-1">Role</div>
                <div className="font-mono text-sm text-vm-text-bright">{profile.role === 'admin' || profile.is_admin ? 'Administrator' : profile.role === 'operator' ? 'Operator' : 'Viewer'}</div>
              </div>
            </div>
          </div>

          {/* Email addresses */}
          <div className="bg-vm-surface border border-vm-border rounded p-6">
            <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider flex items-center gap-2"><Mail className="w-5 h-5 text-vm-accent" /> Email Addresses</h3>
            <div className="font-mono text-[11px] text-vm-text-dim mb-3">Used for backup notifications. You can add multiple addresses.</div>
            <div className="space-y-2 mb-4">
              {emails.map((email) => (
                <div key={email} className="flex items-center gap-2 bg-vm-surface2 border border-vm-border rounded px-3 py-2">
                  <span className="font-mono text-sm text-vm-text flex-1">{email}</span>
                  <button onClick={() => handleRemoveEmail(email)} className="text-vm-danger hover:text-red-400 text-xs font-bold">Remove</button>
                </div>
              ))}
              {emails.length === 0 && <div className="font-mono text-xs text-vm-text-dim">No email addresses configured</div>}
            </div>
            <div className="flex gap-2">
              <input value={newEmail} onChange={e => setNewEmail(e.target.value)} placeholder="user@example.com" className="flex-1 bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" onKeyDown={e => e.key === 'Enter' && handleAddEmail()} />
              <button onClick={handleAddEmail} className="px-4 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">Add</button>
            </div>
            {profileMsg && <div className="mt-2 font-mono text-xs text-vm-success">{profileMsg}</div>}
          </div>

          {/* Change password */}
          <div className="bg-vm-surface border border-vm-border rounded p-6">
            <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider flex items-center gap-2"><Lock className="w-5 h-5 text-vm-accent" /> Change Password</h3>
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div>
                <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Current Password</label>
                <input type="password" value={pwForm.current} onChange={e => setPwForm({...pwForm, current: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
              </div>
              <div>
                <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">New Password</label>
                <input type="password" value={pwForm.new} onChange={e => setPwForm({...pwForm, new: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
              </div>
              <div>
                <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">Confirm Password</label>
                <input type="password" value={pwForm.confirm} onChange={e => setPwForm({...pwForm, confirm: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
              </div>
            </div>
            <button onClick={handleChangePassword} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">Update Password</button>
            {pwMsg && <div className={`mt-2 font-mono text-xs ${pwMsg.includes('success') ? 'text-vm-success' : 'text-vm-danger'}`}>{pwMsg}</div>}
          </div>

          {/* API Key */}
          <div className="bg-vm-surface border border-vm-border rounded p-6">
            <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider flex items-center gap-2"><Key className="w-5 h-5 text-vm-accent" /> API Key</h3>
            <div className="font-mono text-[11px] text-vm-text-dim mb-3">Use an API key to authenticate external integrations (n8n, scripts, CI/CD). Pass it as <code className="text-vm-accent">X-API-Key</code> header.</div>
            {profile.api_key_prefix ? (
              <div className="flex items-center gap-3 mb-4">
                <div className="bg-vm-surface2 border border-vm-border rounded px-4 py-2.5 font-mono text-sm text-vm-text flex-1">
                  {profile.api_key_prefix} <span className="text-vm-text-dim">••••••••••••</span>
                </div>
                <button onClick={handleRevokeApiKey} className="px-4 py-2.5 border border-vm-danger text-vm-danger rounded font-bold text-sm tracking-wider uppercase hover:bg-vm-danger/10">Revoke</button>
                <button onClick={handleGenerateApiKey} className="flex items-center gap-1.5 px-4 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase"><RefreshCw className="w-4 h-4" /> Regenerate</button>
              </div>
            ) : (
              <button onClick={handleGenerateApiKey} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase"><Key className="w-4 h-4" /> Generate API Key</button>
            )}
            {apiKey && (
              <div className="mt-3 p-3 bg-vm-success/10 border border-vm-success/30 rounded">
                <div className="font-mono text-[11px] text-vm-success mb-2 font-bold">YOUR API KEY (copy now — shown only once):</div>
                <div className="flex items-center gap-2">
                  <code className="font-mono text-sm text-vm-text-bright bg-vm-surface2 px-3 py-2 rounded flex-1 select-all break-all">{apiKey}</code>
                  <button onClick={() => { navigator.clipboard.writeText(apiKey); }} className="px-3 py-2 border border-vm-accent text-vm-accent rounded text-xs font-bold"><Copy className="w-4 h-4" /></button>
                </div>
              </div>
            )}
            {apiKeyMsg && !apiKey && <div className="mt-2 font-mono text-xs text-vm-accent">{apiKeyMsg}</div>}
          </div>
        </div>
      )}

      {tab === 'retention' && (
        <div>
          <div className="flex justify-end mb-4">
            <button onClick={() => setShowForm(!showForm)} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase hover:bg-[#33ddff] transition-all glow">
              <Plus className="w-4 h-4" /> New Policy
            </button>
          </div>

          {showForm && (
            <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
              <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider">New Retention Policy (GFS)</h3>
              <div className="grid grid-cols-4 gap-4 mb-4">
                <div className="col-span-2">
                  <FormLabel label="Name" tooltip="A descriptive name for this retention policy, e.g. 'PostgreSQL Critical' or 'Weekly Files'." />
                  <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder="PostgreSQL Critical" />
                </div>
                <div>
                  <FormLabel label="Hourly" tooltip="Number of hourly backups to keep. Set to 0 to skip hourly retention." />
                  <input type="number" value={form.keep_hourly} onChange={e => setForm({...form, keep_hourly: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
                </div>
                <div>
                  <FormLabel label="Daily" tooltip="Number of daily backups to keep. The most recent backup each day is preserved." />
                  <input type="number" value={form.keep_daily} onChange={e => setForm({...form, keep_daily: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
                </div>
                <div>
                  <FormLabel label="Weekly" tooltip="Number of weekly backups to keep. The most recent backup each week is preserved." />
                  <input type="number" value={form.keep_weekly} onChange={e => setForm({...form, keep_weekly: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
                </div>
                <div>
                  <FormLabel label="Monthly" tooltip="Number of monthly backups to keep. The most recent backup each month is preserved." />
                  <input type="number" value={form.keep_monthly} onChange={e => setForm({...form, keep_monthly: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
                </div>
                <div>
                  <FormLabel label="Yearly" tooltip="Number of yearly backups to keep. The most recent backup each year is preserved." />
                  <input type="number" value={form.keep_yearly} onChange={e => setForm({...form, keep_yearly: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
                </div>
                <div>
                  <FormLabel label="Max Days" tooltip="Maximum age in days. Backups older than this are always deleted, regardless of GFS rules." />
                  <input type="number" value={form.max_age_days} onChange={e => setForm({...form, max_age_days: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
                </div>
              </div>
              <button onClick={handleCreatePolicy} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">Save</button>
            </div>
          )}

          <div className="space-y-3">
            {policies.map((p: any) => (
              <div key={p.id} className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright transition-all">
                <div className="flex items-center justify-between mb-3">
                  <div className="font-semibold text-vm-text-bright text-lg">{p.name}</div>
                  <div className="flex gap-2">
                    <button onClick={() => handlePreview(p.id)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08]">
                      <Eye className="w-3 h-3" /> Preview
                    </button>
                    <button onClick={async () => { if (confirm('Delete this policy?')) { await deleteRetentionPolicy(p.id); loadPolicies(); }}} className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10">
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-6 gap-3">
                  {[['Hourly', p.keep_hourly], ['Daily', p.keep_daily], ['Weekly', p.keep_weekly], ['Monthly', p.keep_monthly], ['Yearly', p.keep_yearly], ['Max Days', p.max_age_days]].map(([label, val]) => (
                    <div key={label as string} className="text-center p-2.5 bg-vm-surface2 rounded border border-vm-border">
                      <div className="font-code text-lg font-bold text-vm-accent">{val}</div>
                      <div className="font-mono text-[10px] text-vm-text-dim mt-0.5">{label}</div>
                    </div>
                  ))}
                </div>
                {previews[p.id] && (
                  <div className="mt-3 p-3 bg-vm-surface2 rounded border border-vm-border font-mono text-xs text-vm-text-dim">
                    Total: {previews[p.id].total_artifacts} · Keep: {previews[p.id].would_keep} · Delete: <span className="text-vm-danger">{previews[p.id].would_delete}</span>
                  </div>
                )}
              </div>
            ))}
            {policies.length === 0 && (
              <div className="text-center py-12 text-vm-text-dim font-mono">
                <Settings className="w-12 h-12 mx-auto mb-3 opacity-40" />
                <div className="tracking-[2px]">No retention policies configured</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
