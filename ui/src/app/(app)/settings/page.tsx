'use client';

import { useEffect, useState } from 'react';
import {
  getRetentionPolicies, createRetentionPolicy, deleteRetentionPolicy, previewRotation,
  getProfile, updateProfile, changePassword, generateApiKey, revokeApiKey,
  getSSHKeys, generateSSHKey,
} from '@/lib/api';
import { Plus, Trash2, Eye, Settings, User, Key, Mail, Lock, Copy, RefreshCw, KeyRound, Sparkles, Rocket, BarChart3, Globe2, Puzzle, Zap, Shield } from 'lucide-react';
import FormLabel from '@/components/FormLabel';
import { useT, useLocale, type Locale } from '@/lib/i18n';

export default function SettingsPage() {
  const t = useT();
  const [locale] = useLocale();
  const [tab, setTab] = useState<'profile' | 'retention' | 'ssh' | 'coming'>('profile');

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

  // SSH keys state
  const [sshKeys, setSshKeys] = useState<any[]>([]);
  const [sshGenerating, setSshGenerating] = useState(false);
  const [sshCopied, setSshCopied] = useState<string | null>(null);

  const loadProfile = () => getProfile().then((p: any) => { setProfile(p); setEmails(p.email_addresses || []); }).catch(() => {});
  const loadPolicies = () => getRetentionPolicies().then(setPolicies).catch(() => {});
  const loadSSHKeys = () => getSSHKeys().then(setSshKeys).catch(() => {});

  useEffect(() => { loadProfile(); loadPolicies(); loadSSHKeys(); }, []);

  const handleAddEmail = () => {
    if (newEmail && !emails.includes(newEmail)) {
      const updated = [...emails, newEmail];
      setEmails(updated);
      setNewEmail('');
      updateProfile({ email_addresses: updated }).then(() => { setProfileMsg(t('settings.emails_updated')); loadProfile(); setTimeout(() => setProfileMsg(''), 3000); });
    }
  };

  const handleRemoveEmail = (email: string) => {
    const updated = emails.filter(e => e !== email);
    setEmails(updated);
    updateProfile({ email_addresses: updated }).then(() => { setProfileMsg(t('settings.email_removed')); loadProfile(); setTimeout(() => setProfileMsg(''), 3000); });
  };

  const handleChangePassword = async () => {
    setPwMsg('');
    if (pwForm.new !== pwForm.confirm) { setPwMsg(t('settings.pw_mismatch')); return; }
    if (pwForm.new.length < 8) { setPwMsg(t('settings.pw_too_short')); return; }
    try {
      await changePassword(pwForm.current, pwForm.new);
      setPwMsg(t('settings.pw_changed'));
      setPwForm({ current: '', new: '', confirm: '' });
    } catch (e: any) { setPwMsg(e.message); }
    setTimeout(() => setPwMsg(''), 5000);
  };

  const handleGenerateApiKey = async () => {
    try {
      const res = await generateApiKey();
      setApiKey(res.api_key);
      setApiKeyMsg(t('settings.api_key_generated'));
      loadProfile();
    } catch (e: any) { setApiKeyMsg(e.message); }
  };

  const handleRevokeApiKey = async () => {
    if (confirm(t('settings.api_key_confirm_revoke'))) {
      await revokeApiKey();
      setApiKey(null);
      setApiKeyMsg(t('settings.api_key_revoked'));
      loadProfile();
      setTimeout(() => setApiKeyMsg(''), 3000);
    }
  };

  const handleGenerateSSHKey = async () => {
    setSshGenerating(true);
    try {
      await generateSSHKey();
      loadSSHKeys();
    } catch (e: any) { /* ignore */ }
    setSshGenerating(false);
  };

  const copyPubKey = (key: string, name: string) => {
    navigator.clipboard.writeText(key);
    setSshCopied(name);
    setTimeout(() => setSshCopied(null), 2000);
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
        <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">{t('settings.title')}</h1>
        <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">{t('settings.subtitle')}</div>
      </div>

      <div className="flex gap-1 border-b border-vm-border mb-6">
        <button onClick={() => setTab('profile')} className={tabClass('profile')}><User className="w-4 h-4 inline mr-1.5" />{t('settings.tab_profile')}</button>
        <button onClick={() => setTab('retention')} className={tabClass('retention')}><Settings className="w-4 h-4 inline mr-1.5" />{t('settings.tab_retention')}</button>
        <button onClick={() => setTab('ssh')} className={tabClass('ssh')}><KeyRound className="w-4 h-4 inline mr-1.5" />{t('settings.tab_ssh')}</button>
        <button onClick={() => setTab('coming')} className={tabClass('coming')}><Sparkles className="w-4 h-4 inline mr-1.5" />{t('settings.tab_coming')}</button>
      </div>

      {tab === 'profile' && profile && (
        <div className="space-y-6">
          {/* Account info */}
          <div className="bg-vm-surface border border-vm-border rounded p-6">
            <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider flex items-center gap-2"><User className="w-5 h-5 text-vm-accent" /> {t('settings.account')}</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-1">{t('settings.username')}</div>
                <div className="font-mono text-sm text-vm-text-bright">{profile.username}</div>
              </div>
              <div>
                <div className="font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-1">{t('settings.role')}</div>
                <div className="font-mono text-sm text-vm-text-bright">{profile.role === 'admin' || profile.is_admin ? t('settings.role_admin') : profile.role === 'operator' ? t('settings.role_operator') : t('settings.role_viewer')}</div>
              </div>
            </div>
          </div>

          {/* Email addresses */}
          <div className="bg-vm-surface border border-vm-border rounded p-6">
            <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider flex items-center gap-2"><Mail className="w-5 h-5 text-vm-accent" /> {t('settings.emails')}</h3>
            <div className="font-mono text-[11px] text-vm-text-dim mb-3">{t('settings.emails_desc')}</div>
            <div className="space-y-2 mb-4">
              {emails.map((email) => (
                <div key={email} className="flex items-center gap-2 bg-vm-surface2 border border-vm-border rounded px-3 py-2">
                  <span className="font-mono text-sm text-vm-text flex-1">{email}</span>
                  <button onClick={() => handleRemoveEmail(email)} className="text-vm-danger hover:text-red-400 text-xs font-bold">{t('action.remove')}</button>
                </div>
              ))}
              {emails.length === 0 && <div className="font-mono text-xs text-vm-text-dim">{t('settings.no_emails')}</div>}
            </div>
            <div className="flex gap-2">
              <input value={newEmail} onChange={e => setNewEmail(e.target.value)} placeholder="user@example.com" className="flex-1 bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" onKeyDown={e => e.key === 'Enter' && handleAddEmail()} />
              <button onClick={handleAddEmail} className="px-4 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">{t('action.add')}</button>
            </div>
            {profileMsg && <div className="mt-2 font-mono text-xs text-vm-success">{profileMsg}</div>}
          </div>

          {/* Change password */}
          <div className="bg-vm-surface border border-vm-border rounded p-6">
            <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider flex items-center gap-2"><Lock className="w-5 h-5 text-vm-accent" /> {t('settings.change_password')}</h3>
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div>
                <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">{t('settings.current_password')}</label>
                <input type="password" value={pwForm.current} onChange={e => setPwForm({...pwForm, current: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
              </div>
              <div>
                <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">{t('settings.new_password')}</label>
                <input type="password" value={pwForm.new} onChange={e => setPwForm({...pwForm, new: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
              </div>
              <div>
                <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">{t('settings.confirm_password')}</label>
                <input type="password" value={pwForm.confirm} onChange={e => setPwForm({...pwForm, confirm: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
              </div>
            </div>
            <button onClick={handleChangePassword} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">{t('settings.update_password')}</button>
            {pwMsg && <div className={`mt-2 font-mono text-xs ${pwMsg.includes('success') ? 'text-vm-success' : 'text-vm-danger'}`}>{pwMsg}</div>}
          </div>

          {/* API Key */}
          <div className="bg-vm-surface border border-vm-border rounded p-6">
            <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider flex items-center gap-2"><Key className="w-5 h-5 text-vm-accent" /> {t('settings.api_key')}</h3>
            <div className="font-mono text-[11px] text-vm-text-dim mb-3">{t('settings.api_key_desc')} <code className="text-vm-accent">X-API-Key</code> {t('settings.api_key_header')}</div>
            {profile.api_key_prefix ? (
              <div className="flex items-center gap-3 mb-4">
                <div className="bg-vm-surface2 border border-vm-border rounded px-4 py-2.5 font-mono text-sm text-vm-text flex-1">
                  {profile.api_key_prefix} <span className="text-vm-text-dim">••••••••••••</span>
                </div>
                <button onClick={handleRevokeApiKey} className="px-4 py-2.5 border border-vm-danger text-vm-danger rounded font-bold text-sm tracking-wider uppercase hover:bg-vm-danger/10">{t('action.revoke')}</button>
                <button onClick={handleGenerateApiKey} className="flex items-center gap-1.5 px-4 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase"><RefreshCw className="w-4 h-4" /> {t('action.regenerate')}</button>
              </div>
            ) : (
              <button onClick={handleGenerateApiKey} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase"><Key className="w-4 h-4" /> {t('settings.generate_api_key')}</button>
            )}
            {apiKey && (
              <div className="mt-3 p-3 bg-vm-success/10 border border-vm-success/30 rounded">
                <div className="font-mono text-[11px] text-vm-success mb-2 font-bold">{t('settings.api_key_copy_now')}</div>
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
              <Plus className="w-4 h-4" /> {t('settings.new_policy')}
            </button>
          </div>

          {showForm && (
            <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
              <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider">{t('settings.new_retention')}</h3>
              <div className="grid grid-cols-4 gap-4 mb-4">
                <div className="col-span-2">
                  <FormLabel label={t('settings.policy_name')} tooltip={t('settings.policy_name_tip')} />
                  <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" placeholder="PostgreSQL Critical" />
                </div>
                <div>
                  <FormLabel label={t('settings.hourly')} tooltip={t('settings.hourly_tip')} />
                  <input type="number" value={form.keep_hourly} onChange={e => setForm({...form, keep_hourly: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
                </div>
                <div>
                  <FormLabel label={t('settings.daily')} tooltip={t('settings.daily_tip')} />
                  <input type="number" value={form.keep_daily} onChange={e => setForm({...form, keep_daily: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
                </div>
                <div>
                  <FormLabel label={t('settings.weekly')} tooltip={t('settings.weekly_tip')} />
                  <input type="number" value={form.keep_weekly} onChange={e => setForm({...form, keep_weekly: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
                </div>
                <div>
                  <FormLabel label={t('settings.monthly')} tooltip={t('settings.monthly_tip')} />
                  <input type="number" value={form.keep_monthly} onChange={e => setForm({...form, keep_monthly: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
                </div>
                <div>
                  <FormLabel label={t('settings.yearly')} tooltip={t('settings.yearly_tip')} />
                  <input type="number" value={form.keep_yearly} onChange={e => setForm({...form, keep_yearly: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
                </div>
                <div>
                  <FormLabel label={t('settings.max_days')} tooltip={t('settings.max_days_tip')} />
                  <input type="number" value={form.max_age_days} onChange={e => setForm({...form, max_age_days: Number(e.target.value)})} className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent" />
                </div>
              </div>
              <button onClick={handleCreatePolicy} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">{t('action.save')}</button>
            </div>
          )}

          <div className="space-y-3">
            {policies.map((p: any) => (
              <div key={p.id} className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright transition-all">
                <div className="flex items-center justify-between mb-3">
                  <div className="font-semibold text-vm-text-bright text-lg">{p.name}</div>
                  <div className="flex gap-2">
                    <button onClick={() => handlePreview(p.id)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08]">
                      <Eye className="w-3 h-3" /> {t('action.preview')}
                    </button>
                    <button onClick={async () => { if (confirm(t('settings.confirm_delete_policy'))) { await deleteRetentionPolicy(p.id); loadPolicies(); }}} className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10">
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-6 gap-3">
                  {[[t('settings.hourly'), p.keep_hourly], [t('settings.daily'), p.keep_daily], [t('settings.weekly'), p.keep_weekly], [t('settings.monthly'), p.keep_monthly], [t('settings.yearly'), p.keep_yearly], [t('settings.max_days'), p.max_age_days]].map(([label, val]) => (
                    <div key={label as string} className="text-center p-2.5 bg-vm-surface2 rounded border border-vm-border">
                      <div className="font-code text-lg font-bold text-vm-accent">{val}</div>
                      <div className="font-mono text-[10px] text-vm-text-dim mt-0.5">{label}</div>
                    </div>
                  ))}
                </div>
                {previews[p.id] && (
                  <div className="mt-3 p-3 bg-vm-surface2 rounded border border-vm-border font-mono text-xs text-vm-text-dim">
                    {t('settings.total_artifacts')}: {previews[p.id].total_artifacts} · {t('settings.would_keep')}: {previews[p.id].would_keep} · {t('settings.would_delete')}: <span className="text-vm-danger">{previews[p.id].would_delete}</span>
                  </div>
                )}
              </div>
            ))}
            {policies.length === 0 && (
              <div className="text-center py-12 text-vm-text-dim font-mono">
                <Settings className="w-12 h-12 mx-auto mb-3 opacity-40" />
                <div className="tracking-[2px]">{t('settings.no_policies')}</div>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === 'ssh' && (
        <div>
          <div className="bg-vm-surface border border-vm-border rounded p-6 mb-6">
            <h3 className="text-lg font-bold text-vm-text-bright mb-2 uppercase tracking-wider flex items-center gap-2"><KeyRound className="w-5 h-5 text-vm-accent" /> {t('ssh.title')}</h3>
            <div className="font-mono text-[11px] text-vm-text-dim mb-6">{t('ssh.desc')}</div>

            {sshKeys.length === 0 ? (
              <div className="text-center py-8 text-vm-text-dim font-mono">
                <KeyRound className="w-12 h-12 mx-auto mb-3 opacity-40" />
                <div className="tracking-[2px] mb-4">{t('ssh.no_keys')}</div>
              </div>
            ) : (
              <div className="space-y-4 mb-6">
                {sshKeys.map((k: any) => (
                  <div key={k.name} className="bg-vm-surface2 border border-vm-border rounded p-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="font-mono text-sm font-bold text-vm-text-bright">{k.name}</div>
                      <div className="font-mono text-[10px] text-vm-text-dim">{k.path}</div>
                    </div>
                    {k.public_key && (
                      <div>
                        <div className="font-mono text-[10px] text-vm-text-dim mb-1.5">{t('ssh.public_key')}:</div>
                        <div className="flex gap-2">
                          <code className="flex-1 font-mono text-[11px] text-vm-accent bg-vm-surface border border-vm-border rounded px-3 py-2 break-all select-all">{k.public_key}</code>
                          <button onClick={() => copyPubKey(k.public_key, k.name)} className="px-3 py-2 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08] shrink-0">
                            {sshCopied === k.name ? <span className="text-vm-success">{t('ssh.copied')}</span> : <><Copy className="w-3.5 h-3.5 inline mr-1" />{t('action.copy')}</>}
                          </button>
                        </div>
                        <div className="font-mono text-[10px] text-vm-text-dim mt-2">{t('ssh.copy_instruction')}</div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            <button onClick={handleGenerateSSHKey} disabled={sshGenerating} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase disabled:opacity-50">
              <KeyRound className="w-4 h-4" /> {sshGenerating ? t('ssh.generating') : t('ssh.generate')}
            </button>
          </div>
        </div>
      )}

      {tab === 'coming' && (
        <div>
          <div className="mb-6">
            <div className="font-mono text-[11px] text-vm-text-dim">{t('coming.desc')}</div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            {[
              { icon: Globe2, title: { sv: 'WordPress-hantering', en: 'WordPress Management' }, desc: { sv: 'Hantera WordPress-installationer direkt från VaultMaster. Uppdatera plugins, teman och kärna. Övervaka säkerhet och prestanda — som ManageWP, fast integrerat.', en: 'Manage WordPress installations directly from VaultMaster. Update plugins, themes, and core. Monitor security and performance — like ManageWP, but integrated.' } },
              { icon: Puzzle, title: { sv: 'Marketplace för plugins', en: 'Plugin Marketplace' }, desc: { sv: 'Installera community-plugins för nya backuptyper, lagringsbackends och notifieringskanaler. Bygg egna plugins med det öppna API:et.', en: 'Install community plugins for new backup types, storage backends, and notification channels. Build your own plugins with the open API.' } },
              { icon: BarChart3, title: { sv: 'Avancerad analys & rapporter', en: 'Advanced Analytics & Reports' }, desc: { sv: 'Detaljerade rapporter om backupstorlek över tid, trender, kostnadsuppskattningar och SLA-uppfyllnad. Exportera som PDF eller skicka via e-post.', en: 'Detailed reports on backup size over time, trends, cost estimates, and SLA compliance. Export as PDF or send via email.' } },
              { icon: Shield, title: { sv: 'Automatisk säkerhetsskanning', en: 'Automated Security Scanning' }, desc: { sv: 'Skanna servrar efter kända sårbarheter, öppna portar och föråldrad mjukvara. Få rekommendationer direkt i dashboarden.', en: 'Scan servers for known vulnerabilities, open ports, and outdated software. Get recommendations directly in the dashboard.' } },
              { icon: Zap, title: { sv: 'Inkrementella backuper', en: 'Incremental Backups' }, desc: { sv: 'Spara tid och lagring med inkrementella backuper som bara kopierar ändrade filer sedan senaste körningen. Stöd för rsync och restic.', en: 'Save time and storage with incremental backups that only copy changed files since the last run. Support for rsync and restic.' } },
              { icon: Rocket, title: { sv: 'Disaster Recovery-plan', en: 'Disaster Recovery Plan' }, desc: { sv: 'Skapa och testa automatiserade återställningsplaner. Verifiera att backuper kan återställas med schemalagda teståterställningar.', en: 'Create and test automated recovery plans. Verify that backups can be restored with scheduled test restores.' } },
              { icon: Globe2, title: { sv: 'Multi-site dashboard', en: 'Multi-site Dashboard' }, desc: { sv: 'Hantera flera VaultMaster-instanser från ett centralt gränssnitt. Perfekt för byråer och managed hosting-leverantörer.', en: 'Manage multiple VaultMaster instances from a central interface. Perfect for agencies and managed hosting providers.' } },
              { icon: Sparkles, title: { sv: 'AI-driven anomalidetektering', en: 'AI-powered Anomaly Detection' }, desc: { sv: 'Automatisk identifiering av ovanliga backupmönster, storleksavvikelser och misslyckanden innan de blir kritiska.', en: 'Automatic identification of unusual backup patterns, size anomalies, and failures before they become critical.' } },
            ].map((feature, i) => (
              <div key={i} className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright hover:-translate-y-0.5 transition-all">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-10 h-10 rounded bg-vm-accent/10 flex items-center justify-center">
                    <feature.icon className="w-5 h-5 text-vm-accent" />
                  </div>
                  <div className="flex-1">
                    <div className="font-semibold text-vm-text-bright">{feature.title[locale]}</div>
                  </div>
                  <span className="font-mono text-[9px] px-2 py-0.5 rounded-sm border border-vm-accent/30 bg-vm-accent/[0.06] text-vm-accent uppercase tracking-wider">{t('coming.planned')}</span>
                </div>
                <div className="font-mono text-[11px] text-vm-text-dim leading-relaxed">{feature.desc[locale]}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
