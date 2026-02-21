<p align="center">
  <img src="https://img.shields.io/badge/version-2.1-00ccff?style=flat-square" alt="Version 2.1" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License" />
  <img src="https://img.shields.io/badge/python-3.12-blue?style=flat-square" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/next.js-14-black?style=flat-square" alt="Next.js 14" />
</p>

# 🔐 VaultMaster

**Self-hosted backup orchestration with a dark sci-fi control panel.**

Manage PostgreSQL dumps, Docker volume snapshots, file backups, DigitalOcean snapshots, and custom scripts — across multiple servers via SSH. Scheduled with cron, protected by GFS retention policies (with per-destination overrides), encrypted with age, and monitored through multi-channel notifications.

---

## Quick Start

```bash
# One-liner install
curl -fsSL https://raw.githubusercontent.com/hedburgaren/vaultmaster/main/install.sh | bash

# Or manually:
git clone https://github.com/hedburgaren/vaultmaster.git && cd vaultmaster
cp .env.example .env          # Edit: set POSTGRES_PASSWORD, DATABASE_URL, SECRET_KEY
docker compose up -d           # Start API, worker, scheduler, PostgreSQL, Redis
cd ui && npm install && npx next build && npx next start --port 3100
# Open http://localhost:3100 → Setup wizard creates your admin account
```

## Architecture

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  Next.js UI │───▶│  FastAPI API  │───▶│ PostgreSQL  │
│  (port 3100)│    │  (port 8100)  │    │  (port 5432)│
└─────────────┘    └──────┬───────┘    └─────────────┘
                          │
                   ┌──────┴───────┐
                   │ Celery Worker │───▶ Redis (queue)
                   │ Celery Beat   │
                   └──────────────┘
```

| Component | Technology |
|---|---|
| **API** | FastAPI (Python 3.12), async, OpenAPI docs |
| **Worker** | Celery with 4 concurrent workers |
| **Scheduler** | Celery Beat (cron-based) |
| **Database** | PostgreSQL 16 |
| **Queue** | Redis 7 |
| **Frontend** | Next.js 14, React, TailwindCSS |
| **SSH** | AsyncSSH for remote server management |
| **Storage** | rclone — local, S3, SFTP, B2, Google Drive |
| **Encryption** | age (AES-256) |
| **Monitoring** | Prometheus `/metrics` endpoint |

## Features

### Backup & Restore
- **5 backup types** — PostgreSQL, Docker volumes, files, DO snapshots, custom scripts
- **Cron scheduling** — visual builder with presets + custom expressions + live preview
- **GFS retention** — Grandfather-Father-Son rotation with dry-run preview
- **Per-destination retention** — Different retention policies per storage destination (e.g. 365 days local, 7 days cloud)
- **Restore wizard** — search, filter, verify checksum, inspect details, one-click restore
- **Encryption** — age-based AES-256 encryption for backup artifacts

### Infrastructure
- **Multi-server management** — SSH key/password/API token auth, automatic health monitoring (5-min interval)
- **Multi-backend storage** — Local disk, S3/DO Spaces, SFTP, Backblaze B2, Google Drive, OneDrive
- **Docker intelligence** — Volume picker with container correlation, bind mount visibility, orphan detection, volume pruning
- **Database discovery** — Auto-list PostgreSQL/MySQL/MariaDB databases via SSH (peer auth + password auth)
- **Notifications** — Slack, ntfy, Telegram, email, webhooks
- **Webhook events** — HMAC-signed payloads for backup.started, backup.completed, backup.failed, etc.

### Security & Access Control
- **RBAC** — Admin, Operator, Viewer roles
- **Multi-user** — Create and manage user accounts with role-based permissions
- **2FA/TOTP** — Two-factor authentication support (TOTP-based)
- **API keys** — SHA-256 hashed, `vm_` prefixed, shown once
- **Rate limiting** — Login: 5/min, API: 120/min per IP
- **Security headers** — HSTS, X-Frame-Options, CSP, Referrer-Policy
- **Audit log** — Who did what, when, from which IP
- **No default credentials** — First-run setup wizard

### Developer Experience
- **Plugin system** — Extend with custom backup types, storage backends, notification channels
- **Prometheus metrics** — `/api/metrics` for Grafana dashboards
- **n8n integration** — Trigger, monitor, and manage backups via n8n workflows
- **REST API** — Full OpenAPI spec at `/api/docs` (Swagger) and `/api/redoc`
- **Webhook events** — Real-time event dispatch with HMAC signing

### UX
- **Dark sci-fi UI** — Cyberpunk-inspired control panel with glow effects
- **Bilingual** — Full Swedish/English UI with locale switcher
- **Tooltips** — Every form field has an info tooltip explaining its purpose
- **Smart inputs** — Cron builder with presets, tag autocomplete, human-readable capacity (TB/GB)
- **Setup wizards** — DB requirements guide, Docker bind mount → file backup conversion
- **Notification bell** — Color-coded alerts in the topbar (red = critical, orange = warning)
- **Detail panels** — Click any artifact to see full metadata, checksum, and restore/verify actions

## API Endpoints

| Route | Description |
|---|---|
| `POST /api/v1/auth/login` | JWT authentication (rate limited) |
| `GET /api/v1/auth/me` | Current user profile |
| `PUT /api/v1/auth/profile` | Update email addresses |
| `POST /api/v1/auth/change-password` | Change password |
| `POST /api/v1/auth/api-key` | Generate API key |
| `DELETE /api/v1/auth/api-key` | Revoke API key |
| `/api/v1/servers` | CRUD + SSH test + file browser |
| `/api/v1/jobs` | CRUD + trigger + schedule preview |
| `/api/v1/runs` | List + live log (SSE) + cancel |
| `/api/v1/artifacts` | Search/filter + restore + verify |
| `/api/v1/storage` | CRUD + test + usage |
| `/api/v1/retention` | CRUD + rotation preview |
| `/api/v1/notifications/channels` | CRUD + test |
| `/api/v1/webhooks` | CRUD + test + HMAC signing |
| `/api/v1/audit` | Audit log (filterable) |
| `/api/v1/users` | User management (admin) |
| `GET /api/v1/dashboard` | Aggregated KPIs |
| `GET /api/metrics` | Prometheus metrics |
| `GET /api/health` | Health check |

Full interactive docs: `/api/docs` (Swagger) · `/api/redoc` (ReDoc)

## API Keys & Integrations

```bash
# Generate a key in Settings → Profile & API, then:
curl -H "X-API-Key: vm_your_key_here" https://your-vaultmaster/api/v1/jobs

