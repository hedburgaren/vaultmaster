# VaultMaster × n8n Integration Guide

Use VaultMaster's REST API to create, trigger, and manage backups from [n8n](https://n8n.io) workflows. This enables powerful automation scenarios like:

- Trigger a backup before deploying new code
- Run a backup after a database migration
- Schedule complex multi-server backup chains
- Send custom notifications when backups complete or fail
- Auto-restore from the latest artifact on a staging server

## Prerequisites

1. A running VaultMaster instance
2. An API key (generated in **Settings → Profile & API → API Key**)
3. n8n with access to your VaultMaster API URL

## Authentication

All API requests require the `X-API-Key` header:

```
X-API-Key: vm_your_api_key_here
```

In n8n, use the **HTTP Request** node with:
- **Authentication**: Header Auth
- **Name**: `X-API-Key`
- **Value**: `{{ $credentials.vaultmasterApiKey }}` (or paste directly)

> **Tip**: Store your API key as an n8n credential of type "Header Auth" for reuse across nodes.

## Common Workflows

### 1. Trigger a Backup Job

```
POST /api/v1/jobs/{job_id}/trigger
```

**n8n HTTP Request node:**
- **Method**: POST
- **URL**: `https://your-vaultmaster.example.com/api/v1/jobs/{job_id}/trigger`
- **Headers**: `X-API-Key: vm_...`

**Response:**
```json
{
  "run_id": "uuid",
  "status": "queued",
  "message": "Backup job triggered"
}
```

### 2. List All Servers

```
GET /api/v1/servers
```

Returns an array of server objects with `id`, `name`, `host`, `is_active`, `last_seen`, etc.

### 3. Create a Backup Job

```
POST /api/v1/jobs
Content-Type: application/json

{
  "name": "Nightly PostgreSQL",
  "backup_type": "postgresql",
  "server_id": "uuid-of-server",
  "schedule_cron": "0 3 * * *",
  "source_config": {
    "database": "myapp_production"
  },
  "tags": ["critical", "nightly"],
  "encrypt": true
}
```

**Backup types**: `postgresql`, `docker_volumes`, `files`, `do_snapshot`, `custom`

### 4. Monitor Backup Runs

```
GET /api/v1/runs
```

Returns recent runs with `status` (`queued`, `running`, `success`, `failed`, `cancelled`).

**Poll for completion** in n8n using a **Wait** node + **IF** node:

```
GET /api/v1/runs/{run_id}
```

Check `status` field — loop until it's `success` or `failed`.

### 5. Search Backup Artifacts

```
GET /api/v1/artifacts?backup_type=postgresql&q=myapp
```

Query parameters:
- `q` — free-text search
- `backup_type` — filter by type
- `domain` — filter by domain
- `server_name` — filter by server
- `from_date` / `to_date` — date range
- `limit` / `offset` — pagination

### 6. Restore from an Artifact

```
POST /api/v1/artifacts/{artifact_id}/restore
Content-Type: application/json

{}
```

Returns a `task_id` for the async restore operation.

### 7. Get Dashboard Overview

```
GET /api/v1/dashboard
```

Returns aggregated stats: servers online, active jobs, 24h success/failure rates, storage usage, upcoming runs, and recent errors.

### 8. Live Backup Logs (SSE)

```
GET /api/v1/runs/{run_id}/logs
Accept: text/event-stream
```

Streams real-time log lines as Server-Sent Events. Useful for monitoring long-running backups.

> **Note**: n8n's HTTP Request node doesn't support SSE natively. Use this endpoint from custom scripts or the VaultMaster UI.

## Example: Pre-Deploy Backup Workflow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Webhook      │───▶│ Trigger      │───▶│ Wait + Poll  │───▶│ Deploy       │
│  (from CI/CD) │    │ VM Backup    │    │ Until Done   │    │ (if success) │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

1. **Webhook node** — receives a deploy trigger from your CI/CD pipeline
2. **HTTP Request node** — `POST /api/v1/jobs/{job_id}/trigger`
3. **Wait node** (5s) + **HTTP Request** (`GET /api/v1/runs/{run_id}`) + **IF** (status == "success")
4. **HTTP Request node** — call your deploy script/webhook

## Full API Reference

Interactive API documentation is always available at:

- **Swagger UI**: `https://your-vaultmaster.example.com/api/docs`
- **ReDoc**: `https://your-vaultmaster.example.com/api/redoc`
- **OpenAPI JSON**: `https://your-vaultmaster.example.com/api/openapi.json`

The OpenAPI spec can be imported directly into n8n as a custom API definition.

## Rate Limits

- **Login**: 5 requests/minute per IP
- **All other endpoints**: 120 requests/minute per IP

If you hit a rate limit, you'll receive a `429 Too Many Requests` response.

## Security Notes

- API keys are SHA-256 hashed before storage — VaultMaster never stores your raw key
- Keys are prefixed with `vm_` for easy identification in logs
- Revoke and regenerate keys anytime from the Settings page
- Use `ALLOWED_ORIGINS` in `.env` to restrict CORS if your n8n instance is on a different domain
