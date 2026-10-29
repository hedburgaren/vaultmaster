'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  getMcpClients, createMcpClient, updateMcpClient, deleteMcpClient, rotateMcpClientKey,
  getMcpClientGrants, putMcpClientGrants, getCredentialItems,
} from '@/lib/api';
import { useToast } from '@/components/Toast';
import { ConfirmModal } from '@/components/ConfirmModal';
import { Bot, Plus, KeyRound, Trash2, X, Copy, ShieldCheck, Pencil, ChevronRight, ChevronDown } from 'lucide-react';
import { useT } from '@/lib/i18n';

interface McpClient {
  id: string;
  name: string;
  description: string | null;
  key_prefix: string | null;
  scopes: string[] | null;
  is_active: boolean;
  rate_limit_per_minute: number;
  last_used_at: string | null;
  use_count: number;
  expires_at: string | null;
  created_at: string;
}

interface CredentialItemLight {
  id: string;
  title: string;
  fields: { id: string; field_title: string }[];
}

const INPUT = "w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2 text-vm-text font-mono text-sm outline-none focus:border-vm-accent";
const LABEL = "block font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim mb-1";

const API_SCOPES = ['backup.read', 'credentials.read'];

export default function AgentsPage() {
  const t = useT();
  const toast = useToast();
  const [clients, setClients] = useState<McpClient[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [createdKey, setCreatedKey] = useState<{ name: string; key: string } | null>(null);
  const [grantsFor, setGrantsFor] = useState<McpClient | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<McpClient | null>(null);

  const load = () => {
    setLoading(true);
    getMcpClients().then(setClients).catch((e) => toast.error(`Load failed: ${e.message}`)).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const handleDelete = async () => {
    if (!confirmDelete) return;
    try {
      await deleteMcpClient(confirmDelete.id);
      toast.success(`${t('agents.deleted')}: ${confirmDelete.name}`);
      setConfirmDelete(null);
      load();
    } catch (e: any) {
      toast.error(e.message || 'Delete failed');
    }
  };

  const toggleActive = async (c: McpClient) => {
    try {
      await updateMcpClient(c.id, { is_active: !c.is_active });
      load();
    } catch (e: any) {
      toast.error(e.message || 'Update failed');
    }
  };

  const rotate = async (c: McpClient) => {
    try {
      const res = await rotateMcpClientKey(c.id);
      setCreatedKey({ name: c.name, key: res.raw_key });
    } catch (e: any) {
      toast.error(e.message || 'Rotate failed');
    }
  };

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase flex items-center gap-2">
            <Bot className="w-6 h-6" /> {t('agents.title')}
          </h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">{clients.length}</div>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-vm-accent text-vm-bg rounded font-bold tracking-wider uppercase text-xs hover:bg-vm-accent/90"
        >
          <Plus className="w-4 h-4" /> {t('agents.new')}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto bg-vm-surface border border-vm-border rounded">
        {loading && <div className="p-6 font-mono text-xs text-vm-text-dim">{t('cred.loading')}</div>}
        {!loading && clients.length === 0 && (
          <div className="text-center py-12 text-vm-text-dim font-mono">
            <Bot className="w-10 h-10 mx-auto mb-3 opacity-30" />
            <div className="tracking-[2px] text-sm">{t('agents.empty')}</div>
          </div>
        )}
        {clients.map((c) => (
          <div key={c.id} className="px-4 py-3 border-b border-vm-border/50">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="font-semibold text-vm-text-bright truncate flex items-center gap-2">
                  {c.name}
                  {!c.is_active && <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border border-vm-danger/40 text-vm-danger uppercase">{t('agents.inactive')}</span>}
                </div>
                <div className="font-mono text-[10px] text-vm-text-dim truncate mt-0.5">
                  {c.key_prefix} · {t('agents.used')} {c.use_count || 0} · {c.last_used_at ? new Date(c.last_used_at).toLocaleString('sv-SE') : t('agents.never')}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button onClick={() => setGrantsFor(c)} className="flex items-center gap-1 px-2 py-1 border border-vm-accent/50 text-vm-accent rounded text-[10px] font-bold uppercase tracking-wider hover:bg-vm-accent/10">
                  <ShieldCheck className="w-3 h-3" /> {t('agents.grants')}
                </button>
                <button onClick={() => rotate(c)} className="flex items-center gap-1 px-2 py-1 border border-vm-border text-vm-text-dim rounded text-[10px] font-bold uppercase tracking-wider hover:text-vm-text-bright" title={t('agents.rotate')}>
                  <KeyRound className="w-3 h-3" />
                </button>
                <button onClick={() => toggleActive(c)} className={`px-2 py-1 rounded text-[10px] font-bold uppercase tracking-wider border ${c.is_active ? 'border-vm-success/40 text-vm-success' : 'border-vm-border text-vm-text-dim'}`}>
                  {c.is_active ? 'On' : 'Off'}
                </button>
                <button onClick={() => setConfirmDelete(c)} className="text-vm-text-dim hover:text-vm-danger" title={t('cred.delete')}>
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {showCreate && (
        <CreateClientModal
          onClose={() => setShowCreate(false)}
          onCreated={(name, key) => { setShowCreate(false); setCreatedKey({ name, key }); load(); }}
        />
      )}

      {createdKey && <RawKeyModal name={createdKey.name} rawKey={createdKey.key} onClose={() => setCreatedKey(null)} />}

      {grantsFor && (
        <GrantsModal
          client={grantsFor}
          onClose={() => setGrantsFor(null)}
          onSaved={() => { setGrantsFor(null); load(); }}
        />
      )}

      <ConfirmModal
        open={!!confirmDelete}
        title={t('agents.delete_title')}
        message={`"${confirmDelete?.name}" ${t('cred.delete_message')}`}
        confirmLabel={t('cred.delete')}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

function CreateClientModal({ onClose, onCreated }: { onClose: () => void; onCreated: (name: string, key: string) => void }) {
  const t = useT();
  const toast = useToast();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (!name.trim()) { toast.warning(t('agents.need_name')); return; }
    setSubmitting(true);
    try {
      const res = await createMcpClient({ name: name.trim(), description: description || null });
      onCreated(res.name, res.raw_key);
    } catch (e: any) {
      toast.error(e.message || 'Create failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-vm-surface2 border border-vm-border-bright rounded shadow-2xl w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-vm-border flex items-center justify-between">
          <span className="font-mono text-xs uppercase tracking-[2px] text-vm-text-bright">{t('agents.new')}</span>
          <button onClick={onClose} className="text-vm-text-dim hover:text-vm-text-bright"><X className="w-4 h-4" /></button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <div>
            <label className={LABEL}>{t('agents.name')}</label>
            <input value={name} onChange={(e) => setName(e.target.value)} className={INPUT} placeholder="llm-agent" autoFocus />
          </div>
          <div>
            <label className={LABEL}>{t('cred.description')}</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)} className={INPUT} />
          </div>
          <div className="font-mono text-[10px] text-vm-text-dim">{t('agents.create_hint')}</div>
        </div>
        <div className="px-5 py-3 border-t border-vm-border flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase">{t('cred.cancel')}</button>
          <button onClick={submit} disabled={submitting} className="px-3 py-1.5 bg-vm-accent text-vm-bg rounded text-xs font-bold tracking-wider uppercase disabled:opacity-50">
            {submitting ? '…' : t('cred.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

function RawKeyModal({ name, rawKey, onClose }: { name: string; rawKey: string; onClose: () => void }) {
  const t = useT();
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(rawKey);
      setCopied(true);
      toast.success(t('cred.copied'));
    } catch {
      toast.error(t('cred.copy_failed'));
    }
  };
  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-vm-surface2 border border-vm-accent/50 rounded shadow-2xl w-full max-w-lg mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-vm-border flex items-center justify-between">
          <span className="font-mono text-xs uppercase tracking-[2px] text-vm-text-bright">{t('agents.key_once')}: {name}</span>
        </div>
        <div className="px-5 py-4 space-y-3">
          <pre className="bg-vm-bg border border-vm-accent/30 rounded p-2 text-vm-text-bright text-xs whitespace-pre-wrap break-all">{rawKey}</pre>
          <div className="font-mono text-[11px] text-vm-warning">{t('agents.key_warning')}</div>
          <div className="flex justify-end gap-2">
            <button onClick={copy} className="flex items-center gap-1 px-3 py-1.5 bg-vm-accent text-vm-bg rounded text-xs font-bold tracking-wider uppercase">
              <Copy className="w-3 h-3" /> {copied ? t('agents.copied') : t('cred.copy')}
            </button>
            <button onClick={onClose} className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase">{t('cred.cancel')}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function GrantsModal({ client, onClose, onSaved }: { client: McpClient; onClose: () => void; onSaved: () => void }) {
  const t = useT();
  const toast = useToast();
  const [items, setItems] = useState<CredentialItemLight[]>([]);
  const [itemIds, setItemIds] = useState<Set<string>>(new Set());
  const [fieldIds, setFieldIds] = useState<Set<string>>(new Set());
  const [apiScopes, setApiScopes] = useState<Set<string>>(new Set());
  const [openItems, setOpenItems] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    Promise.all([getCredentialItems(), getMcpClientGrants(client.id)])
      .then(([itemRows, grants]: any[]) => {
        setItems(itemRows.map((i: any) => ({ id: i.id, title: i.title, fields: i.fields })));
        setItemIds(new Set(grants.credential_items || []));
        setFieldIds(new Set(grants.credential_fields || []));
        setApiScopes(new Set(grants.api_scopes || []));
      })
      .catch((e) => toast.error(`Load failed: ${e.message}`))
      .finally(() => setLoading(false));
  }, [client.id]);

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id); else next.add(id);
    setter(next);
  };

  const save = async () => {
    setSubmitting(true);
    try {
      await putMcpClientGrants(client.id, {
        credential_item_ids: Array.from(itemIds),
        credential_field_ids: Array.from(fieldIds),
        api_scopes: Array.from(apiScopes),
      });
      toast.success(t('agents.grants_saved'));
      onSaved();
    } catch (e: any) {
      toast.error(e.message || 'Save failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-vm-surface2 border border-vm-border-bright rounded shadow-2xl w-full max-w-xl mx-4 max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-vm-border flex items-center justify-between sticky top-0 bg-vm-surface2 z-10">
          <span className="font-mono text-xs uppercase tracking-[2px] text-vm-text-bright truncate">{t('agents.grants')}: {client.name}</span>
          <button onClick={onClose} className="text-vm-text-dim hover:text-vm-text-bright"><X className="w-4 h-4" /></button>
        </div>
        {loading ? (
          <div className="px-5 py-4 font-mono text-xs text-vm-text-dim">{t('cred.loading')}</div>
        ) : (
          <div className="px-5 py-4 space-y-4">
            <div>
              <div className={LABEL}>{t('agents.api_scopes')}</div>
              {API_SCOPES.map((s) => (
                <label key={s} className="flex items-center gap-2 py-0.5 font-mono text-[11px] text-vm-text cursor-pointer">
                  <input type="checkbox" checked={apiScopes.has(s)} onChange={() => toggle(apiScopes, setApiScopes, s)} className="accent-[var(--vm-accent)]" />
                  {s}
                  <span className="text-vm-text-dim">· {t(`agents.scope_${s.replace('.', '_')}`)}</span>
                </label>
              ))}
            </div>

            <div>
              <div className={LABEL}>{t('agents.item_grants')}</div>
              <div className="font-mono text-[10px] text-vm-text-dim mb-1">{t('agents.item_grants_hint')}</div>
              {items.length === 0 && <div className="font-mono text-[11px] text-vm-text-dim">{t('agents.no_items')}</div>}
              <div className="border border-vm-border rounded bg-vm-bg max-h-64 overflow-y-auto">
                {items.map((it) => {
                  const itemOpen = openItems.has(it.id);
                  return (
                    <div key={it.id}>
                      <div className="flex items-center gap-2 px-2.5 py-1.5 border-b border-vm-border/50">
                        <button onClick={() => toggle(openItems, setOpenItems, it.id)} className="text-vm-text-dim hover:text-vm-text-bright shrink-0">
                          {itemOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                        </button>
                        <label className="flex items-center gap-2 flex-1 cursor-pointer min-w-0">
                          <input type="checkbox" checked={itemIds.has(it.id)} onChange={() => toggle(itemIds, setItemIds, it.id)} className="accent-[var(--vm-accent)]" />
                          <span className="font-mono text-[11px] text-vm-text truncate">{it.title}</span>
                          {itemIds.has(it.id) && <span className="font-mono text-[9px] text-vm-accent uppercase shrink-0">{t('agents.all_fields')}</span>}
                        </label>
                      </div>
                      {itemOpen && it.fields.map((f) => (
                        <label key={f.id} className="flex items-center gap-2 pl-10 pr-2.5 py-1 cursor-pointer border-b border-vm-border/30">
                          <input
                            type="checkbox"
                            checked={itemIds.has(it.id) || fieldIds.has(f.id)}
                            disabled={itemIds.has(it.id)}
                            onChange={() => toggle(fieldIds, setFieldIds, f.id)}
                            className="accent-[var(--vm-accent)]"
                          />
                          <span className="font-mono text-[10px] text-vm-text-dim">{f.field_title}</span>
                        </label>
                      ))}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
        <div className="px-5 py-3 border-t border-vm-border flex justify-end gap-2 sticky bottom-0 bg-vm-surface2">
          <button onClick={onClose} className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase">{t('cred.cancel')}</button>
          <button onClick={save} disabled={submitting || loading} className="px-3 py-1.5 bg-vm-accent text-vm-bg rounded text-xs font-bold tracking-wider uppercase disabled:opacity-50">
            {submitting ? '…' : t('cred.save')}
          </button>
        </div>
      </div>
    </div>
  );
}
