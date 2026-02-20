'use client';

import { useEffect, useState } from 'react';
import { getNotificationChannels, createNotificationChannel, updateNotificationChannel, deleteNotificationChannel, testNotificationChannel } from '@/lib/api';
import FormLabel from '@/components/FormLabel';
import { useT } from '@/lib/i18n';
import { Plus, Trash2, TestTube, Bell, Send, Eye, EyeOff, Pencil, X } from 'lucide-react';

const INPUT = "w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent";

const TRIGGER_OPTIONS = [
  { value: 'run.success', label: 'Backup success' },
  { value: 'run.failed', label: 'Backup failed' },
  { value: 'run.started', label: 'Backup started' },
  { value: 'restore.started', label: 'Restore started' },
  { value: 'restore.completed', label: 'Restore completed' },
  { value: 'restore.failed', label: 'Restore failed' },
  { value: 'server.offline', label: 'Server offline' },
  { value: 'storage.warning', label: 'Storage warning (>70%)' },
  { value: 'storage.critical', label: 'Storage critical (>90%)' },
];

const TYPE_LABELS: Record<string, string> = { slack: 'Slack', ntfy: 'ntfy', telegram: 'Telegram', email: 'Email', webhook: 'Webhook' };

export default function NotificationsPage() {
  const t = useT();
  const [channels, setChannels] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [channelType, setChannelType] = useState('slack');
  const [name, setName] = useState('');
  const [triggers, setTriggers] = useState<string[]>(['run.success', 'run.failed']);
  const [showSecret, setShowSecret] = useState(false);
  const [testResults, setTestResults] = useState<Record<string, any>>({});

  // Per-channel config fields
  const [slackWebhookUrl, setSlackWebhookUrl] = useState('');
  const [slackChannel, setSlackChannel] = useState('');
  const [ntfyTopic, setNtfyTopic] = useState('');
  const [ntfyServer, setNtfyServer] = useState('https://ntfy.sh');
  const [telegramBotToken, setTelegramBotToken] = useState('');
  const [telegramChatId, setTelegramChatId] = useState('');
  const [emailRecipients, setEmailRecipients] = useState('');
  const [emailSubjectPrefix, setEmailSubjectPrefix] = useState('[VaultMaster]');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [webhookSecret, setWebhookSecret] = useState('');

  const load = () => getNotificationChannels().then(setChannels).catch(() => {});
  useEffect(() => { load(); }, []);

  const buildConfig = (): Record<string, any> => {
    switch (channelType) {
      case 'slack': return { webhook_url: slackWebhookUrl, channel: slackChannel || undefined };
      case 'ntfy': return { topic: ntfyTopic, server: ntfyServer };
      case 'telegram': return { bot_token: telegramBotToken, chat_id: telegramChatId };
      case 'email': return { recipients: emailRecipients.split(',').map(e => e.trim()).filter(Boolean), subject_prefix: emailSubjectPrefix };
      case 'webhook': return { url: webhookUrl, secret: webhookSecret || undefined };
      default: return {};
    }
  };

  const resetForm = () => {
    setName(''); setChannelType('slack'); setTriggers(['run.success', 'run.failed']); setEditId(null);
    setSlackWebhookUrl(''); setSlackChannel(''); setNtfyTopic(''); setNtfyServer('https://ntfy.sh');
    setTelegramBotToken(''); setTelegramChatId(''); setEmailRecipients(''); setEmailSubjectPrefix('[VaultMaster]');
    setWebhookUrl(''); setWebhookSecret('');
  };

  const openNew = () => { resetForm(); setShowForm(true); };
  const openEdit = (c: any) => {
    setEditId(c.id); setName(c.name); setChannelType(c.channel_type); setTriggers(c.triggers || []);
    const cfg = c.config || {};
    if (c.channel_type === 'slack') { setSlackWebhookUrl(cfg.webhook_url || ''); setSlackChannel(cfg.channel || ''); }
    if (c.channel_type === 'ntfy') { setNtfyTopic(cfg.topic || ''); setNtfyServer(cfg.server || 'https://ntfy.sh'); }
    if (c.channel_type === 'telegram') { setTelegramBotToken(''); setTelegramChatId(cfg.chat_id || ''); }
    if (c.channel_type === 'email') { setEmailRecipients((cfg.recipients || []).join(', ')); setEmailSubjectPrefix(cfg.subject_prefix || '[VaultMaster]'); }
    if (c.channel_type === 'webhook') { setWebhookUrl(cfg.url || ''); setWebhookSecret(''); }
    setShowForm(true);
  };
  const closeForm = () => { setShowForm(false); setEditId(null); };

  const handleSave = async () => {
    const payload = { name, channel_type: channelType, config: buildConfig(), triggers };
    if (editId) {
      await updateNotificationChannel(editId, payload);
    } else {
      await createNotificationChannel(payload);
    }
    closeForm(); resetForm();
    load();
  };

  const handleTest = async (id: string) => {
    const res = await testNotificationChannel(id);
    setTestResults((p: any) => ({ ...p, [id]: res }));
  };

  const toggleTrigger = (t: string) => {
    setTriggers(prev => prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]);
  };

  const SecretInput = ({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) => (
    <div className="relative">
      <input type={showSecret ? 'text' : 'password'} value={value} onChange={e => onChange(e.target.value)} className={INPUT + ' pr-10'} placeholder={placeholder} />
      <button type="button" onClick={() => setShowSecret(!showSecret)} className="absolute right-3 top-1/2 -translate-y-1/2 text-vm-text-dim hover:text-vm-accent">
        {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      </button>
    </div>
  );

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">Notifications</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">// NOTIFICATION CHANNELS · {channels.length} TOTAL</div>
        </div>
        <button onClick={openNew} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase hover:bg-[#33ddff] transition-all glow">
          <Plus className="w-4 h-4" /> {t('notif.new')}
        </button>
      </div>

      {showForm && (
        <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold text-vm-text-bright uppercase tracking-wider">{editId ? t('notif.edit') : t('notif.new')}</h3>
            <button onClick={closeForm} className="text-vm-text-dim hover:text-vm-text"><X className="w-5 h-5" /></button>
          </div>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <FormLabel label="Name" tooltip="A friendly name for this notification channel." />
              <input value={name} onChange={e => setName(e.target.value)} className={INPUT} placeholder="Production alerts" />
            </div>
            <div>
              <FormLabel label="Channel Type" tooltip="Where notifications will be sent. Each type has its own configuration." />
              <select value={channelType} onChange={e => setChannelType(e.target.value)} className={INPUT}>
                <option value="slack">💬 Slack</option>
                <option value="ntfy">📱 ntfy</option>
                <option value="telegram">✈️ Telegram</option>
                <option value="email">📧 Email</option>
                <option value="webhook">🔗 Webhook</option>
              </select>
            </div>
          </div>

          {/* Per-channel config */}
          <div className="bg-vm-surface2 border border-vm-border rounded p-4 mb-4">
            <div className="font-mono text-[10px] text-vm-accent tracking-[2px] uppercase mb-3">// {TYPE_LABELS[channelType]} Configuration</div>

            {channelType === 'slack' && (
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <FormLabel label="Webhook URL" tooltip="Slack Incoming Webhook URL. Create one at api.slack.com → Your App → Incoming Webhooks." />
                  <input value={slackWebhookUrl} onChange={e => setSlackWebhookUrl(e.target.value)} className={INPUT} placeholder="https://hooks.slack.com/services/T.../B.../..." />
                </div>
                <div className="col-span-2">
                  <FormLabel label="Channel Override" tooltip="Optional. Override the default channel set in the webhook. Example: #backup-alerts" />
                  <input value={slackChannel} onChange={e => setSlackChannel(e.target.value)} className={INPUT} placeholder="#backup-alerts (optional)" />
                </div>
              </div>
            )}

            {channelType === 'ntfy' && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <FormLabel label="Topic" tooltip="The ntfy topic to publish to. Anyone subscribed to this topic will receive notifications." />
                  <input value={ntfyTopic} onChange={e => setNtfyTopic(e.target.value)} className={INPUT} placeholder="vaultmaster-alerts" />
                </div>
                <div>
                  <FormLabel label="Server" tooltip="ntfy server URL. Default is the public ntfy.sh server. Use your own for private topics." />
                  <input value={ntfyServer} onChange={e => setNtfyServer(e.target.value)} className={INPUT} placeholder="https://ntfy.sh" />
                </div>
              </div>
            )}

            {channelType === 'telegram' && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <FormLabel label="Bot Token" tooltip="Telegram Bot API token. Create a bot via @BotFather and copy the token." />
                  <SecretInput value={telegramBotToken} onChange={setTelegramBotToken} placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11" />
                </div>
                <div>
                  <FormLabel label="Chat ID" tooltip="Telegram chat/group/channel ID. Send a message to @userinfobot to find your ID." />
                  <input value={telegramChatId} onChange={e => setTelegramChatId(e.target.value)} className={INPUT} placeholder="-1001234567890" />
                </div>
              </div>
            )}

            {channelType === 'email' && (
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <FormLabel label="Recipients" tooltip="Comma-separated email addresses to send notifications to. Requires SMTP settings in .env." />
                  <input value={emailRecipients} onChange={e => setEmailRecipients(e.target.value)} className={INPUT} placeholder="admin@example.com, ops@example.com" />
                </div>
                <div className="col-span-2">
                  <FormLabel label="Subject Prefix" tooltip="Prefix added to all email subjects for easy filtering." />
                  <input value={emailSubjectPrefix} onChange={e => setEmailSubjectPrefix(e.target.value)} className={INPUT} placeholder="[VaultMaster]" />
                </div>
              </div>
            )}

            {channelType === 'webhook' && (
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <FormLabel label="Webhook URL" tooltip="URL to POST JSON payloads to when events occur." />
                  <input value={webhookUrl} onChange={e => setWebhookUrl(e.target.value)} className={INPUT} placeholder="https://example.com/webhook" />
                </div>
                <div className="col-span-2">
                  <FormLabel label="Signing Secret" tooltip="Optional HMAC secret for verifying webhook authenticity. Sent as X-VaultMaster-Signature header." />
                  <SecretInput value={webhookSecret} onChange={setWebhookSecret} placeholder="Optional signing secret" />
                </div>
              </div>
            )}
          </div>

          {/* Trigger checkboxes */}
          <div className="mb-4">
            <FormLabel label="Triggers" tooltip="Select which events should send notifications through this channel." />
            <div className="grid grid-cols-3 gap-2 mt-1">
              {TRIGGER_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => toggleTrigger(opt.value)}
                  className={`text-left px-3 py-2 rounded border font-mono text-[11px] transition-all ${triggers.includes(opt.value) ? 'bg-vm-accent/10 border-vm-accent text-vm-accent' : 'bg-vm-surface2 border-vm-border text-vm-text-dim hover:border-vm-accent/50'}`}
                >
                  <span className={`inline-block w-3 h-3 rounded-sm border mr-2 align-middle ${triggers.includes(opt.value) ? 'bg-vm-accent border-vm-accent' : 'border-vm-border'}`}>
                    {triggers.includes(opt.value) && <span className="block w-full h-full text-center text-[8px] text-vm-bg leading-3">✓</span>}
                  </span>
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-3">
            <button onClick={handleSave} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">{editId ? t('action.update') : t('action.save')}</button>
            <button onClick={closeForm} className="px-4 py-2.5 text-vm-text-dim font-bold text-sm tracking-wider uppercase hover:text-vm-text">{t('action.cancel')}</button>
          </div>
        </div>
      )}

      <div className="space-y-3">
        {channels.map((c: any) => (
          <div key={c.id} className="bg-vm-surface border border-vm-border rounded p-5 flex items-center gap-4 hover:border-vm-border-bright transition-all">
            <div className="w-10 h-10 rounded bg-vm-accent/10 flex items-center justify-center text-vm-accent"><Send className="w-5 h-5" /></div>
            <div className="flex-1">
              <div className="font-semibold text-vm-text-bright">{c.name}</div>
              <div className="font-mono text-[11px] text-vm-text-dim">{TYPE_LABELS[c.channel_type] || c.channel_type}</div>
              {c.triggers?.length > 0 && (
                <div className="flex gap-1 mt-1.5 flex-wrap">
                  {c.triggers.map((t: string) => (
                    <span key={t} className="font-mono text-[9px] px-1.5 py-0.5 rounded-sm bg-vm-accent/[0.06] text-vm-accent border border-vm-accent/20 uppercase">{t}</span>
                  ))}
                </div>
              )}
            </div>
            {testResults[c.id] && (
              <div className={`font-mono text-xs px-3 py-1 rounded ${testResults[c.id].success ? 'bg-vm-success/10 text-vm-success' : 'bg-vm-danger/10 text-vm-danger'}`}>
                {testResults[c.id].message}
              </div>
            )}
            <div className="flex gap-2">
              <button onClick={() => openEdit(c)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08]">
                <Pencil className="w-3 h-3" /> {t('action.edit')}
              </button>
              <button onClick={() => handleTest(c.id)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08]">
                <TestTube className="w-3 h-3" /> {t('action.test')}
              </button>
              <button onClick={async () => { if (confirm(t('notif.confirm_delete'))) { await deleteNotificationChannel(c.id); load(); }}} className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10">
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          </div>
        ))}
        {channels.length === 0 && (
          <div className="text-center py-12 text-vm-text-dim font-mono">
            <Bell className="w-12 h-12 mx-auto mb-3 opacity-40" />
            <div className="tracking-[2px]">No notification channels configured</div>
          </div>
        )}
      </div>
    </div>
  );
}