# Trigger a backup from CI/CD:
curl -X POST -H "X-API-Key: vm_..." https://your-vaultmaster/api/v1/jobs/{id}/trigger
```

See **[n8n Integration Guide](docs/n8n-integration.md)** for workflow examples.

## Plugin System

VaultMaster supports plugins for custom backup types, storage backends, and notification channels.

```python
# plugins/wordpress/__init__.py
from api.plugins import BackupPlugin, register_backup_plugin

class WordPressBackup(BackupPlugin):
    name = "WordPress"
    backup_type = "wordpress"
    icon = "🌐"

    async def run_backup(self, server, config, work_dir):
        # Your backup logic here
        return True, "Backup complete", "/path/to/artifact.tar.gz"

def register():
    register_backup_plugin(WordPressBackup())
```

Set `VAULTMASTER_PLUGINS_DIR` to your plugins directory. See [Plugin Development Guide](docs/plugins.md) for details.

## Prometheus & Grafana

```yaml
# prometheus.yml
scrape_configs:
  - job_name: vaultmaster
    metrics_path: /api/metrics
    static_configs:
      - targets: ['your-vaultmaster:8100']
```

Available metrics: `vaultmaster_servers_total`, `vaultmaster_runs_24h_success`, `vaultmaster_storage_used_bytes`, `vaultmaster_success_rate_24h`, and more.

## Security

| Feature | Implementation |
|---|---|
| Passwords | bcrypt (cost 12) |
| JWT tokens | HS256, 24h expiry |
| API keys | SHA-256 hashed, `vm_` prefix |
| Rate limiting | slowapi (5/min login, 120/min API) |
| Headers | HSTS, X-Frame-Options DENY, nosniff, Referrer-Policy |
| CORS | Configurable via `ALLOWED_ORIGINS` |
| Audit | Full action log with user, IP, timestamp |
| RBAC | Admin / Operator / Viewer roles |
| 2FA | TOTP-based (Google Authenticator, Authy) |
| Secrets | Encrypted before storage (API tokens, SSH passwords) |

## Environment Variables

See [`.env.example`](.env.example) for all options.

| Variable | Required | Description |
|---|---|---|
| `POSTGRES_PASSWORD` | ✅ | Database password |
| `DATABASE_URL` | ✅ | Async PostgreSQL connection string |
| `SECRET_KEY` | ✅ | JWT signing key (random, 32+ chars) |
| `ALLOWED_ORIGINS` | | Comma-separated CORS origins |
| `AGE_PUBLIC_KEY` | | age public key for backup encryption |
| `VAULTMASTER_PLUGINS_DIR` | | Path to plugins directory |
| `SMTP_*` | | SMTP settings for email notifications |

## License

[MIT](LICENSE) — Copyright (c) 2026 ARC Gruppen AB

See [CHANGELOG.md](CHANGELOG.md) for version history.

## Credits

- **Author**: [ARC Gruppen AB](https://arcgruppen.se) — info@arcgruppen.se
- **Designer**: [Chrille Hedberg](https://chrille.nu) — info@chrille.nu
