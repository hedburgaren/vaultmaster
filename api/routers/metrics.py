from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.server import Server
from api.models.backup_job import BackupJob
from api.models.backup_run import BackupRun
from api.models.storage_destination import StorageDestination
from api.models.backup_artifact import BackupArtifact
from api.models.user import User

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics(db: AsyncSession = Depends(get_db)):
    """Prometheus-compatible /metrics endpoint."""
    now = datetime.now(timezone.utc)
    last_24h = now - timedelta(hours=24)
    lines = []

    def gauge(name: str, help_text: str, value, labels: dict | None = None):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        if labels:
            lbl = ",".join(f'{k}="{v}"' for k, v in labels.items())
            lines.append(f"{name}{{{lbl}}} {value}")
        else:
            lines.append(f"{name} {value}")

    # Servers
    servers = (await db.execute(select(Server))).scalars().all()
    gauge("vaultmaster_servers_total", "Total number of servers", len(servers))
    online = sum(1 for s in servers if s.is_active and s.last_seen and s.last_seen > now - timedelta(minutes=10))
    gauge("vaultmaster_servers_online", "Number of online servers", online)

    # Jobs
    jobs = (await db.execute(select(BackupJob))).scalars().all()
    gauge("vaultmaster_jobs_total", "Total number of backup jobs", len(jobs))
    gauge("vaultmaster_jobs_active", "Number of active backup jobs", sum(1 for j in jobs if j.is_active))

    # Runs (24h)
    runs_24h = (await db.execute(select(BackupRun).where(BackupRun.created_at >= last_24h))).scalars().all()
    gauge("vaultmaster_runs_24h_total", "Total runs in last 24h", len(runs_24h))
    gauge("vaultmaster_runs_24h_success", "Successful runs in last 24h", sum(1 for r in runs_24h if r.status == "success"))
    gauge("vaultmaster_runs_24h_failed", "Failed runs in last 24h", sum(1 for r in runs_24h if r.status == "failed"))
    gauge("vaultmaster_runs_active", "Currently running backups", sum(1 for r in runs_24h if r.status == "running"))

    # Success rate
    success = sum(1 for r in runs_24h if r.status == "success")
    rate = round(success / len(runs_24h) * 100, 1) if runs_24h else 0
    gauge("vaultmaster_success_rate_24h", "Backup success rate in last 24h (percent)", rate)

    # Storage
    storage = (await db.execute(select(StorageDestination).where(StorageDestination.is_active == True))).scalars().all()
    for s in storage:
        gauge("vaultmaster_storage_used_bytes", "Storage used in bytes", s.used_bytes or 0, {"name": s.name, "backend": s.backend})
        if s.capacity_bytes:
            gauge("vaultmaster_storage_capacity_bytes", "Storage capacity in bytes", s.capacity_bytes, {"name": s.name, "backend": s.backend})
            pct = round((s.used_bytes or 0) / s.capacity_bytes * 100, 1)
            gauge("vaultmaster_storage_used_percent", "Storage used percentage", pct, {"name": s.name, "backend": s.backend})

    # Artifacts
    artifact_count = (await db.execute(select(func.count()).select_from(BackupArtifact))).scalar() or 0
    gauge("vaultmaster_artifacts_total", "Total number of backup artifacts", artifact_count)
    artifact_size = (await db.execute(select(func.sum(BackupArtifact.size_bytes)))).scalar() or 0
    gauge("vaultmaster_artifacts_total_bytes", "Total size of all artifacts in bytes", artifact_size)

    # Users
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    gauge("vaultmaster_users_total", "Total number of users", user_count)

    return "\n".join(lines) + "\n"
