'use client';

import { useState, useEffect, useCallback } from 'react';

export type Locale = 'sv' | 'en';

const STORAGE_KEY = 'vm_locale';

export function getLocale(): Locale {
  if (typeof window === 'undefined') return 'sv';
  return (localStorage.getItem(STORAGE_KEY) as Locale) || 'sv';
}

export function setLocale(locale: Locale) {
  localStorage.setItem(STORAGE_KEY, locale);
  window.dispatchEvent(new Event('vm-locale-change'));
}

export function useLocale(): [Locale, (l: Locale) => void] {
  const [locale, setLoc] = useState<Locale>('sv');

  useEffect(() => {
    setLoc(getLocale());
    const handler = () => setLoc(getLocale());
    window.addEventListener('vm-locale-change', handler);
    return () => window.removeEventListener('vm-locale-change', handler);
  }, []);

  const change = useCallback((l: Locale) => {
    setLocale(l);
    setLoc(l);
  }, []);

  return [locale, change];
}

// Translation dictionary type
type Dict = Record<string, Record<Locale, string>>;

const translations: Dict = {
  // ── Global / Nav ──
  'nav.dashboard': { sv: 'Översikt', en: 'Dashboard' },
  'nav.servers': { sv: 'Servrar', en: 'Servers' },
  'nav.jobs': { sv: 'Backupjobb', en: 'Backup Jobs' },
  'nav.runs': { sv: 'Körningar', en: 'Runs' },
  'nav.artifacts': { sv: 'Artefakter', en: 'Artifacts' },
  'nav.storage': { sv: 'Lagring', en: 'Storage' },
  'nav.notifications': { sv: 'Notifieringar', en: 'Notifications' },
  'nav.settings': { sv: 'Inställningar', en: 'Settings' },
  'nav.audit': { sv: 'Revisionslogg', en: 'Audit Log' },
  'nav.users': { sv: 'Användare', en: 'Users' },

  // ── Common actions ──
  'action.save': { sv: 'Spara', en: 'Save' },
  'action.cancel': { sv: 'Avbryt', en: 'Cancel' },
  'action.delete': { sv: 'Radera', en: 'Delete' },
  'action.edit': { sv: 'Redigera', en: 'Edit' },
  'action.test': { sv: 'Testa', en: 'Test' },
  'action.add': { sv: 'Lägg till', en: 'Add' },
  'action.close': { sv: 'Stäng', en: 'Close' },
  'action.run': { sv: 'Kör', en: 'Run' },
  'action.testing': { sv: 'Testar...', en: 'Testing...' },
  'action.update': { sv: 'Uppdatera', en: 'Update' },

  // ── Dashboard ──
  'dash.title': { sv: 'Översikt', en: 'Dashboard' },
  'dash.subtitle': { sv: '// BACKUP KONTROLLCENTER · v2.0', en: '// BACKUP CONTROL CENTER · v2.0' },
  'dash.servers_online': { sv: 'Servrar online', en: 'Servers online' },
  'dash.successful_24h': { sv: 'Lyckade (24h)', en: 'Successful (24h)' },
  'dash.active_jobs': { sv: 'Aktiva jobb', en: 'Active jobs' },
  'dash.failed_24h': { sv: 'Misslyckade (24h)', en: 'Failed (24h)' },
  'dash.success_rate': { sv: 'framgångsgrad', en: 'success rate' },
  'dash.check_logs': { sv: 'Kontrollera loggar', en: 'Check logs' },
  'dash.all_clear': { sv: 'Inga fel', en: 'All clear' },
  'dash.last_backup': { sv: 'Senaste lyckade backup', en: 'Last Successful Backup' },
  'dash.no_backups_yet': { sv: 'Inga backuper ännu', en: 'No backups yet' },
  'dash.less_than_1h': { sv: 'Mindre än 1h sedan', en: 'Less than 1h ago' },
  'dash.hours_ago': { sv: 'h sedan', en: 'h ago' },
  'dash.backup_vault': { sv: 'Backupvalv', en: 'Backup Vault' },
  'dash.total': { sv: 'totalt', en: 'total' },
  'dash.system_health': { sv: 'Systemhälsa', en: 'System Health' },
  'dash.healthy': { sv: 'FRISKT', en: 'HEALTHY' },
  'dash.all_operational': { sv: 'Alla system fungerar', en: 'All systems operational' },
  'dash.issue': { sv: 'PROBLEM', en: 'ISSUE' },
  'dash.issues': { sv: 'PROBLEM', en: 'ISSUES' },
  'dash.failed_backups': { sv: 'misslyckade backuper', en: 'failed backups' },
  'dash.storage_warnings': { sv: 'lagringsvarningar', en: 'storage warnings' },
  'dash.servers_offline': { sv: 'servrar offline', en: 'servers offline' },
  'dash.no_backup_48h': { sv: 'Ingen backup på 48h+', en: 'No backup in 48h+' },
  'dash.active_run': { sv: 'Aktiv körning', en: 'Active run' },
  'dash.started': { sv: 'Startad', en: 'Started' },
  'dash.storage_warnings_title': { sv: 'Lagringsvarningar', en: 'Storage Warnings' },
  'dash.server_health': { sv: 'Serverhälsa', en: 'Server Health' },
  'dash.online': { sv: 'Online', en: 'Online' },
  'dash.offline': { sv: 'Offline', en: 'Offline' },
  'dash.last_seen': { sv: 'senast sedd', en: 'last seen' },
  'dash.storage_destinations': { sv: 'Lagringsdestinationer', en: 'Storage Destinations' },
  'dash.used': { sv: 'Använt', en: 'Used' },
  'dash.upcoming_runs': { sv: 'Kommande körningar', en: 'Upcoming Runs' },
  'dash.job': { sv: 'Jobb', en: 'Job' },
  'dash.next_run': { sv: 'Nästa körning', en: 'Next Run' },
  'dash.countdown': { sv: 'Nedräkning', en: 'Countdown' },
  'dash.recent_errors': { sv: 'Senaste fel', en: 'Recent Errors' },
  'dash.unknown_error': { sv: 'Okänt fel', en: 'Unknown error' },

  // ── Servers ──
  'servers.title': { sv: 'Servrar', en: 'Servers' },
  'servers.subtitle_prefix': { sv: '// ANSLUTNA SERVRAR ·', en: '// CONNECTED SERVERS ·' },
  'servers.add': { sv: 'Lägg till server', en: 'Add Server' },
  'servers.new': { sv: 'Ny server', en: 'New Server' },
  'servers.edit': { sv: 'Redigera server', en: 'Edit Server' },
  'servers.name': { sv: 'Namn', en: 'Name' },
  'servers.name_tip': { sv: 'Ett vänligt namn för att identifiera servern i VaultMaster.', en: 'A friendly name to identify this server in VaultMaster.' },
  'servers.host': { sv: 'Värd', en: 'Host' },
  'servers.host_tip': { sv: 'IP-adress eller värdnamn. Måste vara nåbar från VaultMaster.', en: 'IP address or hostname. Must be reachable from VaultMaster.' },
  'servers.ssh_user': { sv: 'SSH-användare', en: 'SSH User' },
  'servers.ssh_user_tip': { sv: 'SSH-användarnamn. Vanligtvis \'root\' eller en dedikerad backupanvändare.', en: 'SSH username. Typically \'root\' or a dedicated backup user.' },
  'servers.ssh_port': { sv: 'SSH-port', en: 'SSH Port' },
  'servers.ssh_port_tip': { sv: 'SSH-portnummer. Standard är 22.', en: 'SSH port number. Default is 22.' },
  'servers.auth_type': { sv: 'Autentiseringstyp', en: 'Auth Type' },
  'servers.auth_type_tip': { sv: 'Hur VaultMaster autentiserar mot servern. SSH-nyckel rekommenderas.', en: 'How VaultMaster authenticates. SSH Key is recommended.' },
  'servers.provider': { sv: 'Leverantör', en: 'Provider' },
  'servers.provider_tip': { sv: 'Molnleverantör för leverantörsspecifika funktioner som snapshots.', en: 'Cloud provider for provider-specific features like snapshots.' },
  'servers.ssh_key_path': { sv: 'SSH-nyckelsökväg', en: 'SSH Key Path' },
  'servers.ssh_key_path_tip': { sv: 'Absolut sökväg till den privata SSH-nyckeln. Exempel: /root/.ssh/id_ed25519', en: 'Absolute path to the private SSH key. Example: /root/.ssh/id_ed25519' },
  'servers.ssh_password': { sv: 'SSH-lösenord', en: 'SSH Password' },
  'servers.ssh_password_tip': { sv: 'Lösenord för SSH-autentisering. Krypteras innan lagring.', en: 'Password for SSH authentication. Will be encrypted before storage.' },
  'servers.api_token': { sv: 'API-token', en: 'API Token' },
  'servers.api_token_tip': { sv: 'Leverantörens API-token för molnoperationer. Krypteras innan lagring.', en: 'Provider API token for cloud operations. Will be encrypted before storage.' },
  'servers.tags': { sv: 'Taggar', en: 'Tags' },
  'servers.tags_tip': { sv: 'Organisera servrar med taggar. Tryck Enter eller komma för att lägga till.', en: 'Organize servers with tags. Press Enter or comma to add.' },
  'servers.test_connection': { sv: 'Testa anslutning', en: 'Test Connection' },
  'servers.last_seen': { sv: 'Senast sedd', en: 'Last seen' },
  'servers.confirm_delete': { sv: 'Radera denna server?', en: 'Delete this server?' },
  'servers.none': { sv: 'Inga servrar konfigurerade', en: 'No servers configured' },

  // ── Jobs ──
  'jobs.title': { sv: 'Backupjobb', en: 'Backup Jobs' },
  'jobs.subtitle_prefix': { sv: '// SCHEMALAGDA JOBB ·', en: '// SCHEDULED JOBS ·' },
  'jobs.new': { sv: 'Nytt jobb', en: 'New Job' },
  'jobs.edit': { sv: 'Redigera jobb', en: 'Edit Job' },
  'jobs.name': { sv: 'Namn', en: 'Name' },
  'jobs.name_tip': { sv: 'Ett beskrivande namn, t.ex. \'Nattlig PostgreSQL\' eller \'Veckovis filer\'.', en: 'A descriptive name, e.g. \'Nightly PostgreSQL\' or \'Weekly Files\'.' },
  'jobs.backup_type': { sv: 'Backuptyp', en: 'Backup Type' },
  'jobs.backup_type_tip': { sv: 'Vilken typ av data som ska säkerhetskopieras.', en: 'What kind of data to back up.' },
  'jobs.server': { sv: 'Server', en: 'Server' },
  'jobs.server_tip': { sv: 'Vilken server backupen ska köras på.', en: 'Which server to run this backup on.' },
  'jobs.select_server': { sv: 'Välj server...', en: 'Select server...' },
  'jobs.project': { sv: 'Projekt / Domän', en: 'Project / Domain' },
  'jobs.project_tip': { sv: 'Gruppera backuper efter projekt eller domännamn.', en: 'Group backups by project or domain name.' },
  'jobs.schedule': { sv: 'Schema', en: 'Schedule' },
  'jobs.schedule_tip': { sv: 'När backupen ska köras automatiskt.', en: 'When this backup should run automatically.' },
  'jobs.tags': { sv: 'Taggar', en: 'Tags' },
  'jobs.tags_tip': { sv: 'Kategorisera jobbet med taggar. Tryck Enter eller komma för att lägga till.', en: 'Categorize this job with tags. Press Enter or comma to add.' },
  'jobs.encrypt': { sv: 'Kryptera backup', en: 'Encrypt backup' },
  'jobs.encrypt_on': { sv: 'Kryptering PÅ', en: 'Encryption ON' },
  'jobs.encrypt_desc': { sv: 'Krypterar backupfiler med age (AES-256). Kräver AGE_PUBLIC_KEY i .env.', en: 'Encrypts backup files using age (AES-256). Requires AGE_PUBLIC_KEY in .env.' },
  'jobs.type': { sv: 'Typ', en: 'Type' },
  'jobs.project_col': { sv: 'Projekt', en: 'Project' },
  'jobs.status': { sv: 'Status', en: 'Status' },
  'jobs.active': { sv: 'AKTIV', en: 'ACTIVE' },
  'jobs.inactive': { sv: 'INAKTIV', en: 'INACTIVE' },
  'jobs.confirm_delete': { sv: 'Radera detta jobb?', en: 'Delete this job?' },
  'jobs.none': { sv: 'Inga backupjobb konfigurerade', en: 'No backup jobs configured' },
  'jobs.backup_queued': { sv: 'Backup köad!', en: 'Backup queued!' },

  // ── Storage ──
  'storage.title': { sv: 'Lagring', en: 'Storage' },
  'storage.subtitle_prefix': { sv: '// LAGRINGSDESTINATIONER ·', en: '// STORAGE DESTINATIONS ·' },
  'storage.add': { sv: 'Lägg till', en: 'Add New' },
  'storage.new': { sv: 'Ny lagringsdestination', en: 'New Storage Destination' },
  'storage.edit': { sv: 'Redigera lagring', en: 'Edit Storage' },
  'storage.name': { sv: 'Namn', en: 'Name' },
  'storage.name_tip': { sv: 'Ett vänligt namn för lagringsdestinationen.', en: 'A friendly name for this storage destination.' },
  'storage.backend': { sv: 'Backend', en: 'Backend' },
  'storage.backend_tip': { sv: 'Typ av lagring. Varje backend har sin egen konfiguration.', en: 'The type of storage. Each backend has its own configuration.' },
  'storage.capacity': { sv: 'Kapacitet', en: 'Capacity' },
  'storage.capacity_tip': { sv: 'Total lagringskapacitet. Används för övervakning och varningar.', en: 'Total storage capacity. Used for monitoring and alerts.' },
  'storage.confirm_delete': { sv: 'Radera denna lagringsdestination?', en: 'Delete this storage destination?' },
  'storage.none': { sv: 'Inga lagringsdestinationer konfigurerade', en: 'No storage destinations configured' },

  // ── Notifications ──
  'notif.title': { sv: 'Notifieringar', en: 'Notifications' },
  'notif.subtitle_prefix': { sv: '// NOTIFIERINGSKANALER ·', en: '// NOTIFICATION CHANNELS ·' },
  'notif.new': { sv: 'Ny kanal', en: 'New Channel' },
  'notif.edit': { sv: 'Redigera kanal', en: 'Edit Channel' },
  'notif.name': { sv: 'Namn', en: 'Name' },
  'notif.name_tip': { sv: 'Ett vänligt namn för notifieringskanalen.', en: 'A friendly name for this notification channel.' },
  'notif.type': { sv: 'Kanaltyp', en: 'Channel Type' },
  'notif.type_tip': { sv: 'Vart notifieringar ska skickas.', en: 'Where notifications will be sent.' },
  'notif.triggers': { sv: 'Utlösare', en: 'Triggers' },
  'notif.triggers_tip': { sv: 'Välj vilka händelser som ska skicka notifieringar.', en: 'Select which events should send notifications.' },
  'notif.confirm_delete': { sv: 'Radera denna kanal?', en: 'Delete this channel?' },
  'notif.none': { sv: 'Inga notifieringskanaler konfigurerade', en: 'No notification channels configured' },

  // ── Trigger labels ──
  'trigger.run.success': { sv: 'Backup lyckades', en: 'Backup success' },
  'trigger.run.failed': { sv: 'Backup misslyckades', en: 'Backup failed' },
  'trigger.run.started': { sv: 'Backup startad', en: 'Backup started' },
  'trigger.restore.started': { sv: 'Återställning startad', en: 'Restore started' },
  'trigger.restore.completed': { sv: 'Återställning klar', en: 'Restore completed' },
  'trigger.restore.failed': { sv: 'Återställning misslyckades', en: 'Restore failed' },
  'trigger.server.offline': { sv: 'Server offline', en: 'Server offline' },
  'trigger.storage.warning': { sv: 'Lagringsvarning (>70%)', en: 'Storage warning (>70%)' },
  'trigger.storage.critical': { sv: 'Lagring kritisk (>90%)', en: 'Storage critical (>90%)' },

  // ── Common ──
  'common.total': { sv: 'TOTALT', en: 'TOTAL' },
  'common.loading': { sv: 'Laddar...', en: 'Loading...' },
  'common.system_online': { sv: 'System: Online', en: 'System: Online' },
};

export function t(key: string, locale?: Locale): string {
  const l = locale || getLocale();
  const entry = translations[key];
  if (!entry) return key;
  return entry[l] || entry['en'] || key;
}

export function useT(): (key: string) => string {
  const [locale] = useLocale();
  return useCallback((key: string) => t(key, locale), [locale]);
}
