'use client';

import { useEffect, useState } from 'react';
import { getStorageDestinations, createStorageDestination, deleteStorageDestination, testStorage } from '@/lib/api';
import { formatBytes } from '@/lib/utils';
import FormLabel from '@/components/FormLabel';
import CapacityInput from '@/components/CapacityInput';
import { Plus, Trash2, TestTube, Database, HardDrive, Cloud, Globe, Server, Eye, EyeOff } from 'lucide-react';

const INPUT = "w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent";

const BACKEND_LABELS: Record<string, string> = { local: 'Local Disk', s3: 'S3 / DO Spaces', sftp: 'SFTP Server', b2: 'Backblaze B2', gdrive: 'Google Drive', onedrive: 'OneDrive' };

export default function StoragePage() {
  const [dests, setDests] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
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

  const [testResults, setTestResults] = useState<Record<string, any>>({});

  const load = () => getStorageDestinations().then(setDests).catch(() => {});
  useEffect(() => { load(); }, []);

  const buildConfig = (): Record<string, any> => {
    switch (backend) {
      case 'local': return { path: localPath };
      case 's3': return { endpoint: s3Endpoint, bucket: s3Bucket, region: s3Region, access_key: s3AccessKey, secret_key: s3SecretKey };
      case 'sftp': return { host: sftpHost, port: parseInt(sftpPort), user: sftpUser, password: sftpPassword, path: sftpPath };
      case 'b2': return { key_id: b2KeyId, application_key: b2AppKey, bucket: b2Bucket };
      case 'gdrive': return { client_id: gdriveClientId, client_secret: gdriveClientSecret, folder_id: gdriveFolderId };
      case 'onedrive': return { client_id: onedriveClientId, client_secret: onedriveClientSecret, drive_id: onedriveDriveId, folder_path: onedriveFolderPath };
      default: return {};
    }
  };

  const handleCreate = async () => {
    await createStorageDestination({ name, backend, config: buildConfig(), capacity_bytes: capacityBytes });
    setShowForm(false);
    setName(''); setBackend('local'); setCapacityBytes(null);
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
          <h1 className="text-[28px] font-bold text-vm-text-bright tracking-wide uppercase">Storage</h1>
          <div className="font-mono text-xs text-vm-accent tracking-[2px] mt-1">// STORAGE DESTINATIONS · {dests.length} TOTAL</div>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="flex items-center gap-2 px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase hover:bg-[#33ddff] transition-all glow">
          <Plus className="w-4 h-4" /> Add New
        </button>
      </div>

      {showForm && (
        <div className="bg-vm-surface border border-vm-border-bright rounded p-6 mb-6">
          <h3 className="text-lg font-bold text-vm-text-bright mb-4 uppercase tracking-wider">New Storage Destination</h3>

          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <FormLabel label="Name" tooltip="A friendly name for this storage destination." />
              <input value={name} onChange={e => setName(e.target.value)} className={INPUT} placeholder="Primary backup disk" />
            </div>
            <div>
              <FormLabel label="Backend" tooltip="The type of storage to use. Each backend has its own configuration." />
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
                <FormLabel label="Path" tooltip="Absolute path on the VaultMaster host where backups will be stored." />
                <input value={localPath} onChange={e => setLocalPath(e.target.value)} className={INPUT} placeholder="/mnt/backups" />
              </div>
            )}

            {backend === 's3' && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <FormLabel label="Endpoint" tooltip="S3-compatible endpoint URL. Leave empty for AWS S3. For DigitalOcean Spaces: https://ams3.digitaloceanspaces.com" />
                  <input value={s3Endpoint} onChange={e => setS3Endpoint(e.target.value)} className={INPUT} placeholder="https://ams3.digitaloceanspaces.com" />
                </div>
                <div>
                  <FormLabel label="Bucket" tooltip="The S3 bucket name to store backups in." />
                  <input value={s3Bucket} onChange={e => setS3Bucket(e.target.value)} className={INPUT} placeholder="my-backups" />
                </div>
                <div>
                  <FormLabel label="Region" tooltip="AWS region or equivalent for your S3 provider." />
                  <input value={s3Region} onChange={e => setS3Region(e.target.value)} className={INPUT} placeholder="us-east-1" />
                </div>
                <div>
                  <FormLabel label="Access Key" tooltip="Your S3 access key ID." />
                  <input value={s3AccessKey} onChange={e => setS3AccessKey(e.target.value)} className={INPUT} placeholder="AKIAIOSFODNN7EXAMPLE" />
                </div>
                <div className="col-span-2">
                  <FormLabel label="Secret Key" tooltip="Your S3 secret access key. Will be encrypted before storage." />
                  <SecretInput value={s3SecretKey} onChange={setS3SecretKey} placeholder="Enter secret key" />
                </div>
              </div>
            )}

            {backend === 'sftp' && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <FormLabel label="Host" tooltip="Hostname or IP of the SFTP server." />
                  <input value={sftpHost} onChange={e => setSftpHost(e.target.value)} className={INPUT} placeholder="backup.example.com" />
                </div>
                <div>
                  <FormLabel label="Port" tooltip="SFTP port. Default is 22." />
                  <input type="number" value={sftpPort} onChange={e => setSftpPort(e.target.value)} className={INPUT} />
                </div>
                <div>
                  <FormLabel label="Username" tooltip="SFTP username for authentication." />
                  <input value={sftpUser} onChange={e => setSftpUser(e.target.value)} className={INPUT} placeholder="backup-user" />
                </div>
                <div>
                  <FormLabel label="Password" tooltip="SFTP password. Will be encrypted before storage." />
                  <SecretInput value={sftpPassword} onChange={setSftpPassword} placeholder="Enter password" />
                </div>
                <div className="col-span-2">
                  <FormLabel label="Remote Path" tooltip="Directory on the SFTP server where backups will be stored." />
                  <input value={sftpPath} onChange={e => setSftpPath(e.target.value)} className={INPUT} placeholder="/backups" />
                </div>
              </div>
            )}

            {backend === 'b2' && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <FormLabel label="Key ID" tooltip="Backblaze B2 application key ID." />
                  <input value={b2KeyId} onChange={e => setB2KeyId(e.target.value)} className={INPUT} placeholder="0012345678abcdef0000000001" />
                </div>
                <div>
                  <FormLabel label="Application Key" tooltip="Backblaze B2 application key. Will be encrypted before storage." />
                  <SecretInput value={b2AppKey} onChange={setB2AppKey} placeholder="Enter application key" />
                </div>
                <div className="col-span-2">
                  <FormLabel label="Bucket" tooltip="B2 bucket name to store backups in." />
                  <input value={b2Bucket} onChange={e => setB2Bucket(e.target.value)} className={INPUT} placeholder="my-backups" />
                </div>
              </div>
            )}

            {backend === 'gdrive' && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <FormLabel label="Client ID" tooltip="Google OAuth2 Client ID from Google Cloud Console. Required for rclone authentication." />
                  <input value={gdriveClientId} onChange={e => setGdriveClientId(e.target.value)} className={INPUT} placeholder="123456789.apps.googleusercontent.com" />
                </div>
                <div>
                  <FormLabel label="Client Secret" tooltip="Google OAuth2 Client Secret. Will be encrypted before storage." />
                  <SecretInput value={gdriveClientSecret} onChange={setGdriveClientSecret} placeholder="Enter client secret" />
                </div>
                <div className="col-span-2">
                  <FormLabel label="Folder ID" tooltip="Google Drive folder ID where backups will be stored. Find it in the folder URL after /folders/." />
                  <input value={gdriveFolderId} onChange={e => setGdriveFolderId(e.target.value)} className={INPUT} placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms" />
                </div>
              </div>
            )}

            {backend === 'onedrive' && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <FormLabel label="Client ID" tooltip="Microsoft Azure App Registration Client ID (Application ID)." />
                  <input value={onedriveClientId} onChange={e => setOnedriveClientId(e.target.value)} className={INPUT} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
                </div>
                <div>
                  <FormLabel label="Client Secret" tooltip="Microsoft Azure App Registration Client Secret. Will be encrypted before storage." />
                  <SecretInput value={onedriveClientSecret} onChange={setOnedriveClientSecret} placeholder="Enter client secret" />
                </div>
                <div>
                  <FormLabel label="Drive ID" tooltip="OneDrive or SharePoint drive ID. Leave empty for the user's default drive." />
                  <input value={onedriveDriveId} onChange={e => setOnedriveDriveId(e.target.value)} className={INPUT} placeholder="Optional — leave empty for default" />
                </div>
                <div>
                  <FormLabel label="Folder Path" tooltip="Path within the drive where backups will be stored." />
                  <input value={onedriveFolderPath} onChange={e => setOnedriveFolderPath(e.target.value)} className={INPUT} placeholder="/Backups" />
                </div>
              </div>
            )}
          </div>

          <div className="mb-4">
            <FormLabel label="Capacity" tooltip="Total storage capacity. Used for usage monitoring and alerts." />
            <CapacityInput value={capacityBytes} onChange={setCapacityBytes} />
          </div>

          <button onClick={handleCreate} className="px-5 py-2.5 bg-vm-accent text-vm-bg rounded font-bold text-sm tracking-wider uppercase">Save</button>
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
                    <span>Used</span>
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
                <button onClick={() => handleTest(d.id)} className="flex items-center gap-1 px-3 py-1.5 border border-vm-accent text-vm-accent rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-accent/[0.08]">
                  <TestTube className="w-3 h-3" /> Test
                </button>
                <button onClick={async () => { if (confirm('Delete this storage destination?')) { await deleteStorageDestination(d.id); load(); }}} className="flex items-center gap-1 px-3 py-1.5 border border-vm-danger text-vm-danger rounded text-xs font-bold tracking-wider uppercase hover:bg-vm-danger/10">
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            </div>
          );
        })}
        {dests.length === 0 && (
          <div className="col-span-3 text-center py-12 text-vm-text-dim font-mono">
            <Database className="w-12 h-12 mx-auto mb-3 opacity-40" />
            <div className="tracking-[2px]">No storage destinations configured</div>
          </div>
        )}
      </div>
    </div>
  );
}
