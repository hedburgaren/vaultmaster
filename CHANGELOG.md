# Changelog

All notable changes to VaultMaster are documented here.

## [2.1.0] — 2026-02-21

### Added
- **Per-destination retention overrides** — Set different retention policies per storage destination on the same job (e.g. keep 365 days locally, 7 days on Google Drive)
- **Docker bind mount visibility** — Container list is expandable, showing bind mount paths with source → destination mapping
- **"Use as file backup" button** — One-click conversion from Docker bind mounts to a file backup job with paths pre-filled
- **Docker volume prune** — Prune unused/orphan volumes directly from the UI with confirmation dialog
- **Orphan volume detection** — Unused Docker volumes are visually flagged and sorted last
- **PostgreSQL peer auth** — Supports `sudo -u db_user psql` for local PostgreSQL without passwords
- **DB setup wizard** — Server form shows requirements (sudoers line, peer vs password auth) when configuring database access
- **Server health monitoring** — Automatic SSH health checks every 5 minutes (was broken, now fixed)
- **Scheduled backup execution** — Cron-based job scheduling now works reliably (was broken, now fixed)

### Fixed
- **Critical: Celery worker crash** — asyncpg `InterfaceError: another operation is in progress` prevented ALL scheduled tasks from running. Root cause: shared async engine across different event loops in Celery workers. Fix: dedicated engine per task invocation.
- **PostgreSQL database listing** — Added `-d postgres` to psql commands; previously defaulted to a database named after the user (which often doesn't exist)
- **Docker volume-container correlation** — Uses `docker inspect` for accurate full volume names instead of truncated `docker ps` output
- **Hardcoded username removed** — Sudoers example in server form now uses dynamic `form.ssh_user` instead of hardcoded value

### Improved
- **Container list** — Shows bind mount count badge, expandable details with mount paths
- **Volume list** — Sorted (used first, orphans last), orphan badge, prune button
- **DB tooltips** — Explain peer auth, when to leave password empty, remote server requirements
- **i18n** — Full Swedish/English coverage for all new strings

## [2.0.0] — 2026-02-18

### Added
- **Complete UI rewrite** — Dark sci-fi cyberpunk control panel
- **RBAC** — Admin, Operator, Viewer roles with full access control
- **Multi-user management** — Create/edit/delete users with role assignment
- **Audit log** — Full action logging with user, IP, timestamp, resource
- **Bilingual UI** — Complete Swedish/English i18n with locale switcher
- **SSH key management** — Generate keypairs, copy public keys from Settings
- **Sudo support** — Run remote commands with sudo for non-root SSH users
- **Visual cron builder** — Presets + custom expressions + live next-run preview
- **OAuth storage flow** — Google Drive, OneDrive with rclone inline backends
- **Multi-backend storage** — Local, S3, SFTP, B2, Google Drive, OneDrive
- **Notification channels** — Slack, ntfy, Telegram, email, webhooks with per-channel config
- **Webhook events** — HMAC-signed payloads for all backup lifecycle events
- **Plugin system** — Extend with custom backup types, storage backends, notification channels
- **Prometheus metrics** — `/api/metrics` endpoint for Grafana dashboards
- **API keys** — SHA-256 hashed, `vm_` prefixed, shown once
- **Tooltips everywhere** — Every form field has contextual help
- **File browser** — Browse remote server files when configuring backup paths
- **Docker volume picker** — List and select Docker volumes with container correlation
- **Database picker** — List and select databases from remote PostgreSQL/MySQL/MariaDB
- **GFS retention** — Grandfather-Father-Son rotation with dry-run preview
- **Restore wizard** — Search, filter, verify checksum, one-click restore
- **Encryption** — age-based AES-256 encryption for backup artifacts

## [1.1.0] — 2026-02-17

### Added
- Profile management and API keys
- English UI translation
- Security hardening
- n8n integration documentation

## [1.0.0] — 2026-02-16

### Added
- Initial release — VaultMaster Backup Control Center
- PostgreSQL, Docker volumes, files, custom script backup types
- Cron scheduling with Celery Beat
- Basic retention policies
- SSH-based remote server management
- Local and S3 storage backends
