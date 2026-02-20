'use client';

import { useEffect, useState, useMemo } from 'react';
import { getServers, createServer, updateServer, deleteServer, testServer, testConnectionPresave } from '@/lib/api';
import { formatRelative } from '@/lib/utils';
import { useT } from '@/lib/i18n';
import Badge from '@/components/Badge';
import FormLabel from '@/components/FormLabel';
import TagInput from '@/components/TagInput';
import { Plus, Trash2, TestTube, Server, Eye, EyeOff, Pencil, X, Wifi } from 'lucide-react';

const INPUT = "w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent";

const emptyForm = { name: '', host: '', port: 22, auth_type: 'ssh_key', provider: 'custom', ssh_user: '', ssh_key_path: '/root/.ssh/vaultmaster_ed25519', ssh_password: '', api_token: '', tags: [] as string[], use_sudo: true };

export default function ServersPage() {
  const t = useT();
  const [servers, setServers] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState({ ...emptyForm });
  const [showSecret, setShowSecret] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, any>>({});
  const [formTestResult, setFormTestResult] = useState<any>(null);
  const [formTesting, setFormTesting] = useState(false);

  const load = () => getServers().then(setServers).catch(() => {});
  useEffect(() => { load(); }, []);

  const allTags = useMemo(() => {
    const set = new Set<string>();
    servers.forEach(s => s.tags?.forEach((t: string) => set.add(t)));
    return Array.from(set).sort();
  }, [servers]);

  const openNew = () => { setEditId(null); setForm({ ...emptyForm }); setShowForm(true); setFormTestResult(null); };
  const openEdit = (s: any) => {
    setEditId(s.id);
    setForm({ name: s.name, host: s.host, port: s.port, auth_type: s.auth_type, provider: s.provider || 'custom', ssh_user: s.ssh_user || '', ssh_key_path: s.ssh_key_path || '/root/.ssh/vaultmaster_ed25519', ssh_password: '', api_token: '', tags: s.tags || [], use_sudo: s.meta?.use_sudo ?? true });
    setShowForm(true);
    setFormTestResult(null);
  };
  const closeForm = () => { setShowForm(false); setEditId(null); setFormTestResult(null); };

  const buildPayload = () => {
    const payload: any = { name: form.name, host: form.host, port: Number(form.port), auth_type: form.auth_type, provider: form.provider, ssh_user: form.ssh_user || 'root', tags: form.tags, meta: { use_sudo: form.use_sudo } };
    if (form.auth_type === 'ssh_key') payload.ssh_key_path = form.ssh_key_path;
    if (form.auth_type === 'ssh_password') payload.meta = { ...payload.meta, ssh_password: form.ssh_password };
    if (form.auth_type === 'api') payload.api_token = form.api_token;
    return payload;
  };

  const handleSave = async () => {
    if (editId) {
      await updateServer(editId, buildPayload());
    } else {
      await createServer(buildPayload());
    }
    closeForm();
    load();
  };

  const handleFormTest = async () => {
    setFormTesting(true);
    setFormTestResult(null);
    try {
      const res = await testConnectionPresave({ host: form.host, port: Number(form.port), auth_type: form.auth_type, ssh_user: form.ssh_user, ssh_key_path: form.ssh_key_path || undefined });
      setFormTestResult(res);
    } catch (e: any) {
      setFormTestResult({ success: false, message: e.message });
    }
    setFormTesting(false);
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    try {
      const res = await testServer(id);
      setTestResult(prev => ({ ...prev, [id]: res }));
    } catch (e: any) {
      setTestResult(prev => ({ ...prev, [id]: { success: false, message: e.message } }));
    }
    setTesting(null);
  };

  const handleDelete = async (id: string) => {
    if (confirm(t('servers.confirm_delete'))) { await deleteServer(id); load(); }
  };

  const serverForm = (
    <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-bold text-vm-text-bright uppercase tracking-wider">{editId ? t('servers.edit') : t('servers.new')}</h3>
        <button onClick={closeForm} className="text-vm-text-dim hover:text-vm-text"><X className="w-5 h-5" /></button>
      </div>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <FormLabel label={t('servers.name')} tooltip={t('servers.name_tip')} />
          <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} className={INPUT} placeholder="my-server" />
        </div>
        <div>
          <FormLabel label={t('servers.host')} tooltip={t('servers.host_tip')} />
          <input value={form.host} onChange={e => setForm({...form, host: e.target.value})} className={INPUT} placeholder="192.168.1.42" />
        </div>
        <div>
          <FormLabel label={t('servers.ssh_user')} tooltip={t('servers.ssh_user_tip')} />
          <input value={form.ssh_user} onChange={e => setForm({...form, ssh_user: e.target.value})} className={INPUT} placeholder="root" />
        </div>
        <div>
          <FormLabel label={t('servers.ssh_port')} tooltip={t('servers.ssh_port_tip')} />
          <input type="number" value={form.port} onChange={e => setForm({...form, port: Number(e.target.value)})} className={INPUT} />
        </div>
        <div>
          <FormLabel label={t('servers.auth_type')} tooltip={t('servers.auth_type_tip')} />
          <select value={form.auth_type} onChange={e => setForm({...form, auth_type: e.target.value})} className={INPUT}>
            <option value="ssh_key">SSH Key</option>
            <option value="ssh_password">SSH Password</option>
            <option value="api">API Token</option>
            <option value="local">Local (no SSH)</option>
          </select>
        </div>
        <div>
          <FormLabel label={t('servers.provider')} tooltip={t('servers.provider_tip')} />
          <select value={form.provider} onChange={e => setForm({...form, provider: e.target.value})} className={INPUT}>
            <option value="custom">Custom / Bare Metal</option>
            <option value="digitalocean">DigitalOcean</option>
            <option value="hetzner">Hetzner</option>
            <option value="linode">Linode</option>
            <option value="aws">AWS</option>
          </select>
        </div>

        {form.auth_type === 'ssh_key' && (
          <div className="col-span-2">
            <FormLabel label={t('servers.ssh_key_path')} tooltip={t('servers.ssh_key_path_tip')} />
            <input value={form.ssh_key_path} onChange={e => setForm({...form, ssh_key_path: e.target.value})} className={INPUT} placeholder="/root/.ssh/id_ed25519" />
          </div>
        )}
        {form.auth_type === 'ssh_password' && (
          <div className="col-span-2">
            <FormLabel label={t('servers.ssh_password')} tooltip={t('servers.ssh_password_tip')} />
            <div className="relative">
              <input type={showSecret ? 'text' : 'password'} value={form.ssh_password} onChange={e => setForm({...form, ssh_password: e.target.value})} className={INPUT + ' pr-10'} placeholder="Enter SSH password" />
              <button type="button" onClick={() => setShowSecret(!showSecret)} className="absolute right-3 top-1/2 -translate-y-1/2 text-vm-text-dim hover:text-vm-accent">
                {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
        )}
        {form.auth_type === 'api' && (
          <div className="col-span-2">
            <FormLabel label={t('servers.api_token')} tooltip={t('servers.api_token_tip')} />
            <div className="relative">
              <input type={showSecret ? 'text' : 'password'} value={form.api_token} onChange={e => setForm({...form, api_token: e.target.value})} className={INPUT + ' pr-10'} placeholder="Enter API token" />
              <button type="button" onClick={() => setShowSecret(!showSecret)} className="absolute right-3 top-1/2 -translate-y-1/2 text-vm-text-dim hover:text-vm-accent">
                {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
        )}

        {form.auth_type !== 'local' && form.auth_type !== 'api' && (
          <div className="col-span-2 flex items-center gap-3">
            <button type="button" onClick={() => setForm({...form, use_sudo: !form.use_sudo})}
              className={`flex items-center gap-2 px-4 py-2 rounded border text-sm font-bold tracking-wider uppercase transition-all ${form.use_sudo ? 'bg-vm-accent/10 border-vm-accent text-vm-accent' : 'bg-vm-surface2 border-vm-border text-vm-text-dim hover:border-vm-accent'}`}>
              {form.use_sudo ? '✓ ' : ''}{t('servers.use_sudo')}
            </button>
            <span className="font-mono text-[10px] text-vm-text-dim">{t('servers.use_sudo_tip')}</span>
          </div>
        )}

        <div className="col-span-2">
          <FormLabel label={t('servers.tags')} tooltip={t('servers.tags_tip')} />
          <TagInput value={form.tags} onChange={tags => setForm({...form, tags})} suggestions={allTags} placeholder="docker, postgresql, odoo" />
        </div>
      </div>

      {formTestResult && (
        <div className={`font-mono text-xs p-2.5 rounded mb-4 ${formTestResult.success ? 'bg-vm-success/10 text-vm-success border border-vm-success/30' : 'bg-vm-danger/10 text-vm-danger border border-vm-danger/30'}`}>
          {formTestResult.message}
        </div>
      )}

      <div className="flex gap-3">
        <button onClick={handleSave} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">{editId ? t('action.update') : t('action.save')}</button>
        <button onClick={handleFormTest} disabled={formTesting || !form.host} className="flex items-center gap-1.5 px-4 py-2.5 border border-vm-accent text-vm-accent rounded font-bold text-sm tracking-wider uppercase hover:bg-vm-accent/[0.08] disabled:opacity-50">
          <Wifi className="w-4 h-4" /> {formTesting ? t('action.testing') : t('servers.test_connection')}
        </button>
        <button onClick={closeForm} className="px-4 py-2.5 text-vm-text-dim font-bold text-sm tracking-wider uppercase hover:text-vm-text">{t('action.cancel')}</button>
      </div>
    </div>
  );

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">{t('servers.title')}</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">{t('servers.subtitle_prefix')} {servers.length} {t('common.total')}</div>
        </div>
        <button onClick={openNew} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase hover:bg-[#33ddff] transition-all glow">
          <Plus className="w-4 h-4" /> {t('servers.add')}
        </button>
      </div>

      {showForm && serverForm}

      <div className="grid grid-cols-2 gap-4">
        {servers.map((s: any) => (
          <div key={s.id} className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright hover:-translate-y-0.5 transition-all">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-11 h-11 bg-vm-accent/[0.08] border border-vm-border-bright rounded flex items-center justify-center">
                <Server className="w-5 h-5 text-vm-accent" />
              </div>
              <div className="flex-1">
                <div className="text-lg font-bold text-vm-text-bright">{s.name}</div>
                <div className="font-mono text-[11px] text-vm-text-dim">{s.host}:{s.port} · {s.auth_type}</div>
              </div>
              <div className="flex items-center gap-1.5 font-mono text-[11px]">
                {s.is_active && s.last_seen ? (
                  <><div className="w-2 h-2 rounded-full bg-vm-success shadow-[0_0_8px_theme(colors.vm.success)] animate-pulse-glow" /><span className="text-vm-success">ONLINE</span></>
                ) : (
                  <><div className="w-2 h-2 rounded-full bg-vm-danger" /><span className="text-vm-danger">OFFLINE</span></>
                )}
              </div>
            </div>
            {s.tags?.length > 0 && (
              <div className="flex gap-1.5 flex-wrap mb-4">
                {s.tags.map((t: string) => (
                  <span key={t} className="font-mono text-[10px] px-2.5 py-0.5 rounded-sm border border-vm-accent/40 bg-vm-accent/[0.08] text-vm-accent uppercase tracking-wider">{t}</span>
                ))}
              </div>
            )}
            <div className="font-mono text-[11px] text-vm-text-dim mb-3">{t('servers.last_seen')}: {formatRelative(s.last_seen)}</div>
            {testResult[s.id] && (
              <div className={`font-mono text-xs p-2 rounded mb-3 ${testResult[s.id].success ? 'bg-vm-success/10 text-vm-success border border-vm-success/30' : 'bg-vm-danger/10 text-vm-danger border border-vm-danger/30'}`}>
                {testResult[s.id].message}
              </div>
            )}
            <div className="flex gap-2">
              <button onClick={() => openEdit(s)} className="flex items-center gap-1.5 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08] transition-all">
                <Pencil className="w-3.5 h-3.5" /> {t('action.edit')}
              </button>
              <button onClick={() => handleTest(s.id)} disabled={testing === s.id} className="flex items-center gap-1.5 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08] transition-all disabled:opacity-50">
                <TestTube className="w-3.5 h-3.5" /> {testing === s.id ? t('action.testing') : t('action.test')}
              </button>
              <button onClick={() => handleDelete(s.id)} className="flex items-center gap-1.5 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10 transition-all">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        ))}
        {servers.length === 0 && (
          <div className="col-span-2 text-center py-12 text-vm-text-dim font-mono">
            <Server className="w-12 h-12 mx-auto mb-3 opacity-40" />
            <div className="tracking-[2px]">{t('servers.none')}</div>
          </div>
        )}
      </div>
    </div>
  );
}
