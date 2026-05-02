import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.database import get_db
from api.models.backup_job import BackupJob
from api.models.backup_validation_run import BackupValidationRun
from api.schemas import BackupValidationRunOut, BackupValidationTrigger

router = APIRouter(prefix="/validations", tags=["validations"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[BackupValidationRunOut])
async def list_validations(
    job_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = select(BackupValidationRun).order_by(desc(BackupValidationRun.created_at)).limit(limit).offset(offset)
    if job_id:
        query = query.where(BackupValidationRun.job_id == job_id)
    if status_filter:
        query = query.where(BackupValidationRun.status == status_filter)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/latest-by-job")
async def latest_by_job(db: AsyncSession = Depends(get_db)):
    """Most recent validation run per job — used by the jobs list to
    show a "last validated" badge."""
    subq = (
        select(
            BackupValidationRun.job_id,
            func.max(BackupValidationRun.created_at).label("max_ts"),
        )
        .group_by(BackupValidationRun.job_id)
        .subquery()
    )
    result = await db.execute(
        select(BackupValidationRun)
        .join(subq, (BackupValidationRun.job_id == subq.c.job_id) & (BackupValidationRun.created_at == subq.c.max_ts))
    )
    latest = result.scalars().all()
    return [
        {
            "job_id": str(v.job_id),
            "status": v.status,
            "finished_at": v.finished_at.isoformat() if v.finished_at else None,
            "duration_seconds": v.duration_seconds,
            "error_message": v.error_message,
        }
        for v in latest
    ]


@router.get("/{validation_id}", response_model=BackupValidationRunOut)
async def get_validation(validation_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(BackupValidationRun).where(BackupValidationRun.id == validation_id)
    )
    v = result.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Validation run not found")
    return v


@router.post("/jobs/{job_id}/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_validation(
    job_id: uuid.UUID,
    body: BackupValidationTrigger,
    db: AsyncSession = Depends(get_db),
):
    """Queue a validation for the given job. Runs asynchronously via Celery."""
    result = await db.execute(select(BackupJob).where(BackupJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    from api.tasks.validation_tasks import validate_backup_job_task
    artifact_id_str = str(body.artifact_id) if body.artifact_id else None
    validate_backup_job_task.delay(str(job_id), artifact_id_str, "manual")
    return {"queued": True, "job_id": str(job_id), "check_type": body.check_type}
