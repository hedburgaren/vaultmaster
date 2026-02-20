'use client';

import { useEffect, useState } from 'react';
import { getStorageDestinations, createStorageDestination, updateStorageDestination, deleteStorageDestination, testStorage, getOAuthRedirectUri, startOAuth, pollOAuthToken } from '@/lib/api';
import { formatBytes } from '@/lib/utils';
import { useT } from '@/lib/i18n';
import FormLabel from '@/components/FormLabel';
import CapacityInput from '@/components/CapacityInput';
import { Plus, Trash2, TestTube, Database, HardDrive, Cloud, Globe, Server, Eye, EyeOff, Pencil, X, ExternalLink, Copy, Loader2, CheckCircle2, KeyRound } from 'lucide-react';

const INPUT = "w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent";

const BACKEND_LABELS: Record<string, string> = { local: 'Local Disk', s3: 'S3 / DO Spaces', sftp: 'SFTP Server', b2: 'Backblaze B2', gdrive: 'Google Drive', onedrive: 'OneDrive' };

export default function StoragePage() {
  const t = useT();
  const [dests, setDests] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [backend, setBackend] = useState('local');
  const [name, setName] = useState('');
  const [capacityBytes, setCapacityBytes] = useState<number | null>(null);
  const [showSecret, setShowSecret] = useState(false);

  // Per-backend config fields
  const [localPath, setLocalPath] = useState('/mnt/backups');
  const [s3Endpoint, setS3Endpoint] = useState('');
  const [s3Bucket, setS3Bucket] = useState('');
  const [s3Region, setS3Region] = useState('us-east-1');
  const [s3AccessKey, setS3AccessKey] = useState('');
  const [s3SecretKey, setS3SecretKey] = useState('');
  const [sftpHost, setSftpHost] = useState('');
  const [sftpPort, setSftpPort] = useState('22');
  const [sftpUser, setSftpUser] = useState('');
  const [sftpPassword, setSftpPassword] = useState('');
  const [sftpPath, setSftpPath] = useState('/backups');
  const [b2KeyId, setB2KeyId] = useState('');
  const [b2AppKey, setB2AppKey] = useState('');
  const [b2Bucket, setB2Bucket] = useState('');
  const [gdriveClientId, setGdriveClientId] = useState('');
  const [gdriveClientSecret, setGdriveClientSecret] = useState('');
  const [gdriveFolderId, setGdriveFolderId] = useState('');
  const [onedriveClientId, setOnedriveClientId] = useState('');
  const [onedriveClientSecret, setOnedriveClientSecret] = useState('');
  const [onedriveDriveId, setOnedriveDriveId] = useState('');
  const [onedriveFolderPath, setOnedriveFolderPath] = useState('/Backups');

  // OAuth state
  const [gdriveToken, setGdriveToken] = useState('');
  const [onedriveToken, setOnedriveToken] = useState('');
  const [redirectUri, setRedirectUri] = useState('');
  const [oauthState, setOauthState] = useState('');
  const [oauthPolling, setOauthPolling] = useState(false);
  const [oauthStatus, setOauthStatus] = useState<'idle' | 'waiting' | 'complete' | 'error'>('idle');
  const [copiedUri, setCopiedUri] = useState(false);

  const [testResults, setTestResults] = useState<Record<string, any>>({});

  const load = () => getStorageDestinations().then(setDests).catch(() => {});
  useEffect(() => { load(); getOAuthRedirectUri().then(r => setRedirectUri(r.redirect_uri)).catch(() => {}); }, []);

  // OAuth polling effect — polls every 2s for up to 5 minutes
  useEffect(() => {
    if (!oauthState || !oauthPolling) return;
    let failures = 0;
    const interval = setInterval(async () => {
      try {
        const res = await pollOAuthToken(oauthState);
        failures = 0;
        if (res.status === 'complete') {
          if (backend === 'gdrive') setGdriveToken(res.token);
          if (backend === 'onedrive') setOnedriveToken(res.token);
          setOauthStatus('complete');
          setOauthPolling(false);
          setOauthState('');
        } else if (res.status === 'expired') {
          setOauthStatus('error');
          setOauthPolling(false);
          setOauthState('');
        }
        // status === 'pending' → keep polling
      } catch {
        failures++;
        if (failures > 5) { setOauthStatus('error'); setOauthPolling(false); }
      }
    }, 2000);
    // Auto-stop after 5 minutes
    const timeout = setTimeout(() => { setOauthPolling(false); setOauthStatus('error'); }, 300_000);
    return () => { clearInterval(interval); clearTimeout(timeout); };
  }, [oauthState, oauthPolling, backend]);

  const buildConfig = (): Record<string, any> => {
    switch (backend) {
      case 'local': return { path: localPath };
      case 's3': return { endpoint: s3Endpoint, bucket: s3Bucket, region: s3Region, access_key: s3AccessKey, secret_key: s3SecretKey };
      case 'sftp': return { host: sftpHost, port: parseInt(sftpPort), user: sftpUser, password: sftpPassword, path: sftpPath };
      case 'b2': return { key_id: b2KeyId, application_key: b2AppKey, bucket: b2Bucket };
      case 'gdrive': return { client_id: gdriveClientId, client_secret: gdriveClientSecret, folder_id: gdriveFolderId, token: gdriveToken || undefined };
      case 'onedrive': return { client_id: onedriveClientId, client_secret: onedriveClientSecret, drive_id: onedriveDriveId, folder_path: onedriveFolderPath, token: onedriveToken || undefined };
      default: return {};
    }
  };

  const resetForm = () => {
    setName(''); setBackend('local'); setCapacityBytes(null); setEditId(null);
    setLocalPath('/mnt/backups'); setS3Endpoint(''); setS3Bucket(''); setS3Region('us-east-1'); setS3AccessKey(''); setS3SecretKey('');
    setSftpHost(''); setSftpPort('22'); setSftpUser(''); setSftpPassword(''); setSftpPath('/backups');
    setB2KeyId(''); setB2AppKey(''); setB2Bucket('');
    setGdriveClientId(''); setGdriveClientSecret(''); setGdriveFolderId(''); setGdriveToken('');
    setOnedriveClientId(''); setOnedriveClientSecret(''); setOnedriveDriveId(''); setOnedriveFolderPath('/Backups'); setOnedriveToken('');
    setOauthState(''); setOauthPolling(false); setOauthStatus('idle');
  };

  const openNew = () => { resetForm(); setShowForm(true); };
  const openEdit = (d: any) => {
    setEditId(d.id); setName(d.name); setBackend(d.backend); setCapacityBytes(d.capacity_bytes);
    const c = d.config || {};
    if (d.backend === 'local') { setLocalPath(c.path || '/mnt/backups'); }
    if (d.backend === 's3') { setS3Endpoint(c.endpoint || ''); setS3Bucket(c.bucket || ''); setS3Region(c.region || 'us-east-1'); setS3AccessKey(c.access_key || ''); setS3SecretKey(''); }
    if (d.backend === 'sftp') { setSftpHost(c.host || ''); setSftpPort(String(c.port || 22)); setSftpUser(c.user || ''); setSftpPassword(''); setSftpPath(c.path || '/backups'); }
    if (d.backend === 'b2') { setB2KeyId(c.key_id || ''); setB2AppKey(''); setB2Bucket(c.bucket || ''); }
    if (d.backend === 'gdrive') { setGdriveClientId(c.client_id || ''); setGdriveClientSecret(''); setGdriveFolderId(c.folder_id || ''); setGdriveToken(c.token || ''); setOauthStatus(c.token ? 'complete' : 'idle'); }
    if (d.backend === 'onedrive') { setOnedriveClientId(c.client_id || ''); setOnedriveClientSecret(''); setOnedriveDriveId(c.drive_id || ''); setOnedriveFolderPath(c.folder_path || '/Backups'); setOnedriveToken(c.token || ''); setOauthStatus(c.token ? 'complete' : 'idle'); }
    setShowForm(true);
  };
  const closeForm = () => { setShowForm(false); setEditId(null); };

  const handleSave = async () => {
    const payload = { name, backend, config: buildConfig(), capacity_bytes: capacityBytes };
    if (editId) {
      await updateStorageDestination(editId, payload);
    } else {
      await createStorageDestination(payload);
    }
    closeForm(); resetForm();
    load();
  };

  const handleTest = async (id: string) => {
    const res = await testStorage(id);
    setTestResults((p: any) => ({ ...p, [id]: res }));
  };

  const backendIcon = (b: string) => {
    switch (b) {
      case 'local': return <HardDrive className="w-5 h-5" />;
      case 'sftp': return <Server className="w-5 h-5" />;
      case 'gdrive': case 'onedrive': return <Globe className="w-5 h-5" />;
      default: return <Cloud className="w-5 h-5" />;
    }
  };

  const secretInput = (value: string, onChange: (v: string) => void, placeholder: string) => (
    <div className="relative">
      <input type={showSecret ? 'text' : 'password'} value={value} onChange={e => onChange(e.target.value)} className={INPUT + ' pr-10'}
        placeholder={editId ? `••••••••  (${t('storage.secret_kept')})` : placeholder} />
      <button type="button" onClick={() => setShowSecret(!showSecret)} className="absolute right-3 top-1/2 -translate-y-1/2 text-vm-text-dim hover:text-vm-accent">
        {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      </button>
    </div>
  );

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">{t('storage.title')}</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">{t('storage.subtitle_prefix')} {dests.length} {t('common.total')}</div>
        </div>
        <button onClick={openNew} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase hover:bg-[#33ddff] transition-all glow">
          <Plus className="w-4 h-4" /> {t('storage.add')}
        </button>
      </div>

      {showForm && (
        <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold text-vm-text-bright uppercase tracking-wider">{editId ? t('storage.edit') : t('storage.new')}</h3>
            <button onClick={closeForm} className="text-vm-text-dim hover:text-vm-text"><X className="w-5 h-5" /></button>
          </div>

          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <FormLabel label={t('storage.form_name')} tooltip={t('storage.form_name_tip')} />
              <input value={name} onChange={e => setName(e.target.value)} className={INPUT} placeholder="Primary backup disk" />
            </div>
            <div>
              <FormLabel label={t('storage.form_backend')} tooltip={t('storage.form_backend_tip')} />
              <select value={backend} onChange={e => setBackend(e.target.value)} className={INPUT}>
                <option value="local">💾 Local Disk</option>
                <option value="s3">☁️ S3 / DO Spaces</option>
                <option value="sftp">🖥️ SFTP Server</option>
                <option value="b2">🔷 Backblaze B2</option>
                <option value="gdrive">📁 Google Drive</option>
                <option value="onedrive">☁️ OneDrive / SharePoint</option>
              </select>
            </div>
          </div>

          {/* Per-backend config fields */}
          <div className="bg-vm-surface2 border border-vm-border rounded p-4 mb-4">
            <div className="font-mono text-[10px] text-vm-accent tracking-[2px] uppercase mb-3">// {BACKEND_LABELS[backend] || backend} Configuration</div>

            {backend === 'local' && (
              <div>
                <FormLabel label={t('storage.local_path')} tooltip={t('storage.local_path_tip')} />
                <input value={localPath} onChange={e => setLocalPath(e.target.value)} className={INPUT} placeholder="/mnt/backups" />
              </div>
            )}

            {backend === 's3' && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <FormLabel label={t('storage.s3_endpoint')} tooltip={t('storage.s3_endpoint_tip')} />
                  <input value={s3Endpoint} onChange={e => setS3Endpoint(e.target.value)} className={INPUT} placeholder="https://ams3.digitaloceanspaces.com" />
                </div>
                <div>
                  <FormLabel label={t('storage.s3_bucket')} tooltip={t('storage.s3_bucket_tip')} />
                  <input value={s3Bucket} onChange={e => setS3Bucket(e.target.value)} className={INPUT} placeholder="my-backups" />
                </div>
                <div>
                  <FormLabel label={t('storage.s3_region')} tooltip={t('storage.s3_region_tip')} />
                  <input value={s3Region} onChange={e => setS3Region(e.target.value)} className={INPUT} placeholder="us-east-1" />
                </div>
                <div>
                  <FormLabel label={t('storage.s3_access_key')} tooltip={t('storage.s3_access_key_tip')} />
                  <input value={s3AccessKey} onChange={e => setS3AccessKey(e.target.value)} className={INPUT} placeholder="AKIAIOSFODNN7EXAMPLE" />
                </div>
                <div className="col-span-2">
                  <FormLabel label={t('storage.s3_secret_key')} tooltip={t('storage.s3_secret_key_tip')} />
                  {secretInput(s3SecretKey, setS3SecretKey, 'Enter secret key')}
                </div>
              </div>
            )}

            {backend === 'sftp' && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <FormLabel label={t('storage.sftp_host')} tooltip={t('storage.sftp_host_tip')} />
                  <input value={sftpHost} onChange={e => setSftpHost(e.target.value)} className={INPUT} placeholder="backup.example.com" />
                </div>
                <div>
                  <FormLabel label={t('storage.sftp_port')} tooltip={t('storage.sftp_port_tip')} />
                  <input type="number" value={sftpPort} onChange={e => setSftpPort(e.target.value)} className={INPUT} />
                </div>
                <div>
                  <FormLabel label={t('storage.sftp_user')} tooltip={t('storage.sftp_user_tip')} />
                  <input value={sftpUser} onChange={e => setSftpUser(e.target.value)} className={INPUT} placeholder="backup-user" />
                </div>
                <div>
                  <FormLabel label={t('storage.sftp_password')} tooltip={t('storage.sftp_password_tip')} />
                  {secretInput(sftpPassword, setSftpPassword, 'Enter password')}
                </div>
                <div className="col-span-2">
                  <FormLabel label={t('storage.sftp_path')} tooltip={t('storage.sftp_path_tip')} />
                  <input value={sftpPath} onChange={e => setSftpPath(e.target.value)} className={INPUT} placeholder="/backups" />
                </div>
              </div>
            )}

            {backend === 'b2' && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <FormLabel label={t('storage.b2_key_id')} tooltip={t('storage.b2_key_id_tip')} />
                  <input value={b2KeyId} onChange={e => setB2KeyId(e.target.value)} className={INPUT} placeholder="0012345678abcdef0000000001" />
                </div>
                <div>
                  <FormLabel label={t('storage.b2_app_key')} tooltip={t('storage.b2_app_key_tip')} />
                  {secretInput(b2AppKey, setB2AppKey, 'Enter application key')}
                </div>
                <div className="col-span-2">
                  <FormLabel label={t('storage.b2_bucket')} tooltip={t('storage.b2_bucket_tip')} />
                  <input value={b2Bucket} onChange={e => setB2Bucket(e.target.value)} className={INPUT} placeholder="my-backups" />
                </div>
              </div>
            )}

            {backend === 'gdrive' && (
              <div className="space-y-4">
                {/* Redirect URI info box */}
                <div className="bg-vm-accent/5 border border-vm-accent/20 rounded p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <KeyRound className="w-3.5 h-3.5 text-vm-accent" />
                    <span className="font-mono text-[10px] text-vm-accent tracking-[2px] uppercase">{t('storage.oauth_redirect_uri')}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 font-mono text-[11px] text-vm-text bg-vm-surface px-2 py-1.5 rounded border border-vm-border truncate">{redirectUri}</code>
                    <button type="button" onClick={() => { navigator.clipboard.writeText(redirectUri); setCopiedUri(true); setTimeout(() => setCopiedUri(false), 2000); }}
                      className="flex items-center gap-1 px-2 py-1.5 text-[10px] font-bold text-vm-accent border border-vm-accent/40 rounded uppercase tracking-wider hover:bg-vm-accent/10">
                      {copiedUri ? <CheckCircle2 className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                      {copiedUri ? t('storage.oauth_copied') : t('storage.oauth_copy')}
                    </button>
                  </div>
                  <div className="font-mono text-[10px] text-vm-text-dim mt-1.5">{t('storage.oauth_redirect_uri_tip')}</div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <FormLabel label={t('storage.gdrive_client_id')} tooltip={t('storage.gdrive_client_id_tip')} />
                    <input value={gdriveClientId} onChange={e => setGdriveClientId(e.target.value)} className={INPUT} placeholder="123456789.apps.googleusercontent.com" />
                  </div>
                  <div>
                    <FormLabel label={t('storage.gdrive_client_secret')} tooltip={t('storage.gdrive_client_secret_tip')} />
                    {secretInput(gdriveClientSecret, setGdriveClientSecret, 'Enter client secret')}
                  </div>
                  <div className="col-span-2">
                    <FormLabel label={t('storage.gdrive_folder_id')} tooltip={t('storage.gdrive_folder_id_tip')} />
                    <input value={gdriveFolderId} onChange={e => setGdriveFolderId(e.target.value)} className={INPUT} placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms" />
                  </div>
                </div>
                {/* OAuth authorize + token */}
                <div className="border-t border-vm-border pt-3">
                  <FormLabel label={t('storage.oauth_token')} tooltip={t('storage.oauth_token_tip')} />
                  <div className="flex gap-2 mb-2">
                    <button type="button" disabled={!gdriveClientId || !gdriveClientSecret || oauthPolling}
                      onClick={async () => {
                        setOauthStatus('waiting');
                        try {
                          const res = await startOAuth('gdrive', gdriveClientId, gdriveClientSecret);
                          setOauthState(res.state);
                          setOauthPolling(true);
                          window.open(res.auth_url, '_blank', 'width=600,height=700');
                        } catch { setOauthStatus('error'); }
                      }}
                      className="flex items-center gap-1.5 px-3 py-2 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08] disabled:opacity-50">
                      {oauthPolling ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ExternalLink className="w-3.5 h-3.5" />}
                      {oauthPolling ? t('storage.oauth_waiting') : t('storage.oauth_authorize')}
                    </button>
                    {oauthStatus === 'complete' && <span className="flex items-center gap-1 text-vm-success font-mono text-xs"><CheckCircle2 className="w-3.5 h-3.5" /> {t('storage.oauth_success')}</span>}
                    {oauthStatus === 'error' && <span className="text-vm-danger font-mono text-xs">{t('storage.oauth_error')}</span>}
                  </div>
                  <textarea value={gdriveToken} onChange={e => setGdriveToken(e.target.value)} className={INPUT + ' h-16 resize-y font-mono text-[10px]'} placeholder={t('storage.oauth_token_placeholder')} />
                </div>
              </div>
            )}

            {backend === 'onedrive' && (
              <div className="space-y-4">
                {/* Redirect URI info box */}
                <div className="bg-vm-accent/5 border border-vm-accent/20 rounded p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <KeyRound className="w-3.5 h-3.5 text-vm-accent" />
                    <span className="font-mono text-[10px] text-vm-accent tracking-[2px] uppercase">{t('storage.oauth_redirect_uri')}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 font-mono text-[11px] text-vm-text bg-vm-surface px-2 py-1.5 rounded border border-vm-border truncate">{redirectUri}</code>
                    <button type="button" onClick={() => { navigator.clipboard.writeText(redirectUri); setCopiedUri(true); setTimeout(() => setCopiedUri(false), 2000); }}
                      className="flex items-center gap-1 px-2 py-1.5 text-[10px] font-bold text-vm-accent border border-vm-accent/40 rounded uppercase tracking-wider hover:bg-vm-accent/10">
                      {copiedUri ? <CheckCircle2 className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                      {copiedUri ? t('storage.oauth_copied') : t('storage.oauth_copy')}
                    </button>
                  </div>
                  <div className="font-mono text-[10px] text-vm-text-dim mt-1.5">{t('storage.oauth_redirect_uri_tip_onedrive')}</div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <FormLabel label={t('storage.onedrive_client_id')} tooltip={t('storage.onedrive_client_id_tip')} />
                    <input value={onedriveClientId} onChange={e => setOnedriveClientId(e.target.value)} className={INPUT} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
                  </div>
                  <div>
                    <FormLabel label={t('storage.onedrive_client_secret')} tooltip={t('storage.onedrive_client_secret_tip')} />
                    {secretInput(onedriveClientSecret, setOnedriveClientSecret, 'Enter client secret')}
                  </div>
                  <div>
                    <FormLabel label={t('storage.onedrive_drive_id')} tooltip={t('storage.onedrive_drive_id_tip')} />
                    <input value={onedriveDriveId} onChange={e => setOnedriveDriveId(e.target.value)} className={INPUT} placeholder="Optional — leave empty for default" />
                  </div>
                  <div>
                    <FormLabel label={t('storage.onedrive_folder_path')} tooltip={t('storage.onedrive_folder_path_tip')} />
                    <input value={onedriveFolderPath} onChange={e => setOnedriveFolderPath(e.target.value)} className={INPUT} placeholder="/Backups" />
                  </div>
                </div>
                {/* OAuth authorize + token */}
                <div className="border-t border-vm-border pt-3">
                  <FormLabel label={t('storage.oauth_token')} tooltip={t('storage.oauth_token_tip')} />
                  <div className="flex gap-2 mb-2">
                    <button type="button" disabled={!onedriveClientId || !onedriveClientSecret || oauthPolling}
                      onClick={async () => {
                        setOauthStatus('waiting');
                        try {
                          const res = await startOAuth('onedrive', onedriveClientId, onedriveClientSecret);
                          setOauthState(res.state);
                          setOauthPolling(true);
                          window.open(res.auth_url, '_blank', 'width=600,height=700');
                        } catch { setOauthStatus('error'); }
                      }}
                      className="flex items-center gap-1.5 px-3 py-2 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08] disabled:opacity-50">
                      {oauthPolling ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ExternalLink className="w-3.5 h-3.5" />}
                      {oauthPolling ? t('storage.oauth_waiting') : t('storage.oauth_authorize')}
                    </button>
                    {oauthStatus === 'complete' && <span className="flex items-center gap-1 text-vm-success font-mono text-xs"><CheckCircle2 className="w-3.5 h-3.5" /> {t('storage.oauth_success')}</span>}
                    {oauthStatus === 'error' && <span className="text-vm-danger font-mono text-xs">{t('storage.oauth_error')}</span>}
                  </div>
                  <textarea value={onedriveToken} onChange={e => setOnedriveToken(e.target.value)} className={INPUT + ' h-16 resize-y font-mono text-[10px]'} placeholder={t('storage.oauth_token_placeholder')} />
                </div>
              </div>
            )}
          </div>

          <div className="mb-4">
            <FormLabel label={t('storage.form_capacity')} tooltip={t('storage.form_capacity_tip')} />
            <CapacityInput value={capacityBytes} onChange={setCapacityBytes} />
          </div>

          <div className="flex gap-3">
            <button onClick={handleSave} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">{editId ? t('action.update') : t('action.save')}</button>
            <button onClick={closeForm} className="px-4 py-2.5 text-vm-text-dim font-bold text-sm tracking-wider uppercase hover:text-vm-text">{t('action.cancel')}</button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        {dests.map((d: any) => {
          const pct = d.capacity_bytes ? Math.round((d.used_bytes || 0) / d.capacity_bytes * 100) : null;
          return (
            <div key={d.id} className="bg-vm-surface border border-vm-border rounded p-5 hover:border-vm-border-bright hover:-translate-y-0.5 transition-all">
              <div className="flex items-center gap-2.5 mb-4">
                <div className="w-9 h-9 rounded bg-vm-accent/10 flex items-center justify-center text-vm-accent">{backendIcon(d.backend)}</div>
                <div>
                  <div className="font-semibold text-vm-text-bright">{d.name}</div>
                  <div className="font-mono text-[11px] text-vm-text-dim">{BACKEND_LABELS[d.backend] || d.backend}</div>
                </div>
              </div>
              {pct !== null && (
                <div className="mb-3">
                  <div className="flex justify-between font-mono text-[11px] text-vm-text-dim mb-1.5">
                    <span>{t('storage.used')}</span>
                    <strong className="text-vm-text">{formatBytes(d.used_bytes)} / {formatBytes(d.capacity_bytes)}</strong>
                  </div>
                  <div className="h-1.5 bg-vm-surface3 rounded overflow-hidden">
                    <div className={`h-full rounded ${pct > 90 ? 'bg-vm-danger' : pct > 70 ? 'bg-vm-warning' : 'bg-vm-success'}`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )}
              {testResults[d.id] && (
                <div className={`font-mono text-xs p-2 rounded mb-3 ${testResults[d.id].success ? 'bg-vm-success/10 text-vm-success border border-vm-success/30' : 'bg-vm-danger/10 text-vm-danger border border-vm-danger/30'}`}>
                  {testResults[d.id].message}
                </div>
              )}
              <div className="flex gap-2">
                <button onClick={() => openEdit(d)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08]">
                  <Pencil className="w-3 h-3" /> {t('action.edit')}
                </button>
                <button onClick={() => handleTest(d.id)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08]">
                  <TestTube className="w-3 h-3" /> {t('action.test')}
                </button>
                <button onClick={async () => { if (confirm(t('storage.confirm_delete'))) { await deleteStorageDestination(d.id); load(); }}} className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10">
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            </div>
          );
        })}
        {dests.length === 0 && (
          <div className="col-span-3 text-center py-12 text-vm-text-dim font-mono">
            <Database className="w-12 h-12 mx-auto mb-3 opacity-40" />
            <div className="tracking-[2px]">{t('storage.none')}</div>
          </div>
        )}
      </div>
    </div>
  );
}
