'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  getCredentialItems, createCredentialItem, updateCredentialItem, deleteCredentialItem,
  addCredentialField, updateCredentialField, deleteCredentialField,
  revealCredentialItem, revealCredentialField, getAuditLogs,
} from '@/lib/api';
import { useToast } from '@/components/Toast';
import { ConfirmModal } from '@/components/ConfirmModal';
import {
  KeyRound, Plus, Search, Eye, EyeOff, Copy, Trash2, X, Clock, Bot, Pencil, AlertTriangle,
} from 'lucide-react';
import { useT } from '@/lib/i18n';

interface CredentialField {
  id: string;
  field_title: string;
  key_version: number;
  sort_order: number;
  reveal_count: number;
  last_revealed_at: string | null;
  created_at: string;
  updated_at: string;
}

interface CredentialItem {
  id: string;
  owner_id: string;
  title: string;
  description: string | null;
  tags: string[] | null;
  expires_at: string | null;
  rotation_policy: string | null;
  provenance: string | null;
  mcp_enabled: boolean;
  mcp_scopes: string[] | null;
  last_revealed_at: string | null;
  reveal_count: number;
  field_count: number;
  fields: CredentialField[];
  created_at: string;
  updated_at: string;
}

function expiryColour(iso: string | null): string {
  if (!iso) return 'text-vm-text-dim';
  const days = Math.floor((new Date(iso).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  if (days < 7) return 'text-vm-danger';
  if (days < 30) return 'text-vm-warning';
  return 'text-vm-text-dim';
}

const INPUT = "w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2 text-vm-text font-mono text-sm outline-none focus:border-vm-accent";
const LABEL = "block font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim mb-1";
const NONE = '-';

export default function CredentialsPage() {
  const t = useT();
  const toast = useToast();
  const [items, setItems] = useState<CredentialItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<CredentialItem | null>(null);

  const load = () => {
    setLoading(true);
    getCredentialItems()
      .then(setItems)
      .catch((e) => toast.error(`Load failed: ${e.message}`))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((c) => {
      if (tagFilter && !(c.tags || []).includes(tagFilter)) return false;
      if (!q) return true;
      return c.title.toLowerCase().includes(q) || (c.description || '').toLowerCase().includes(q);
    });
  }, [items, search, tagFilter]);

  const allTags = useMemo(() => {
    const s = new Set<string>();
    items.forEach((c) => (c.tags || []).forEach((t) => s.add(t)));
    return Array.from(s).sort();
  }, [items]);

  const selected = items.find((c) => c.id === selectedId) || null;

  const handleDelete = async () => {
    if (!confirmDelete) return;
    try {
      await deleteCredentialItem(confirmDelete.id);
      toast.success(`${t('cred.deleted_msg')}: ${confirmDelete.title}`);
      if (selectedId === confirmDelete.id) setSelectedId(null);
      setConfirmDelete(null);
      load();
    } catch (e: any) {
      toast.error(`Delete failed: ${e.message}`);
    }
  };

  return (
    <div className="flex gap-4 h-[calc(100vh-100px)]">
      {/* List */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase flex items-center gap-2">
              <KeyRound className="w-6 h-6" /> {t('cred.title')}
            </h1>
            <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">{filtered.length} / {items.length}</div>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 bg-vm-accent text-vm-bg rounded font-bold tracking-wider uppercase text-xs hover:bg-vm-accent/90"
          >
            <Plus className="w-4 h-4" /> {t('cred.new')}
          </button>
        </div>

        <div className="mb-3 flex gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="w-4 h-4 absolute left-2.5 top-2.5 text-vm-text-dim" />
            <input
              type="text"
              placeholder={t('cred.search')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className={`${INPUT} pl-8`}
            />
          </div>
          <select value={tagFilter} onChange={(e) => setTagFilter(e.target.value)} className={`${INPUT} max-w-[180px]`}>
            <option value="">{t('cred.all_tags')}</option>
            {allTags.map((tag) => <option key={tag} value={tag}>{tag}</option>)}
          </select>
        </div>

        <div className="flex-1 overflow-y-auto bg-vm-surface border border-vm-border rounded">
          {loading && <div className="p-6 font-mono text-xs text-vm-text-dim">{t('cred.loading')}</div>}
          {!loading && filtered.length === 0 && (
            <div className="text-center py-12 text-vm-text-dim font-mono">
              <KeyRound className="w-10 h-10 mx-auto mb-3 opacity-30" />
              <div className="tracking-[2px] text-sm">{t('cred.empty')}</div>
            </div>
          )}
          {filtered.map((c) => (
            <button
              key={c.id}
              onClick={() => setSelectedId(c.id)}
              className={`w-full text-left px-4 py-3 border-b border-vm-border/50 hover:bg-vm-surface2 transition-colors ${selectedId === c.id ? 'bg-vm-surface2 border-l-2 border-l-vm-accent' : ''}`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="font-semibold text-vm-text-bright truncate">{c.title}</div>
                  <div className="font-mono text-[10px] text-vm-text-dim truncate mt-0.5">
                    {c.field_count} {t('cred.fields')}
                    {c.description ? ` · ${c.description}` : ''}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {c.mcp_enabled && <Bot className="w-3.5 h-3.5 text-vm-accent" aria-label="MCP" />}
                  {c.expires_at && (
                    <span className={`font-mono text-[10px] ${expiryColour(c.expires_at)}`}>
                      <Clock className="w-3 h-3 inline mr-0.5" />
                      {new Date(c.expires_at).toLocaleDateString('sv-SE')}
                    </span>
                  )}
                  {(c.tags || []).slice(0, 2).map((tag) => (
                    <span key={tag} className="font-mono text-[9px] px-1.5 py-0.5 rounded-sm border border-vm-accent/30 bg-vm-accent/[0.06] text-vm-accent uppercase tracking-wider">{tag}</span>
                  ))}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Detail panel */}
      {selected && (
        <DetailPanel
          item={selected}
          onClose={() => setSelectedId(null)}
          onChange={load}
          onDelete={() => setConfirmDelete(selected)}
        />
      )}

      {/* Create modal */}
      {showCreate && <CreateModal onClose={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); load(); }} />}

      <ConfirmModal
        open={!!confirmDelete}
        title={t('cred.delete_title')}
        message={`"${confirmDelete?.title}" ${t('cred.delete_message')}`}
        confirmLabel={t('cred.delete')}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

function DetailPanel({
  item, onClose, onChange, onDelete,
}: {
  item: CredentialItem;
  onClose: () => void;
  onChange: () => void;
  onDelete: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const [tab, setTab] = useState<'info' | 'audit'>('info');
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [revealField, setRevealField] = useState<CredentialField | 'ALL' | null>(null);
  const [fieldModal, setFieldModal] = useState<{ mode: 'add' } | { mode: 'edit'; field: CredentialField } | null>(null);
  const [editItem, setEditItem] = useState(false);
  const [confirmFieldDelete, setConfirmFieldDelete] = useState<CredentialField | null>(null);

  useEffect(() => {
    if (tab !== 'audit') return;
    setAuditLoading(true);
    // action=credential matches credential_item.*, credential_field.* and the
    // legacy credential.* rows, whose ids the migration reused as item ids.
    const ids = new Set([item.id, ...item.fields.map((f) => f.id)]);
    getAuditLogs('action=credential&limit=200')
      .then((rows: any[]) => setAuditLogs(
        rows.filter((r) => ids.has(r.resource_id) || (r.resource_type === 'mcp_client' && (r.detail || '').includes(item.title)))
            .sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
      ))
      .finally(() => setAuditLoading(false));
  }, [tab, item.id, item.fields]);

  const handleFieldDelete = async () => {
    if (!confirmFieldDelete) return;
    try {
      await deleteCredentialField(confirmFieldDelete.id);
      toast.success(t('cred.field_deleted_msg'));
      setConfirmFieldDelete(null);
      onChange();
    } catch (e: any) {
      // The API refuses to remove the last field; surface that verbatim.
      toast.error(e.message || 'Delete failed');
      setConfirmFieldDelete(null);
    }
  };

  return (
    <div className="w-[460px] shrink-0 bg-vm-surface border border-vm-border-bright rounded flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-vm-border flex items-center justify-between">
        <div className="min-w-0">
          <div className="font-semibold text-vm-text-bright truncate">{item.title}</div>
          <div className="font-mono text-[10px] text-vm-accent uppercase tracking-[2px]">
            {item.field_count} {t('cred.fields')}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setEditItem(true)} className="text-vm-text-dim hover:text-vm-text-bright" title={t('cred.edit')}>
            <Pencil className="w-4 h-4" />
          </button>
          <button onClick={onClose} className="text-vm-text-dim hover:text-vm-text-bright"><X className="w-4 h-4" /></button>
        </div>
      </div>

      <div className="flex border-b border-vm-border">
        <button
          onClick={() => setTab('info')}
          className={`flex-1 py-2 font-mono text-[11px] tracking-[2px] uppercase ${tab === 'info' ? 'text-vm-accent border-b-2 border-vm-accent' : 'text-vm-text-dim hover:text-vm-text'}`}
        >{t('cred.tab_info')}</button>
        <button
          onClick={() => setTab('audit')}
          className={`flex-1 py-2 font-mono text-[11px] tracking-[2px] uppercase ${tab === 'audit' ? 'text-vm-accent border-b-2 border-vm-accent' : 'text-vm-text-dim hover:text-vm-text'}`}
        >{t('cred.tab_audit')}</button>
      </div>

      {tab === 'info' && (
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          <div className="bg-vm-surface2 border border-vm-border rounded p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim">{t('cred.detail_fields')}</span>
              <div className="flex gap-2">
                {item.fields.length > 1 && (
                  <button
                    onClick={() => setRevealField('ALL')}
                    className="flex items-center gap-1 px-2 py-1 border border-vm-accent/50 text-vm-accent rounded text-[10px] font-bold uppercase tracking-wider hover:bg-vm-accent/10"
                  >
                    <Eye className="w-3 h-3" /> {t('cred.reveal_all')}
                  </button>
                )}
                <button
                  onClick={() => setFieldModal({ mode: 'add' })}
                  className="flex items-center gap-1 px-2 py-1 bg-vm-accent text-vm-bg rounded text-[10px] font-bold uppercase tracking-wider hover:bg-vm-accent/90"
                >
                  <Plus className="w-3 h-3" /> {t('cred.add_field')}
                </button>
              </div>
            </div>

            <div className="space-y-1.5">
              {item.fields.map((f) => (
                <div key={f.id} className="flex items-center gap-2 bg-vm-bg border border-vm-border rounded px-2.5 py-2">
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-[11px] text-vm-text truncate">{f.field_title}</div>
                    <div className="font-mono text-[10px] text-vm-text-dim">••••••••</div>
                  </div>
                  <button
                    onClick={() => setRevealField(f)}
                    className="text-vm-text-dim hover:text-vm-accent shrink-0"
                    title={t('cred.reveal')}
                  ><Eye className="w-4 h-4" /></button>
                  <button
                    onClick={() => setFieldModal({ mode: 'edit', field: f })}
                    className="text-vm-text-dim hover:text-vm-text-bright shrink-0"
                    title={t('cred.edit')}
                  ><Pencil className="w-4 h-4" /></button>
                  <button
                    onClick={() => setConfirmFieldDelete(f)}
                    className="text-vm-text-dim hover:text-vm-danger shrink-0"
                    title={t('cred.remove_field')}
                  ><Trash2 className="w-4 h-4" /></button>
                </div>
              ))}
            </div>
            <div className="font-mono text-[10px] text-vm-text-dim mt-2">{t('cred.reveal_one_hint')}</div>
          </div>

          {item.description && <Field label={t('cred.description')} value={item.description} />}
          <Field label={t('cred.tags')} value={(item.tags || []).join(', ') || NONE} />
          <Field label={t('cred.expires')} value={item.expires_at ? new Date(item.expires_at).toLocaleString('sv-SE') : NONE} />
          <Field label={t('cred.rotation_policy')} value={item.rotation_policy || NONE} />
          <Field label={t('cred.provenance')} value={item.provenance || NONE} />
          <Field label={t('cred.mcp')} value={item.mcp_enabled ? 'On' : 'Off'} />
          {item.mcp_enabled && <Field label={t('cred.mcp_scopes')} value={(item.mcp_scopes || []).join(', ') || NONE} />}
          <Field label={t('cred.last_revealed')} value={item.last_revealed_at ? new Date(item.last_revealed_at).toLocaleString('sv-SE') : NONE} />
          <Field label={t('cred.reveal_count')} value={String(item.reveal_count || 0)} />
          <Field label={t('cred.created')} value={new Date(item.created_at).toLocaleString('sv-SE')} />

          <div className="pt-3 border-t border-vm-border flex gap-2">
            <button
              onClick={onDelete}
              className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10"
            >
              <Trash2 className="w-3 h-3" /> {t('cred.delete')}
            </button>
          </div>
        </div>
      )}

      {tab === 'audit' && (
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {auditLoading && <div className="font-mono text-xs text-vm-text-dim">{t('cred.loading')}</div>}
          {!auditLoading && auditLogs.length === 0 && (
            <div className="font-mono text-xs text-vm-text-dim text-center py-6">{t('cred.audit_empty')}</div>
          )}
          {auditLogs.map((l) => (
            <div key={l.id} className="bg-vm-surface2 border border-vm-border rounded p-2.5">
              <div className="flex items-center justify-between mb-1">
                <span className={`font-mono text-[10px] uppercase tracking-[2px] ${
                  l.action.includes('denied') ? 'text-vm-danger' :
                  l.action.includes('reveal') ? 'text-vm-warning' :
                  l.action.includes('delete') ? 'text-vm-danger' :
                  l.action.includes('create') ? 'text-vm-success' : 'text-vm-accent'
                }`}>{l.action}</span>
                <span className="font-mono text-[10px] text-vm-text-dim">
                  {l.created_at ? new Date(l.created_at).toLocaleString('sv-SE') : ''}
                </span>
              </div>
              <div className="font-mono text-[11px] text-vm-text-bright">{l.username || NONE}</div>
              {l.detail && <div className="font-mono text-[10px] text-vm-text-dim mt-1 break-words">{l.detail}</div>}
              {l.ip_address && <div className="font-mono text-[10px] text-vm-text-dim">IP: {l.ip_address}</div>}
            </div>
          ))}
        </div>
      )}

      {/* Reveal modal: one field, or every field of the item */}
      {revealField && (
        <RevealModal
          item={item}
          field={revealField === 'ALL' ? null : revealField}
          onClose={() => { setRevealField(null); onChange(); }}
        />
      )}

      {/* Add / edit field modal */}
      {fieldModal && (
        <FieldModal
          item={item}
          mode={fieldModal.mode}
          field={fieldModal.mode === 'edit' ? fieldModal.field : null}
          onClose={() => setFieldModal(null)}
          onSaved={() => { setFieldModal(null); onChange(); }}
        />
      )}

      {/* Edit item modal */}
      {editItem && (
        <ItemEditModal
          item={item}
          onClose={() => setEditItem(false)}
          onSaved={() => { setEditItem(false); onChange(); }}
        />
      )}

      <ConfirmModal
        open={!!confirmFieldDelete}
        title={t('cred.remove_field')}
        message={`"${confirmFieldDelete?.field_title}" ${t('cred.delete_message')}`}
        confirmLabel={t('cred.delete')}
        destructive
        onConfirm={handleFieldDelete}
        onCancel={() => setConfirmFieldDelete(null)}
      />
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim mb-0.5">{label}</div>
      <div className="font-mono text-xs text-vm-text-bright break-words">{value}</div>
    </div>
  );
}

function RevealModal({
  item, field, onClose,
}: {
  item: CredentialItem;
  field: CredentialField | null; // null = reveal all fields
  onClose: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const [password, setPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [purpose, setPurpose] = useState('manual-copy');
  const [values, setValues] = useState<{ field_title: string; value: string }[] | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!values) return;
    setSecondsLeft(60);
    const i = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) {
          clearInterval(i);
          setValues(null);
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(i);
  }, [values]);

  // Clear plaintext from memory whenever this modal closes.
  useEffect(() => () => setValues(null), []);

  const handleReveal = async () => {
    if (!password || !purpose) {
      toast.warning(t('cred.reveal_reauth'));
      return;
    }
    setSubmitting(true);
    try {
      if (field) {
        const res = await revealCredentialField(field.id, password, purpose, totpCode);
        setValues([{ field_title: res.field_title, value: res.value }]);
      } else {
        const res = await revealCredentialItem(item.id, password, purpose, totpCode);
        setValues(res.values.map((v: any) => ({ field_title: v.field_title, value: v.value })));
      }
      setPassword('');
      setTotpCode('');
    } catch (e: any) {
      toast.error(`Reveal failed: ${e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(t('cred.copied'));
      setTimeout(() => navigator.clipboard.writeText(' ').catch(() => {}), 30000);
    } catch {
      toast.error(t('cred.copy_failed'));
    }
  };

  const heading = field ? field.field_title : item.title;

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-vm-surface2 border border-vm-border-bright rounded shadow-2xl w-full max-w-lg mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-vm-border flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <Eye className="w-4 h-4 text-vm-accent shrink-0" />
            <span className="font-mono text-xs uppercase tracking-[2px] text-vm-text-bright truncate">{t('cred.reveal')}: {heading}</span>
          </div>
          <button onClick={onClose} className="text-vm-text-dim hover:text-vm-text-bright"><X className="w-4 h-4" /></button>
        </div>

        {!values && (
          <div className="px-5 py-4 space-y-3">
            <div>
              <label className={LABEL}>{t('cred.reveal_reauth')}</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleReveal()}
                className={INPUT}
                autoFocus
              />
            </div>
            <div>
              <label className={LABEL}>{t('cred.reveal_totp')}</label>
              <input
                type="text"
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
                className={INPUT}
                placeholder="123456"
              />
            </div>
            <div>
              <label className={LABEL}>{t('cred.reveal_purpose')}</label>
              <input
                type="text"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                className={INPUT}
                placeholder={t('cred.reveal_purpose_ph')}
              />
            </div>
            <div className="flex items-start gap-2 p-2.5 bg-vm-warning/10 border border-vm-warning/30 rounded">
              <AlertTriangle className="w-4 h-4 text-vm-warning shrink-0 mt-0.5" />
              <div className="font-mono text-[11px] text-vm-warning">{t('cred.reveal_warning')}</div>
            </div>
            <div className="pt-2 flex justify-end gap-2">
              <button onClick={onClose} className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-surface3">{t('cred.cancel')}</button>
              <button onClick={handleReveal} disabled={submitting} className="px-3 py-1.5 bg-vm-accent text-vm-bg rounded text-xs font-bold tracking-wider uppercase disabled:opacity-50">
                {submitting ? '…' : t('cred.reveal')}
              </button>
            </div>
          </div>
        )}

        {values && (
          <div className="px-5 py-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim">{t('cred.field_value')}</span>
              <span className="font-mono text-[10px] text-vm-warning">{t('cred.reveal_clears_in')} {secondsLeft}s</span>
            </div>
            {values.map((v) => (
              <div key={v.field_title}>
                <div className="font-mono text-[10px] text-vm-text-dim mb-0.5">{v.field_title}</div>
                <div className="flex items-start gap-2">
                  <pre className="flex-1 bg-vm-bg border border-vm-accent/30 rounded p-2 text-vm-text-bright text-xs whitespace-pre-wrap break-all">{v.value}</pre>
                  <button onClick={() => handleCopy(v.value)} className="mt-1 flex items-center gap-1 px-2 py-1 bg-vm-accent text-vm-bg rounded text-[10px] font-bold uppercase tracking-wider shrink-0">
                    <Copy className="w-3 h-3" /> {t('cred.copy')}
                  </button>
                </div>
              </div>
            ))}
            <div className="flex justify-end">
              <button onClick={onClose} className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase">{t('cred.cancel')}</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function FieldModal({
  item, mode, field, onClose, onSaved,
}: {
  item: CredentialItem;
  mode: 'add' | 'edit';
  field: CredentialField | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const [fieldTitle, setFieldTitle] = useState(field?.field_title || '');
  const [value, setValue] = useState('');
  const [showVal, setShowVal] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!fieldTitle || (mode === 'add' && !value)) {
      toast.warning(t('cred.need_title_and_one_field'));
      return;
    }
    setSubmitting(true);
    try {
      if (mode === 'add') {
        await addCredentialField(item.id, { field_title: fieldTitle, value });
        toast.success(t('cred.field_added_msg'));
      } else if (field) {
        const payload: any = { field_title: fieldTitle };
        if (value) payload.value = value; // empty value = keep the stored one
        await updateCredentialField(field.id, payload);
        toast.success(t('cred.field_updated_msg'));
      }
      onSaved();
    } catch (e: any) {
      toast.error(e.message || 'Save failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-vm-surface2 border border-vm-border-bright rounded shadow-2xl w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-vm-border flex items-center justify-between">
          <span className="font-mono text-xs uppercase tracking-[2px] text-vm-text-bright truncate">
            {mode === 'add' ? `${t('cred.add_field')}: ${item.title}` : `${t('cred.edit')}: ${field?.field_title}`}
          </span>
          <button onClick={onClose} className="text-vm-text-dim hover:text-vm-text-bright"><X className="w-4 h-4" /></button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <div>
            <label className={LABEL}>{t('cred.field_title')}</label>
            <input value={fieldTitle} onChange={(e) => setFieldTitle(e.target.value)} className={INPUT} placeholder={t('cred.field_title_ph')} />
          </div>
          <div>
            <label className={LABEL}>
              {t('cred.field_value')}
              {mode === 'edit' && <span className="normal-case tracking-normal"> ({t('cred.field_value_keep_hint')})</span>}
            </label>
            <div className="relative">
              <input
                type={showVal ? 'text' : 'password'}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                className={`${INPUT} pr-10`}
                placeholder={t('cred.field_value_ph')}
                autoFocus={mode === 'add'}
              />
              <button onClick={() => setShowVal(!showVal)} className="absolute right-2 top-2 text-vm-text-dim hover:text-vm-text-bright">
                {showVal ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>
        <div className="px-5 py-3 border-t border-vm-border flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase">{t('cred.cancel')}</button>
          <button onClick={handleSubmit} disabled={submitting} className="px-3 py-1.5 bg-vm-accent text-vm-bg rounded text-xs font-bold tracking-wider uppercase disabled:opacity-50">
            {submitting ? '…' : t('cred.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

function ItemEditModal({
  item, onClose, onSaved,
}: {
  item: CredentialItem;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const [title, setTitle] = useState(item.title);
  const [description, setDescription] = useState(item.description || '');
  const [tags, setTags] = useState((item.tags || []).join(', '));
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!title) return;
    setSubmitting(true);
    try {
      await updateCredentialItem(item.id, {
        title,
        description: description || null,
        tags: tags.split(',').map((s) => s.trim()).filter(Boolean),
      });
      toast.success(t('cred.item_updated_msg'));
      onSaved();
    } catch (e: any) {
      toast.error(`Save failed: ${e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-vm-surface2 border border-vm-border-bright rounded shadow-2xl w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-vm-border flex items-center justify-between">
          <span className="font-mono text-xs uppercase tracking-[2px] text-vm-text-bright truncate">{t('cred.edit')}: {item.title}</span>
          <button onClick={onClose} className="text-vm-text-dim hover:text-vm-text-bright"><X className="w-4 h-4" /></button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <div>
            <label className={LABEL}>{t('cred.create_item_title')}</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} className={INPUT} placeholder={t('cred.create_item_title_ph')} />
          </div>
          <div>
            <label className={LABEL}>{t('cred.description')}</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)} className={INPUT} />
          </div>
          <div>
            <label className={LABEL}>{t('cred.tags')}</label>
            <input value={tags} onChange={(e) => setTags(e.target.value)} className={INPUT} placeholder={t('cred.tags_ph')} />
          </div>
        </div>
        <div className="px-5 py-3 border-t border-vm-border flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase">{t('cred.cancel')}</button>
          <button onClick={handleSubmit} disabled={submitting} className="px-3 py-1.5 bg-vm-accent text-vm-bg rounded text-xs font-bold tracking-wider uppercase disabled:opacity-50">
            {submitting ? '…' : t('cred.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

function CreateModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const t = useT();
  const toast = useToast();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [rows, setRows] = useState<{ field_title: string; value: string }[]>([
    { field_title: '', value: '' },
    { field_title: '', value: '' },
  ]);
  const [showVal, setShowVal] = useState<Record<number, boolean>>({});
  const [submitting, setSubmitting] = useState(false);

  const setRow = (i: number, patch: Partial<{ field_title: string; value: string }>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const handleSubmit = async () => {
    const fields = rows.filter((r) => r.field_title.trim() && r.value.trim());
    if (!title.trim() || fields.length === 0) {
      toast.warning(t('cred.need_title_and_one_field'));
      return;
    }
    const titles = fields.map((f) => f.field_title.trim());
    if (new Set(titles).size !== titles.length) {
      toast.warning(t('cred.duplicate_titles'));
      return;
    }
    setSubmitting(true);
    try {
      await createCredentialItem({
        title: title.trim(),
        description: description || null,
        tags: tags.split(',').map((s) => s.trim()).filter(Boolean),
        fields: fields.map((f) => ({ field_title: f.field_title.trim(), value: f.value })),
      });
      toast.success(t('cred.created_msg'));
      onCreated();
    } catch (e: any) {
      toast.error(`Create failed: ${e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-vm-surface2 border border-vm-border-bright rounded shadow-2xl w-full max-w-xl mx-4 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-vm-border flex items-center justify-between sticky top-0 bg-vm-surface2 z-10">
          <span className="font-mono text-xs uppercase tracking-[2px] text-vm-text-bright">{t('cred.create_title')}</span>
          <button onClick={onClose} className="text-vm-text-dim hover:text-vm-text-bright"><X className="w-4 h-4" /></button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <div>
            <label className={LABEL}>{t('cred.create_item_title')}</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} className={INPUT} placeholder={t('cred.create_item_title_ph')} autoFocus />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className={LABEL + " mb-0"}>{t('cred.detail_fields')}</label>
              <button
                onClick={() => setRows((rs) => [...rs, { field_title: '', value: '' }])}
                className="flex items-center gap-1 px-2 py-1 border border-vm-accent/50 text-vm-accent rounded text-[10px] font-bold uppercase tracking-wider hover:bg-vm-accent/10"
              >
                <Plus className="w-3 h-3" /> {t('cred.add_field')}
              </button>
            </div>
            <div className="font-mono text-[10px] text-vm-text-dim mb-2">{t('cred.create_fields_hint')}</div>
            <div className="space-y-2">
              {rows.map((r, i) => (
                <div key={i} className="flex items-start gap-2">
                  <input
                    value={r.field_title}
                    onChange={(e) => setRow(i, { field_title: e.target.value })}
                    className={`${INPUT} w-[42%]`}
                    placeholder={t('cred.field_title_ph')}
                  />
                  <div className="relative flex-1">
                    <input
                      type={showVal[i] ? 'text' : 'password'}
                      value={r.value}
                      onChange={(e) => setRow(i, { value: e.target.value })}
                      className={`${INPUT} pr-9`}
                      placeholder={t('cred.field_value_ph')}
                    />
                    <button
                      onClick={() => setShowVal((s) => ({ ...s, [i]: !s[i] }))}
                      className="absolute right-2 top-2 text-vm-text-dim hover:text-vm-text-bright"
                    >
                      {showVal[i] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  {rows.length > 1 && (
                    <button
                      onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                      className="mt-2 text-vm-text-dim hover:text-vm-danger shrink-0"
                      title={t('cred.remove_field')}
                    ><Trash2 className="w-4 h-4" /></button>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div>
            <label className={LABEL}>{t('cred.tags')}</label>
            <input value={tags} onChange={(e) => setTags(e.target.value)} className={INPUT} placeholder={t('cred.tags_ph')} />
          </div>
          <div>
            <label className={LABEL}>{t('cred.description')}</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)} className={INPUT} />
          </div>
        </div>
        <div className="px-5 py-3 border-t border-vm-border flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase">{t('cred.cancel')}</button>
          <button onClick={handleSubmit} disabled={submitting} className="px-3 py-1.5 bg-vm-accent text-vm-bg rounded text-xs font-bold tracking-wider uppercase disabled:opacity-50">
            {submitting ? t('cred.creating') : t('cred.save')}
          </button>
        </div>
      </div>
    </div>
  );
}
