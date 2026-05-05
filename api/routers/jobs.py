import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession
from croniter import croniter
from datetime import datetime, timezone

from api.auth import get_current_user
from api.database import get_db
from api.models.backup_job import BackupJob
from api.models.backup_validation_run import BackupValidationRun
from api.models.user import User
from api.routers.audit import log_action
from api.schemas import BackupJobCreate, BackupJobUpdate, BackupJobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _require_admin_for_custom(body_dump: dict, current_user: User, action: str) -> None:
    """Bug #23: custom-script backups can run arbitrary shell on the target server.
    Lock creation/update of `backup_type='custom'` jobs to admin users."""
    if body_dump.get("backup_type") == "custom" and not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Only admin users may {action} custom-script backup jobs",
        )


@router.get("", response_model=list[BackupJobOut])
async def list_jobs(
    is_active: bool | None = None,
    backup_type: str | None = None,
    domain: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(BackupJob).order_by(BackupJob.name)
    if is_active is not None:
        query = query.where(BackupJob.is_active == is_active)
    if backup_type:
        query = query.where(BackupJob.backup_type == backup_type)
    if domain:
        query = query.where(BackupJob.domain == domain)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=BackupJobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: BackupJobCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not croniter.is_valid(body.schedule_cron):
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {body.schedule_cron}")
    body_dump = body.model_dump()
    _require_admin_for_custom(body_dump, current_user, "create")
    job = BackupJob(**body_dump)
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


@router.get("/{job_id}", response_model=BackupJobOut)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(BackupJob).where(BackupJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.put("/{job_id}", response_model=BackupJobOut)
async def update_job(
    job_id: uuid.UUID,
    body: BackupJobUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(BackupJob).where(BackupJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    update_data = body.model_dump(exclude_unset=True)
    if "schedule_cron" in update_data and not croniter.is_valid(update_data["schedule_cron"]):
        raise HTTPException(status_code=400, detail="Invalid cron expression")
    # Bug #23: gate custom-script backups behind admin both when switching INTO
    # custom and when editing an already-custom job (defense in depth).
    effective_type = update_data.get("backup_type", job.backup_type)
    if effective_type == "custom" and not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin users may edit custom-script backup jobs",
        )
    for key, value in update_data.items():
        setattr(job, key, value)
    await db.flush()
    await db.refresh(job)
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(BackupJob).where(BackupJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # backup_validation_run has a FK to backup_job but no cascade declared
    # at either ORM or DB level — clear them explicitly so the delete
    # doesn't trip the FK constraint.
    await db.execute(sql_delete(BackupValidationRun).where(BackupValidationRun.job_id == job_id))
    await db.delete(job)


@router.post("/{job_id}/trigger")
async def trigger_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(BackupJob).where(BackupJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    from api.tasks.backup_tasks import run_backup_task
    task = run_backup_task.apply_async(args=[str(job_id)], kwargs={"triggered_by": "manual"})
    # Bug #10: explicit audit entry tying the queued Celery task to the BackupJob.
    # The actual BackupRun.id is created inside the worker, so the task_id is
    # the durable correlation handle here.
    await log_action(
        db,
        action="job.trigger",
        user=current_user,
        resource_type="backup_job",
        resource_id=str(job_id),
        detail=f"Manual trigger queued (job_name={job.name})",
        meta={"task_id": task.id, "triggered_by": "manual"},
    )
    return {"task_id": task.id, "status": "queued", "job_id": str(job_id)}


@router.get("/{job_id}/schedule-preview")
async def schedule_preview(
    job_id: uuid.UUID,
    count: int = 5,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(BackupJob).where(BackupJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    cron = croniter(job.schedule_cron, datetime.now(timezone.utc))
    next_runs = [cron.get_next(datetime).isoformat() for _ in range(count)]
    return {"schedule_cron": job.schedule_cron, "next_runs": next_runs}
