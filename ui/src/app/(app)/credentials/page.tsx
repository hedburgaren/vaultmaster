'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  getCredentials, createCredential, updateCredential, deleteCredential,
  revealCredential, getAuditLogs,
} from '@/lib/api';
import { useToast } from '@/components/Toast';
import { ConfirmModal } from '@/components/ConfirmModal';
import {
  KeyRound, Plus, Search, Eye, EyeOff, Copy, Trash2, X, Tag, Clock, Shield,
  AlertTriangle, RotateCcw, Bot,
} from 'lucide-react';
import { useT } from '@/lib/i18n';

interface Credential {
  id: string;
  name: string;
  credential_type: string;
  description: string | null;
  tags: string[] | null;
  expires_at: string | null;
  rotation_policy: string | null;
  provenance: string | null;
  mcp_enabled: boolean;
  mcp_scopes: string[] | null;
  last_revealed_at: string | null;
  reveal_count: number;
  key_version: number;
  created_at: string;
  updated_at: string;
}

const TYPE_LABELS: Record<string, string> = {
  api_key: 'API key',
  password: 'Password',
  oauth_token: 'OAuth token',
  token: 'Token',
  secret: 'Secret',
  ssh_key: 'SSH key',
  cert: 'Certificate',
  json_blob: 'JSON',
};

