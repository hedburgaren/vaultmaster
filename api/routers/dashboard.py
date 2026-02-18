from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from croniter import croniter

from api.auth import get_current_user
from api.database import get_db
from api.models.server import Server
from api.models.backup_job import BackupJob
from api.models.backup_run import BackupRun
from api.models.storage_destination import StorageDestination
from api.schemas import DashboardOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=DashboardOut)
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    last_24h = now - timedelta(hours=24)

    # Servers
    servers_result = await db.execute(select(Server))
    servers = servers_result.scalars().all()
    servers_online = sum(1 for s in servers if s.is_active and s.last_seen and s.last_seen > now - timedelta(minutes=10))

    # Jobs
    jobs_result = await db.execute(select(BackupJob))
    jobs = jobs_result.scalars().all()
    jobs_active = sum(1 for j in jobs if j.is_active)

    # Storage
    storage_result = await db.execute(select(StorageDestination).where(StorageDestination.is_active == True))
    storage_dests = storage_result.scalars().all()
    storage_info = [
        {
            "id": str(s.id),
            "name": s.name,
            "backend": s.backend,
            "used_bytes": s.used_bytes or 0,
            "capacity_bytes": s.capacity_bytes,
            "percent_used": round((s.used_bytes or 0) / s.capacity_bytes * 100, 1) if s.capacity_bytes else None,
        }
        for s in storage_dests
    ]

    # Runs (last 24h)
    runs_result = await db.execute(
        select(BackupRun).where(BackupRun.created_at >= last_24h)
    )
    runs = runs_result.scalars().all()
    runs_success = sum(1 for r in runs if r.status == "success")
    runs_failed = sum(1 for r in runs if r.status == "failed")
    success_rate = round(runs_success / len(runs) * 100, 1) if runs else 0.0

    # Next scheduled runs
    next_runs = []
    for job in jobs:
        if job.is_active and job.schedule_cron:
            try:
                cron = croniter(job.schedule_cron, now)
                next_time = cron.get_next(datetime)
                next_runs.append({
                    "job_id": str(job.id),
                    "job_name": job.name,
                    "next_run": next_time.isoformat(),
                    "seconds_until": int((next_time - now).total_seconds()),
                })
            except Exception:
                pass
    next_runs.sort(key=lambda x: x["seconds_until"])

    # Active runs
    active_result = await db.execute(
        select(BackupRun).where(BackupRun.status == "running")
    )
    active_runs = [
        {
            "id": str(r.id),
            "job_id": str(r.job_id),
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
        }
        for r in active_result.scalars().all()
    ]

    # Recent errors
    error_result = await db.execute(
        select(BackupRun)
        .where(BackupRun.status == "failed")
        .order_by(BackupRun.created_at.desc())
        .limit(5)
    )
    recent_errors = [
        {
            "id": str(r.id),
            "job_id": str(r.job_id),
            "error": r.error_message,
            "created_at": r.created_at.isoformat(),
        }
        for r in error_result.scalars().all()
    ]

    return DashboardOut(
        servers_online=servers_online,
        servers_total=len(servers),
        jobs_active=jobs_active,
        jobs_total=len(jobs),
        storage_destinations=storage_info,
        runs_24h=len(runs),
        runs_success_24h=runs_success,
        runs_failed_24h=runs_failed,
        success_rate=success_rate,
        next_runs=next_runs[:10],
        active_runs=active_runs,
        recent_errors=recent_errors,
    )
