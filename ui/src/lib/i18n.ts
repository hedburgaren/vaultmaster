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
  // ── Navigation ──
  'nav.dashboard': { sv: 'Översikt', en: 'Dashboard' },
  'nav.servers': { sv: 'Servrar', en: 'Servers' },
  'nav.jobs': { sv: 'Backupjobb', en: 'Backup Jobs' },
  'nav.runs': { sv: 'Körningar', en: 'Runs' },
  'nav.artifacts': { sv: 'Återställning', en: 'Restore' },
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
  'action.create': { sv: 'Skapa', en: 'Create' },
  'action.remove': { sv: 'Ta bort', en: 'Remove' },
  'action.preview': { sv: 'Förhandsgranska', en: 'Preview' },
  'action.restore': { sv: 'Återställ', en: 'Restore' },
  'action.verify': { sv: 'Verifiera', en: 'Verify' },
  'action.revoke': { sv: 'Återkalla', en: 'Revoke' },
  'action.regenerate': { sv: 'Generera om', en: 'Regenerate' },
  'action.copy': { sv: 'Kopiera', en: 'Copy' },
  'action.generate': { sv: 'Generera', en: 'Generate' },

  // ── Common ──
  'common.total': { sv: 'TOTALT', en: 'TOTAL' },
  'common.loading': { sv: 'Laddar...', en: 'Loading...' },
  'common.system': { sv: 'System', en: 'System' },
  'common.online': { sv: 'ONLINE', en: 'ONLINE' },
  'common.offline': { sv: 'OFFLINE', en: 'OFFLINE' },
  'common.yes': { sv: 'Ja', en: 'Yes' },
  'common.no': { sv: 'Nej', en: 'No' },
  'common.all_types': { sv: 'Alla typer', en: 'All types' },
  'common.enabled': { sv: 'Aktiverad', en: 'Enabled' },

  // ── Login ──
  'login.subtitle': { sv: 'BACKUP KONTROLLCENTER', en: 'BACKUP CONTROL CENTER' },
  'login.username': { sv: 'Användarnamn', en: 'Username' },
  'login.password': { sv: 'Lösenord', en: 'Password' },
  'login.submit': { sv: 'Logga in', en: 'Log in' },
  'login.loading': { sv: 'Loggar in...', en: 'Logging in...' },
  'login.failed': { sv: 'Inloggning misslyckades', en: 'Login failed' },
  'login.logout': { sv: 'Logga ut', en: 'Log out' },

  // ── Setup ──
  'setup.title': { sv: 'FÖRSTA KONFIGURATION', en: 'INITIAL SETUP' },
  'setup.desc': { sv: 'Inget administratörskonto hittades. Skapa ditt första administratörskonto för att komma igång.', en: 'No admin account found. Create your first administrator account to get started.' },
  'setup.admin_username': { sv: 'Administratörsnamn', en: 'Admin Username' },
  'setup.password': { sv: 'Lösenord', en: 'Password' },
  'setup.confirm_password': { sv: 'Bekräfta lösenord', en: 'Confirm Password' },
  'setup.submit': { sv: 'Skapa administratörskonto', en: 'Create Admin Account' },
  'setup.creating': { sv: 'Skapar konto...', en: 'Creating account...' },
  'setup.checking': { sv: 'KONTROLLERAR SYSTEMSTATUS...', en: 'CHECKING SYSTEM STATUS...' },
  'setup.err_username': { sv: 'Användarnamn måste vara minst 2 tecken', en: 'Username must be at least 2 characters' },
  'setup.err_password': { sv: 'Lösenord måste vara minst 8 tecken', en: 'Password must be at least 8 characters' },
  'setup.err_mismatch': { sv: 'Lösenorden matchar inte', en: 'Passwords do not match' },
  'setup.err_failed': { sv: 'Konfiguration misslyckades', en: 'Setup failed' },
  'setup.min_chars': { sv: 'Minst 8 tecken', en: 'Min 8 characters' },

  // ── Topbar ──
  'topbar.notifications': { sv: 'Notifieringar', en: 'Notifications' },
  'topbar.failed_24h': { sv: 'misslyckade (24h)', en: 'failed (24h)' },
  'topbar.all_clear': { sv: 'Inga fel — allt ser bra ut', en: 'All clear — no recent errors' },
  'topbar.unknown_error': { sv: 'Okänt fel', en: 'Unknown error' },

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
  'dash.live': { sv: 'LIVE', en: 'LIVE' },
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
  'dash.loading': { sv: 'Laddar översikt...', en: 'Loading dashboard...' },

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
  'servers.ssh_user_tip': { sv: 'SSH-användarnamn. Använd en vanlig användare med sudo-rättigheter, eller en dedikerad backupanvändare.', en: 'SSH username. Use a regular user with sudo privileges, or a dedicated backup user.' },
  'servers.ssh_port': { sv: 'SSH-port', en: 'SSH Port' },
  'servers.ssh_port_tip': { sv: 'SSH-portnummer. Standard är 22.', en: 'SSH port number. Default is 22.' },
  'servers.auth_type': { sv: 'Autentiseringstyp', en: 'Auth Type' },
  'servers.auth_type_tip': { sv: 'Hur VaultMaster autentiserar mot servern. SSH-nyckel rekommenderas.', en: 'How VaultMaster authenticates. SSH Key is recommended.' },
  'servers.provider': { sv: 'Leverantör', en: 'Provider' },
  'servers.provider_tip': { sv: 'Molnleverantör för leverantörsspecifika funktioner som snapshots.', en: 'Cloud provider for provider-specific features like snapshots.' },
  'servers.ssh_key_path': { sv: 'SSH-nyckelsökväg', en: 'SSH Key Path' },
  'servers.ssh_key_path_tip': { sv: 'Sökväg till den privata SSH-nyckeln inuti containern. Hantera nycklar under Inställningar → SSH-nycklar.', en: 'Path to the private SSH key inside the container. Manage keys under Settings → SSH Keys.' },
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
  'servers.use_sudo': { sv: 'Använd sudo', en: 'Use sudo' },
  'servers.use_sudo_tip': { sv: 'Kör kommandon med sudo. Aktivera om SSH-användaren inte är root.', en: 'Run commands with sudo. Enable if the SSH user is not root.' },
  'servers.public_key_info': { sv: 'Kopiera denna publika nyckel till serverns ~/.ssh/authorized_keys', en: 'Copy this public key to the server\'s ~/.ssh/authorized_keys' },
  'servers.copy_pubkey': { sv: 'Kopiera publik nyckel', en: 'Copy public key' },
  'servers.generate_key': { sv: 'Generera SSH-nyckelpar', en: 'Generate SSH keypair' },
  'servers.generating': { sv: 'Genererar...', en: 'Generating...' },

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

  // ── Runs ──
  'runs.title': { sv: 'Körningar', en: 'Runs' },
  'runs.subtitle_prefix': { sv: '// BACKUPKÖRNINGAR ·', en: '// BACKUP RUNS ·' },
  'runs.status': { sv: 'Status', en: 'Status' },
  'runs.started': { sv: 'Startad', en: 'Started' },
  'runs.finished': { sv: 'Avslutad', en: 'Finished' },
  'runs.size': { sv: 'Storlek', en: 'Size' },
  'runs.trigger': { sv: 'Utlösare', en: 'Trigger' },
  'runs.cancel': { sv: 'Avbryt', en: 'Cancel' },
  'runs.confirm_cancel': { sv: 'Avbryt denna körning?', en: 'Cancel this run?' },
  'runs.none': { sv: 'Inga körningar ännu', en: 'No runs yet' },

  // ── Artifacts / Restore ──
  'artifacts.title': { sv: 'Återställning', en: 'Restore' },
  'artifacts.subtitle_prefix': { sv: '// BACKUPARTEFAKTER ·', en: '// BACKUP ARTIFACTS ·' },
  'artifacts.found': { sv: 'HITTADE', en: 'FOUND' },
  'artifacts.search_restore': { sv: 'SÖK & ÅTERSTÄLL', en: 'SEARCH & RESTORE' },
  'artifacts.search_placeholder': { sv: 'Sök efter filnamn, server, domän, tagg...', en: 'Search by filename, server, domain, tag...' },
  'artifacts.type': { sv: 'Typ', en: 'Type' },
  'artifacts.backup': { sv: 'Backup', en: 'Backup' },
  'artifacts.server': { sv: 'Server', en: 'Server' },
  'artifacts.date': { sv: 'Datum', en: 'Date' },
  'artifacts.size': { sv: 'Storlek', en: 'Size' },
  'artifacts.details': { sv: 'Artefaktdetaljer', en: 'Artifact Details' },
  'artifacts.filename': { sv: 'Filnamn', en: 'Filename' },
  'artifacts.project': { sv: 'Projekt', en: 'Project' },
  'artifacts.database': { sv: 'Databas', en: 'Database' },
  'artifacts.created': { sv: 'Skapad', en: 'Created' },
  'artifacts.encrypted': { sv: 'Krypterad (age/AES-256)', en: 'Encrypted (age/AES-256)' },
  'artifacts.expires': { sv: 'Förfaller', en: 'Expires' },
  'artifacts.confirm_restore': { sv: 'Starta återställning från denna backup? Befintlig data skrivs över.', en: 'Start restore from this backup? This will overwrite existing data.' },
  'artifacts.restore_queued': { sv: 'Återställning köad', en: 'Restore queued' },
  'artifacts.verify_queued': { sv: 'Verifiering köad', en: 'Verification queued' },
  'artifacts.none': { sv: 'Inga backuper hittade', en: 'No backups found' },
  'artifacts.none_desc': { sv: 'Kör ett backupjobb först, sedan visas artefakter här.', en: 'Run a backup job first, then artifacts will appear here.' },

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

  // ── Audit ──
  'audit.title': { sv: 'Revisionslogg', en: 'Audit Log' },
  'audit.subtitle_prefix': { sv: '// VEM GJORDE VAD · NÄR ·', en: '// WHO DID WHAT · WHEN ·' },
  'audit.entries': { sv: 'POSTER', en: 'ENTRIES' },
  'audit.filter_placeholder': { sv: 'Filtrera efter åtgärd...', en: 'Filter by action...' },
  'audit.time': { sv: 'Tid', en: 'Time' },
  'audit.user': { sv: 'Användare', en: 'User' },
  'audit.action': { sv: 'Åtgärd', en: 'Action' },
  'audit.resource': { sv: 'Resurs', en: 'Resource' },
  'audit.detail': { sv: 'Detalj', en: 'Detail' },
  'audit.ip': { sv: 'IP', en: 'IP' },
  'audit.none': { sv: 'Inga loggposter', en: 'No audit log entries' },
  'audit.none_desc': { sv: 'Åtgärder loggas här när användare interagerar med VaultMaster.', en: 'Actions will be logged here as users interact with VaultMaster.' },

  // ── Users ──
  'users.title': { sv: 'Användare', en: 'Users' },
  'users.subtitle_prefix': { sv: '// ANVÄNDARHANTERING ·', en: '// USER MANAGEMENT ·' },
  'users.accounts': { sv: 'KONTON', en: 'ACCOUNTS' },
  'users.new': { sv: 'Ny användare', en: 'New User' },
  'users.create': { sv: 'Skapa användare', en: 'Create User' },
  'users.username': { sv: 'Användarnamn', en: 'Username' },
  'users.username_tip': { sv: 'Unikt inloggningsnamn för denna användare.', en: 'Unique login name for this user.' },
  'users.password': { sv: 'Lösenord', en: 'Password' },
  'users.password_tip': { sv: 'Minst 8 tecken. Användaren kan ändra det senare.', en: 'Minimum 8 characters. The user can change it later.' },
  'users.role': { sv: 'Roll', en: 'Role' },
  'users.role_tip': { sv: 'Admin: full åtkomst. Operatör: hantera servrar, jobb och köra backuper. Visare: skrivskyddad åtkomst.', en: 'Admin: full access. Operator: manage servers, jobs, and run backups. Viewer: read-only access.' },
  'users.email': { sv: 'E-postadresser', en: 'Email Addresses' },
  'users.email_tip': { sv: 'Kommaseparerade e-postadresser för notifieringar.', en: 'Comma-separated email addresses for notifications.' },
  'users.col_user': { sv: 'Användare', en: 'User' },
  'users.col_role': { sv: 'Roll', en: 'Role' },
  'users.col_status': { sv: 'Status', en: 'Status' },
  'users.col_2fa': { sv: '2FA', en: '2FA' },
  'users.col_api_key': { sv: 'API-nyckel', en: 'API Key' },
  'users.col_created': { sv: 'Skapad', en: 'Created' },
  'users.active': { sv: 'AKTIV', en: 'ACTIVE' },
  'users.disabled': { sv: 'INAKTIVERAD', en: 'DISABLED' },
  'users.confirm_delete': { sv: 'Radera användare "{name}"? Detta kan inte ångras.', en: 'Delete user "{name}"? This cannot be undone.' },
  'users.admin_required': { sv: 'Administratörsåtkomst krävs', en: 'Admin Access Required' },
  'users.admin_required_desc': { sv: 'Endast administratörer kan hantera användare.', en: 'Only administrators can manage users.' },
  'users.none': { sv: 'Inga användare hittade', en: 'No users found' },
  'users.min_chars': { sv: 'Minst 8 tecken', en: 'Min. 8 characters' },
  'users.viewer': { sv: 'Visare — skrivskyddad', en: 'Viewer — read-only' },
  'users.operator': { sv: 'Operatör — hantera & kör', en: 'Operator — manage & run' },
  'users.admin': { sv: 'Admin — full åtkomst', en: 'Admin — full access' },

  // ── Settings ──
  'settings.title': { sv: 'Inställningar', en: 'Settings' },
  'settings.subtitle': { sv: '// PROFIL · API-NYCKLAR · BEVARANDEPOLICYER · SSH-NYCKLAR', en: '// PROFILE · API KEYS · RETENTION POLICIES · SSH KEYS' },
  'settings.tab_profile': { sv: 'Profil & API', en: 'Profile & API' },
  'settings.tab_retention': { sv: 'Bevarande', en: 'Retention' },
  'settings.tab_ssh': { sv: 'SSH-nycklar', en: 'SSH Keys' },
  'settings.tab_coming': { sv: 'Kommer snart', en: 'Coming Soon' },
  'settings.account': { sv: 'Konto', en: 'Account' },
  'settings.username': { sv: 'Användarnamn', en: 'Username' },
  'settings.role': { sv: 'Roll', en: 'Role' },
  'settings.role_admin': { sv: 'Administratör', en: 'Administrator' },
  'settings.role_operator': { sv: 'Operatör', en: 'Operator' },
  'settings.role_viewer': { sv: 'Visare', en: 'Viewer' },
  'settings.emails': { sv: 'E-postadresser', en: 'Email Addresses' },
  'settings.emails_desc': { sv: 'Används för backupnotifieringar. Du kan lägga till flera adresser.', en: 'Used for backup notifications. You can add multiple addresses.' },
  'settings.no_emails': { sv: 'Inga e-postadresser konfigurerade', en: 'No email addresses configured' },
  'settings.emails_updated': { sv: 'E-post uppdaterad', en: 'Emails updated' },
  'settings.email_removed': { sv: 'E-post borttagen', en: 'Email removed' },
  'settings.change_password': { sv: 'Byt lösenord', en: 'Change Password' },
  'settings.current_password': { sv: 'Nuvarande lösenord', en: 'Current Password' },
  'settings.new_password': { sv: 'Nytt lösenord', en: 'New Password' },
  'settings.confirm_password': { sv: 'Bekräfta lösenord', en: 'Confirm Password' },
  'settings.update_password': { sv: 'Uppdatera lösenord', en: 'Update Password' },
  'settings.pw_mismatch': { sv: 'Lösenorden matchar inte', en: 'Passwords do not match' },
  'settings.pw_too_short': { sv: 'Lösenord måste vara minst 8 tecken', en: 'Password must be at least 8 characters' },
  'settings.pw_changed': { sv: 'Lösenord ändrat', en: 'Password changed successfully' },
  'settings.api_key': { sv: 'API-nyckel', en: 'API Key' },
  'settings.api_key_desc': { sv: 'Använd en API-nyckel för att autentisera externa integrationer (n8n, skript, CI/CD). Skicka den som', en: 'Use an API key to authenticate external integrations (n8n, scripts, CI/CD). Pass it as' },
  'settings.api_key_header': { sv: 'header.', en: 'header.' },
  'settings.api_key_generated': { sv: 'Nyckel genererad — kopiera den nu, den visas inte igen.', en: 'Key generated — copy it now, it will not be shown again.' },
  'settings.api_key_revoked': { sv: 'API-nyckel återkallad', en: 'API key revoked' },
  'settings.api_key_confirm_revoke': { sv: 'Återkalla API-nyckel? Alla integrationer som använder den slutar fungera.', en: 'Revoke API key? Any integrations using it will stop working.' },
  'settings.api_key_copy_now': { sv: 'DIN API-NYCKEL (kopiera nu — visas bara en gång):', en: 'YOUR API KEY (copy now — shown only once):' },
  'settings.generate_api_key': { sv: 'Generera API-nyckel', en: 'Generate API Key' },
  'settings.new_policy': { sv: 'Ny policy', en: 'New Policy' },
  'settings.new_retention': { sv: 'Ny bevarandepolicy (GFS)', en: 'New Retention Policy (GFS)' },
  'settings.policy_name': { sv: 'Namn', en: 'Name' },
  'settings.policy_name_tip': { sv: 'Ett beskrivande namn, t.ex. \'PostgreSQL Kritisk\' eller \'Veckovis filer\'.', en: 'A descriptive name, e.g. \'PostgreSQL Critical\' or \'Weekly Files\'.' },
  'settings.hourly': { sv: 'Timvis', en: 'Hourly' },
  'settings.hourly_tip': { sv: 'Antal timvisa backuper att behålla. Sätt till 0 för att hoppa över.', en: 'Number of hourly backups to keep. Set to 0 to skip.' },
  'settings.daily': { sv: 'Daglig', en: 'Daily' },
  'settings.daily_tip': { sv: 'Antal dagliga backuper att behålla.', en: 'Number of daily backups to keep.' },
  'settings.weekly': { sv: 'Veckovis', en: 'Weekly' },
  'settings.weekly_tip': { sv: 'Antal veckovisa backuper att behålla.', en: 'Number of weekly backups to keep.' },
  'settings.monthly': { sv: 'Månadsvis', en: 'Monthly' },
  'settings.monthly_tip': { sv: 'Antal månadsvisa backuper att behålla.', en: 'Number of monthly backups to keep.' },
  'settings.yearly': { sv: 'Årsvis', en: 'Yearly' },
  'settings.yearly_tip': { sv: 'Antal årliga backuper att behålla.', en: 'Number of yearly backups to keep.' },
  'settings.max_days': { sv: 'Max dagar', en: 'Max Days' },
  'settings.max_days_tip': { sv: 'Maximal ålder i dagar. Backuper äldre än detta raderas alltid.', en: 'Maximum age in days. Backups older than this are always deleted.' },
  'settings.confirm_delete_policy': { sv: 'Radera denna policy?', en: 'Delete this policy?' },
  'settings.no_policies': { sv: 'Inga bevarandepolicyer konfigurerade', en: 'No retention policies configured' },
  'settings.total_artifacts': { sv: 'Totalt', en: 'Total' },
  'settings.would_keep': { sv: 'Behåll', en: 'Keep' },
  'settings.would_delete': { sv: 'Radera', en: 'Delete' },

  // ── SSH Keys (Settings tab) ──
  'ssh.title': { sv: 'SSH-nycklar', en: 'SSH Keys' },
  'ssh.desc': { sv: 'Hantera SSH-nycklar som VaultMaster använder för att ansluta till servrar. Den publika nyckeln måste läggas till i authorized_keys på målservern.', en: 'Manage SSH keys that VaultMaster uses to connect to servers. The public key must be added to authorized_keys on the target server.' },
  'ssh.current_keys': { sv: 'Tillgängliga nycklar', en: 'Available Keys' },
  'ssh.no_keys': { sv: 'Inga SSH-nycklar hittade. Generera ett nyckelpar nedan.', en: 'No SSH keys found. Generate a keypair below.' },
  'ssh.generate': { sv: 'Generera nytt nyckelpar', en: 'Generate New Keypair' },
  'ssh.generating': { sv: 'Genererar...', en: 'Generating...' },
  'ssh.public_key': { sv: 'Publik nyckel', en: 'Public Key' },
  'ssh.copy_instruction': { sv: 'Kopiera denna nyckel och lägg till den i ~/.ssh/authorized_keys på servern du vill ansluta till.', en: 'Copy this key and add it to ~/.ssh/authorized_keys on the server you want to connect to.' },
  'ssh.copied': { sv: 'Kopierad!', en: 'Copied!' },

  // ── Coming Soon ──
  'coming.title': { sv: 'Kommer snart', en: 'Coming Soon' },
  'coming.desc': { sv: 'Dessa funktioner är planerade för framtida versioner av VaultMaster.', en: 'These features are planned for future versions of VaultMaster.' },
  'coming.planned': { sv: 'PLANERAD', en: 'PLANNED' },
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