function expiryColour(iso: string | null): string {
  if (!iso) return 'text-vm-text-dim';
  const days = Math.floor((new Date(iso).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  if (days < 0) return 'text-vm-danger';
  if (days < 7) return 'text-vm-danger';
  if (days < 30) return 'text-vm-warning';
  return 'text-vm-text-dim';
}

const INPUT = "w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2 text-vm-text font-mono text-sm outline-none focus:border-vm-accent";

export default function CredentialsPage() {
  const t = useT();
  const toast = useToast();
  const [creds, setCreds] = useState<Credential[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [revealOpen, setRevealOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<Credential | null>(null);

  const load = () => {
    setLoading(true);
    getCredentials().then(setCreds).catch((e) => toast.error(`Load failed: ${e.message}`)).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return creds.filter((c) => {
      if (typeFilter && c.credential_type !== typeFilter) return false;
      if (tagFilter && !(c.tags || []).includes(tagFilter)) return false;
      if (!q) return true;
      return c.name.toLowerCase().includes(q) || (c.description || '').toLowerCase().includes(q);
    });
  }, [creds, search, typeFilter, tagFilter]);

  const allTags = useMemo(() => {
    const s = new Set<string>();
    creds.forEach((c) => (c.tags || []).forEach((t) => s.add(t)));
    return Array.from(s).sort();
  }, [creds]);
  const allTypes = useMemo(() => {
    const s = new Set<string>();
    creds.forEach((c) => s.add(c.credential_type));
    return Array.from(s).sort();
  }, [creds]);

  const selected = creds.find((c) => c.id === selectedId) || null;

  const handleDelete = async () => {
    if (!confirmDelete) return;
    try {
      await deleteCredential(confirmDelete.id);
      toast.success(`Deleted ${confirmDelete.name}`);
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
              <KeyRound className="w-6 h-6" /> Credentials
            </h1>
            <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">{filtered.length} of {creds.length}</div>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 bg-vm-accent text-vm-bg rounded font-bold tracking-wider uppercase text-xs hover:bg-vm-accent/90"
          >
            <Plus className="w-4 h-4" /> New
          </button>
        </div>

        <div className="mb-3 flex gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="w-4 h-4 absolute left-2.5 top-2.5 text-vm-text-dim" />
            <input
              type="text"
              placeholder="Search name or description"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className={`${INPUT} pl-8`}
            />
          </div>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className={`${INPUT} max-w-[180px]`}>
            <option value="">All types</option>
            {allTypes.map((t) => <option key={t} value={t}>{TYPE_LABELS[t] || t}</option>)}
          </select>
          <select value={tagFilter} onChange={(e) => setTagFilter(e.target.value)} className={`${INPUT} max-w-[180px]`}>
            <option value="">All tags</option>
            {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>

        <div className="flex-1 overflow-y-auto bg-vm-surface border border-vm-border rounded">
          {loading && <div className="p-6 font-mono text-xs text-vm-text-dim">Loading…</div>}
          {!loading && filtered.length === 0 && (
            <div className="text-center py-12 text-vm-text-dim font-mono">
              <KeyRound className="w-10 h-10 mx-auto mb-3 opacity-30" />
              <div className="tracking-[2px] text-sm">No credentials match.</div>
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
                  <div className="font-semibold text-vm-text-bright truncate">{c.name}</div>
                  <div className="font-mono text-[10px] text-vm-text-dim truncate mt-0.5">
                    {TYPE_LABELS[c.credential_type] || c.credential_type}
                    {c.description ? ` — ${c.description}` : ''}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {c.mcp_enabled && <Bot className="w-3.5 h-3.5 text-vm-accent" aria-label="MCP enabled" />}
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
          credential={selected}
          onClose={() => setSelectedId(null)}
          onRequestReveal={() => setRevealOpen(true)}
          onChange={load}
          onDelete={() => setConfirmDelete(selected)}
        />
      )}

      {/* Create modal */}
      {showCreate && <CreateModal onClose={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); load(); }} />}

      {/* Reveal modal */}
      {selected && revealOpen && (
        <RevealModal
          credentialId={selected.id}
          credentialName={selected.name}
          onClose={() => setRevealOpen(false)}
          onRevealed={() => load()}
        />
      )}

      <ConfirmModal
        open={!!confirmDelete}
        title="Delete credential"
        message={`Permanently delete "${confirmDelete?.name}"? Encrypted value cannot be recovered.`}
        confirmLabel="Delete"
        destructive
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

function DetailPanel({
  credential, onClose, onRequestReveal, onChange, onDelete,
}: {
  credential: Credential;
  onClose: () => void;
  onRequestReveal: () => void;
  onChange: () => void;
  onDelete: () => void;
}) {
  const toast = useToast();
  const [tab, setTab] = useState<'info' | 'audit'>('info');
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);

  useEffect(() => {
    if (tab !== 'audit') return;
    setAuditLoading(true);
    getAuditLogs(`resource_type=credential&limit=100`)
      .then((rows: any[]) => setAuditLogs(rows.filter((r) => r.resource_id === credential.id)))
      .finally(() => setAuditLoading(false));
  }, [tab, credential.id]);

  return (
    <div className="w-[420px] shrink-0 bg-vm-surface border border-vm-border-bright rounded flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-vm-border flex items-center justify-between">
        <div className="min-w-0">
          <div className="font-semibold text-vm-text-bright truncate">{credential.name}</div>
          <div className="font-mono text-[10px] text-vm-accent uppercase tracking-[2px]">
            {TYPE_LABELS[credential.credential_type] || credential.credential_type} · v{credential.key_version}
          </div>
        </div>
        <button onClick={onClose} className="text-vm-text-dim hover:text-vm-text-bright"><X className="w-4 h-4" /></button>
      </div>

      <div className="flex border-b border-vm-border">
        <button
          onClick={() => setTab('info')}
          className={`flex-1 py-2 font-mono text-[11px] tracking-[2px] uppercase ${tab === 'info' ? 'text-vm-accent border-b-2 border-vm-accent' : 'text-vm-text-dim hover:text-vm-text'}`}
        >Info</button>
        <button
          onClick={() => setTab('audit')}
          className={`flex-1 py-2 font-mono text-[11px] tracking-[2px] uppercase ${tab === 'audit' ? 'text-vm-accent border-b-2 border-vm-accent' : 'text-vm-text-dim hover:text-vm-text'}`}
        >Audit</button>
      </div>

      {tab === 'info' && (
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          <div className="bg-vm-surface2 border border-vm-border rounded p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim">Value</span>
              <button
                onClick={onRequestReveal}
                className="flex items-center gap-1 px-2 py-1 bg-vm-accent text-vm-bg rounded text-[10px] font-bold uppercase tracking-wider hover:bg-vm-accent/90"
              >
                <Eye className="w-3 h-3" /> Reveal
              </button>
            </div>
            <div className="font-mono text-vm-text-bright text-sm">••••••••••••</div>
            <div className="font-mono text-[10px] text-vm-text-dim mt-1">
              Reveal requires re-authentication. Plain value clears from screen after 60s.
            </div>
          </div>

          {credential.description && (
            <Field label="Description" value={credential.description} />
          )}
          <Field label="Tags" value={(credential.tags || []).join(', ') || '—'} />
          <Field label="Expires" value={credential.expires_at ? new Date(credential.expires_at).toLocaleString('sv-SE') : '—'} />
          <Field label="Rotation policy" value={credential.rotation_policy || '—'} />
          <Field label="Provenance" value={credential.provenance || '—'} />
          <Field label="MCP enabled" value={credential.mcp_enabled ? 'Yes' : 'No'} />
          {credential.mcp_enabled && (
            <Field label="MCP scopes" value={(credential.mcp_scopes || []).join(', ') || '—'} />
          )}
          <Field label="Last revealed" value={credential.last_revealed_at ? new Date(credential.last_revealed_at).toLocaleString('sv-SE') : 'Never'} />
          <Field label="Reveal count" value={String(credential.reveal_count || 0)} />
          <Field label="Created" value={new Date(credential.created_at).toLocaleString('sv-SE')} />

          <div className="pt-3 border-t border-vm-border flex gap-2">
            <button
              onClick={onDelete}
              className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10"
            >
              <Trash2 className="w-3 h-3" /> Delete
            </button>
          </div>
        </div>
      )}

      {tab === 'audit' && (
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {auditLoading && <div className="font-mono text-xs text-vm-text-dim">Loading audit log…</div>}
          {!auditLoading && auditLogs.length === 0 && (
            <div className="font-mono text-xs text-vm-text-dim text-center py-6">No audit events yet.</div>
          )}
          {auditLogs.map((l) => (
            <div key={l.id} className="bg-vm-surface2 border border-vm-border rounded p-2.5">
              <div className="flex items-center justify-between mb-1">
                <span className={`font-mono text-[10px] uppercase tracking-[2px] ${
                  l.action.includes('reveal.denied') ? 'text-vm-danger' :
                  l.action.includes('reveal') ? 'text-vm-warning' :
                  l.action.includes('delete') ? 'text-vm-danger' :
                  l.action.includes('create') ? 'text-vm-success' : 'text-vm-accent'
                }`}>{l.action}</span>
                <span className="font-mono text-[10px] text-vm-text-dim">
                  {l.created_at ? new Date(l.created_at).toLocaleString('sv-SE') : ''}
                </span>
              </div>
              <div className="font-mono text-[11px] text-vm-text-bright">{l.username || '—'}</div>
              {l.detail && <div className="font-mono text-[10px] text-vm-text-dim mt-1 break-words">{l.detail}</div>}
              {l.ip_address && <div className="font-mono text-[10px] text-vm-text-dim">IP: {l.ip_address}</div>}
            </div>
          ))}
        </div>
      )}
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
  credentialId, credentialName, onClose, onRevealed,
}: {
  credentialId: string;
  credentialName: string;
  onClose: () => void;
  onRevealed: () => void;
}) {
  const toast = useToast();
  const [password, setPassword] = useState('');
  const [purpose, setPurpose] = useState('manual-copy');
  const [plaintext, setPlaintext] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!plaintext) return;
    setSecondsLeft(60);
    const i = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) {
          clearInterval(i);
          setPlaintext(null);
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(i);
  }, [plaintext]);

  // Clear plaintext from memory whenever this modal closes.
  useEffect(() => () => setPlaintext(null), []);

  const handleReveal = async () => {
    if (!password || !purpose) {
      toast.warning('Password and purpose required.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await revealCredential(credentialId, password, purpose);
      setPlaintext(res.plaintext_value);
      setPassword('');
      onRevealed();
    } catch (e: any) {
      toast.error(`Reveal failed: ${e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopy = async () => {
    if (!plaintext) return;
    try {
      await navigator.clipboard.writeText(plaintext);
      toast.success('Copied to clipboard. Will clear in 30s.');
      setTimeout(() => navigator.clipboard.writeText(' ').catch(() => {}), 30000);
    } catch {
      toast.error('Could not copy — browser blocked clipboard access.');
    }
  };

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-vm-surface2 border border-vm-border-bright rounded shadow-2xl w-full max-w-lg mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-vm-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Eye className="w-4 h-4 text-vm-accent" />
            <span className="font-mono text-xs uppercase tracking-[2px] text-vm-text-bright">Reveal — {credentialName}</span>
          </div>
          <button onClick={onClose} className="text-vm-text-dim hover:text-vm-text-bright"><X className="w-4 h-4" /></button>
        </div>

        {!plaintext && (
          <div className="px-5 py-4 space-y-3">
            <div>
              <label className="block font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim mb-1">Re-authenticate (your password)</label>
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
              <label className="block font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim mb-1">Purpose (audit)</label>
              <input
                type="text"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                className={INPUT}
                placeholder="e.g. deploy-job, manual-check"
              />
            </div>
            <div className="flex items-start gap-2 p-2.5 bg-vm-warning/10 border border-vm-warning/30 rounded">
              <AlertTriangle className="w-4 h-4 text-vm-warning shrink-0 mt-0.5" />
              <div className="font-mono text-[11px] text-vm-warning">
                Plain value will display for 60 seconds and then auto-clear from the screen. Every reveal is audit-logged.
              </div>
            </div>
            <div className="pt-2 flex justify-end gap-2">
              <button onClick={onClose} className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-surface3">Cancel</button>
              <button onClick={handleReveal} disabled={submitting} className="px-3 py-1.5 bg-vm-accent text-vm-bg rounded text-xs font-bold tracking-wider uppercase disabled:opacity-50">
                {submitting ? 'Verifying…' : 'Reveal'}
              </button>
            </div>
          </div>
        )}

        {plaintext && (
          <div className="px-5 py-4 space-y-3">
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim">Plain value</span>
                <span className="font-mono text-[10px] text-vm-warning">Auto-clears in {secondsLeft}s</span>
              </div>
              <pre className="bg-vm-bg border border-vm-accent/30 rounded p-2 text-vm-text-bright text-xs whitespace-pre-wrap break-all">{plaintext}</pre>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={handleCopy} className="flex items-center gap-1 px-3 py-1.5 bg-vm-accent text-vm-bg rounded text-xs font-bold tracking-wider uppercase">
                <Copy className="w-3 h-3" /> Copy
              </button>
              <button onClick={onClose} className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase">
                Close
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function CreateModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const [name, setName] = useState('');
  const [credentialType, setCredentialType] = useState('api_key');
  const [plaintext, setPlaintext] = useState('');
  const [tags, setTags] = useState('');
  const [description, setDescription] = useState('');
  const [showVal, setShowVal] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!name || !plaintext) {
      toast.warning('Name and value are required.');
      return;
    }
    setSubmitting(true);
    try {
      await createCredential({
        name,
        credential_type: credentialType,
        plaintext_value: plaintext,
        tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
        description: description || null,
      });
      toast.success(`Created ${name}`);
      onCreated();
    } catch (e: any) {
      toast.error(`Create failed: ${e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-vm-surface2 border border-vm-border-bright rounded shadow-2xl w-full max-w-lg mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-vm-border flex items-center justify-between">
          <span className="font-mono text-xs uppercase tracking-[2px] text-vm-text-bright">New Credential</span>
          <button onClick={onClose} className="text-vm-text-dim hover:text-vm-text-bright"><X className="w-4 h-4" /></button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <div>
            <label className="block font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim mb-1">Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} className={INPUT} placeholder="e.g. Stripe — Production API Key" />
          </div>
          <div>
            <label className="block font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim mb-1">Type</label>
            <select value={credentialType} onChange={(e) => setCredentialType(e.target.value)} className={INPUT}>
              {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <div>
            <label className="block font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim mb-1">Value (encrypted on save)</label>
            <div className="relative">
              <input
                type={showVal ? 'text' : 'password'}
                value={plaintext}
                onChange={(e) => setPlaintext(e.target.value)}
                className={`${INPUT} pr-10`}
                placeholder="paste secret here"
              />
              <button onClick={() => setShowVal(!showVal)} className="absolute right-2 top-2 text-vm-text-dim hover:text-vm-text-bright">
                {showVal ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <div>
            <label className="block font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim mb-1">Tags (comma-separated)</label>
            <input value={tags} onChange={(e) => setTags(e.target.value)} className={INPUT} placeholder="prod, api, billing" />
          </div>
          <div>
            <label className="block font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim mb-1">Description</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)} className={INPUT} placeholder="optional context" />
          </div>
        </div>
        <div className="px-5 py-3 border-t border-vm-border flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 border border-vm-border text-vm-text-dim rounded text-xs font-bold tracking-wider uppercase">Cancel</button>
          <button onClick={handleSubmit} disabled={submitting} className="px-3 py-1.5 bg-vm-accent text-vm-bg rounded text-xs font-bold tracking-wider uppercase disabled:opacity-50">
            {submitting ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}
