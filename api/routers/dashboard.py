from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from croniter import croniter

from api.auth import get_current_user
from api.database import get_db
from api.models.server import Server
from api.models.backup_job import BackupJob
from api.models.backup_run import BackupRun
from api.models.storage_destination import StorageDestination
from api.models.backup_artifact import BackupArtifact
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
    # Failed-count for the topbar bell counts only un-acknowledged ones,
    # so it stays in lockstep with the recent_errors panel below.
    # Status text on dashboard still reflects total failure rate.
    runs_failed = sum(1 for r in runs if r.status == "failed" and r.acknowledged_at is None)
    runs_failed_total = sum(1 for r in runs if r.status == "failed")
    success_rate = round(runs_success / max(runs_success + runs_failed_total, 1) * 100, 1)

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

    # Recent errors — join job + server names for the topbar panel,
    # and surface the last log line so users can read what actually broke.
    error_result = await db.execute(
        select(BackupRun, BackupJob, Server)
        .join(BackupJob, BackupRun.job_id == BackupJob.id)
        .join(Server, BackupRun.server_id == Server.id)
        .where(BackupRun.status == "failed", BackupRun.acknowledged_at.is_(None))
        .order_by(BackupRun.created_at.desc())
        .limit(5)
    )
    recent_errors = []
    for r, j, s in error_result.all():
        last_log_msg = None
        if r.log_lines:
            for entry in reversed(r.log_lines):
                if isinstance(entry, dict) and entry.get("level") in ("error", "warn") and entry.get("msg"):
                    last_log_msg = str(entry["msg"])[:300]
                    break
        recent_errors.append({
            "id": str(r.id),
            "job_id": str(r.job_id),
            "job_name": j.name,
            "server_name": s.name,
            "error": r.error_message,
            "last_log": last_log_msg,
            "retry_count": r.retry_count,
            "created_at": r.created_at.isoformat(),
        })

    # Server health (per-server status)
    server_health = []
    for s in servers:
        online = bool(s.is_active and s.last_seen and s.last_seen > now - timedelta(minutes=10))
        last_seen_ago = None
        if s.last_seen:
            last_seen_ago = round((now - s.last_seen.replace(tzinfo=timezone.utc) if s.last_seen.tzinfo is None else now - s.last_seen).total_seconds() / 3600, 1)
        server_health.append({
            "id": str(s.id),
            "name": s.name,
            "host": s.host,
            "online": online,
            "last_seen_hours_ago": last_seen_ago,
            "tags": s.tags or [],
        })

    # Artifacts totals
    artifact_count = (await db.execute(select(func.count()).select_from(BackupArtifact))).scalar() or 0
    artifact_bytes = (await db.execute(select(func.sum(BackupArtifact.size_bytes)))).scalar() or 0

    # Last successful backup
    last_ok_result = await db.execute(
        select(BackupRun)
        .where(BackupRun.status == "success")
        .order_by(desc(BackupRun.finished_at))
        .limit(1)
    )
    last_ok = last_ok_result.scalar_one_or_none()
    last_ok_iso = None
    hours_since = None
    if last_ok and last_ok.finished_at:
        finished = last_ok.finished_at.replace(tzinfo=timezone.utc) if last_ok.finished_at.tzinfo is None else last_ok.finished_at
        last_ok_iso = finished.isoformat()
        hours_since = round((now - finished).total_seconds() / 3600, 1)

    # Storage warnings (>70% used)
    storage_warnings = []
    for s in storage_dests:
        if s.capacity_bytes and s.used_bytes:
            pct = round(s.used_bytes / s.capacity_bytes * 100, 1)
            if pct > 70:
                level = "critical" if pct > 90 else "warning"
                storage_warnings.append({
                    "id": str(s.id),
                    "name": s.name,
                    "backend": s.backend,
                    "percent_used": pct,
                    "level": level,
                })

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
        server_health=server_health,
        total_artifacts=artifact_count,
        total_artifact_bytes=artifact_bytes,
        last_successful_backup=last_ok_iso,
        hours_since_last_backup=hours_since,
        storage_warnings=storage_warnings,
    )


@router.get("/stats")
async def get_stats(days: int = 30, db: AsyncSession = Depends(get_db)):
    """Aggregate stats for analytics view (trends, fail-rate, top jobs)."""
    days = max(1, min(days, 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Daily success/fail counts + total bytes
    daily_q = await db.execute(
        select(
            func.date_trunc('day', BackupRun.created_at).label('day'),
            func.count().filter(BackupRun.status == 'success').label('ok'),
            func.count().filter(BackupRun.status == 'failed').label('fail'),
            func.coalesce(func.sum(BackupRun.size_bytes).filter(BackupRun.status == 'success'), 0).label('bytes'),
        )
        .where(BackupRun.created_at >= since)
        .group_by('day')
        .order_by('day')
    )
    daily = [
        {
            "day": d.isoformat() if d else None,
            "ok": int(ok),
            "fail": int(fail),
            "bytes": int(bytes),
        }
        for d, ok, fail, bytes in daily_q.all()
    ]

    # Per-job fail-rate (top 10 worst)
    perjob_q = await db.execute(
        select(
            BackupJob.id,
            BackupJob.name,
            func.count().filter(BackupRun.status == 'success').label('ok'),
            func.count().filter(BackupRun.status == 'failed').label('fail'),
            func.coalesce(func.avg(BackupRun.size_bytes).filter(BackupRun.status == 'success'), 0).label('avg_bytes'),
        )
        .join(BackupRun, BackupRun.job_id == BackupJob.id)
        .where(BackupRun.created_at >= since)
        .group_by(BackupJob.id, BackupJob.name)
    )
    perjob = []
    for jid, name, ok, fail, avg in perjob_q.all():
        total = int(ok) + int(fail)
        if total == 0:
            continue
        perjob.append({
            "job_id": str(jid),
            "name": name,
            "ok": int(ok),
            "fail": int(fail),
            "fail_rate": round(int(fail) / total, 3),
            "avg_size_bytes": int(avg or 0),
        })
    perjob.sort(key=lambda x: -x["fail_rate"])
    top_failing = [j for j in perjob if j["fail_rate"] > 0][:10]

    # Per backup_type totals
    bytype_q = await db.execute(
        select(
            BackupArtifact.backup_type,
            func.count().label('count'),
            func.coalesce(func.sum(BackupArtifact.size_bytes), 0).label('bytes'),
        )
        .where(BackupArtifact.created_at >= since, BackupArtifact.is_deleted == False)
        .group_by(BackupArtifact.backup_type)
    )
    by_type = [
        {"backup_type": t or "unknown", "count": int(c), "bytes": int(b)}
        for t, c, b in bytype_q.all()
    ]

    return {
        "since": since.isoformat(),
        "days": days,
        "daily": daily,
        "per_job": perjob,
        "top_failing_jobs": top_failing,
        "by_backup_type": by_type,
    }
