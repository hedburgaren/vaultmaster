import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from croniter import croniter
from datetime import datetime, timezone

from api.auth import get_current_user
from api.database import get_db
from api.models.backup_job import BackupJob
from api.schemas import BackupJobCreate, BackupJobUpdate, BackupJobOut

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[BackupJobOut])
async def list_jobs(
    is_active: bool | None = None,
    backup_type: str | None = None,
    domain: str | None = None,
    db: AsyncSession = Depends(get_db),
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
async def create_job(body: BackupJobCreate, db: AsyncSession = Depends(get_db)):
    if not croniter.is_valid(body.schedule_cron):
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {body.schedule_cron}")
    job = BackupJob(**body.model_dump())
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


@router.get("/{job_id}", response_model=BackupJobOut)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BackupJob).where(BackupJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.put("/{job_id}", response_model=BackupJobOut)
async def update_job(job_id: uuid.UUID, body: BackupJobUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BackupJob).where(BackupJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    update_data = body.model_dump(exclude_unset=True)
    if "schedule_cron" in update_data and not croniter.is_valid(update_data["schedule_cron"]):
        raise HTTPException(status_code=400, detail="Invalid cron expression")
    for key, value in update_data.items():
        setattr(job, key, value)
    await db.flush()
    await db.refresh(job)
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BackupJob).where(BackupJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await db.delete(job)


@router.post("/{job_id}/trigger")
async def trigger_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BackupJob).where(BackupJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    from api.tasks.backup_tasks import run_backup_task
    task = run_backup_task.delay(str(job_id))
    return {"task_id": task.id, "status": "queued", "job_id": str(job_id)}


@router.get("/{job_id}/schedule-preview")
async def schedule_preview(job_id: uuid.UUID, count: int = 5, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BackupJob).where(BackupJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    cron = croniter(job.schedule_cron, datetime.now(timezone.utc))
    next_runs = [cron.get_next(datetime).isoformat() for _ in range(count)]
    return {"schedule_cron": job.schedule_cron, "next_runs": next_runs}
