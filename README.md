# 🔐 VaultMaster — Backup Control Center

Self-hosted backup orchestration system with a dark sci-fi control panel UI. Manage PostgreSQL dumps, Docker volume snapshots, file backups, and more — across multiple servers with SSH, scheduled via cron, with GFS retention policies, encrypted storage, and multi-channel notifications.

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/hedburgaren/vaultmaster.git
cd vaultmaster
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD, DATABASE_URL, and SECRET_KEY

# 2. Start all services
docker compose up -d

# 3. Install frontend dependencies and build
cd ui
cp .env.example .env.local
# Edit .env.local if your API is not on localhost:8100
npm install
npx next build

# 4. Start the frontend (or use your own reverse proxy)
npx next start --port 3100

# 5. Open http://localhost:3100
# On first visit you'll be redirected to the setup wizard
# to create your admin account.
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

- **API**: FastAPI (Python 3.12)
- **Worker**: Celery (4 concurrent workers)
- **Scheduler**: Celery Beat (cron-based job scheduling)
- **Database**: PostgreSQL 16
- **Queue**: Redis 7
- **Frontend**: Next.js 14 + TailwindCSS
- **SSH**: AsyncSSH for remote server management
- **Storage**: rclone for multi-backend file transfer (local, S3, GDrive, SFTP, B2)
- **Encryption**: age (AES)

## Features

- **Multi-server management** — SSH key/password auth, health monitoring
- **Backup types** — PostgreSQL, Docker volumes, files, DigitalOcean snapshots, custom scripts
- **Cron scheduling** — with next-run preview
- **GFS retention** — Grandfather-Father-Son rotation with dry-run preview
- **Multi-backend storage** — local, S3/DO Spaces, Google Drive, SFTP, Backblaze B2
- **Encryption** — age-based backup encryption
- **Notifications** — Slack, ntfy, Telegram, email, webhooks
- **Live logs** — Server-Sent Events for real-time backup progress
- **Restore wizard** — search, filter, verify checksum, one-click restore
- **Initial setup wizard** — first-run admin account creation (no hardcoded credentials)

## API Endpoints

| Route | Description |
|---|---|
| `GET /api/v1/auth/setup-status` | Check if initial setup is needed |
| `POST /api/v1/auth/setup` | Create first admin (only when no users exist) |
| `POST /api/v1/auth/login` | JWT authentication (rate limited: 5/min) |
| `GET /api/v1/auth/me` | Current user info |
| `PUT /api/v1/auth/profile` | Update email addresses |
| `POST /api/v1/auth/change-password` | Change password |
| `POST /api/v1/auth/api-key` | Generate API key (shown once) |
| `DELETE /api/v1/auth/api-key` | Revoke API key |
| `GET /api/v1/dashboard` | Aggregated overview |
| `/api/v1/servers` | CRUD + test + file browser |
| `/api/v1/jobs` | CRUD + trigger + schedule preview |
| `/api/v1/runs` | List + live log (SSE) + cancel |
| `/api/v1/artifacts` | Search/filter + restore + verify |
| `/api/v1/storage` | CRUD + test + usage + browser |
| `/api/v1/retention` | CRUD + rotation preview |
| `/api/v1/notifications/channels` | CRUD + test |
| `GET /api/health` | Health check |

Full interactive API docs available at `/api/docs` (Swagger) and `/api/redoc`.

## First Login

On first launch, navigate to the UI. If no admin account exists, you'll be automatically redirected to `/setup` where you can create your admin account. No default credentials are shipped with the application.

## API Keys & External Integrations

VaultMaster supports API key authentication for headless/external use:

1. Go to **Settings → Profile & API → API Key**
2. Click **Generate API Key**
3. Copy the key (it's only shown once)
4. Pass it as `X-API-Key` header in your requests

```bash
curl -H "X-API-Key: vm_your_key_here" https://your-vaultmaster/api/v1/jobs
```

See **[n8n Integration Guide](docs/n8n-integration.md)** for detailed workflow examples.

## Security

- **Rate limiting** — Login: 5 req/min, API: 120 req/min per IP
- **Security headers** — HSTS, X-Frame-Options DENY, X-Content-Type-Options, Referrer-Policy, Permissions-Policy
- **API key hashing** — Keys are SHA-256 hashed before storage; raw keys are never persisted
- **Configurable CORS** — Set `ALLOWED_ORIGINS` in `.env` to restrict cross-origin access
- **bcrypt passwords** — All passwords hashed with bcrypt (cost factor 12)
- **JWT tokens** — Short-lived (24h default), HS256 signed with your `SECRET_KEY`
- **No default credentials** — First-run setup wizard, no hardcoded accounts

## Environment Variables

See [`.env.example`](.env.example) for all available configuration options. Key variables:

| Variable | Description |
|---|---|
| `POSTGRES_PASSWORD` | Database password |
| `DATABASE_URL` | Full async database connection string |
| `SECRET_KEY` | JWT signing key (generate a random one!) |
| `AGE_PUBLIC_KEY` | Optional: age public key for backup encryption |
| `SMTP_*` | Optional: SMTP settings for email notifications |

## License

[MIT](LICENSE) — Copyright (c) 2026 ARC Gruppen AB

## Credits

- **Author**: [ARC Gruppen AB](https://example.com) — info@example.com
- **Designer**: [Chrille Hedberg](https://example.com) — info@example.com
