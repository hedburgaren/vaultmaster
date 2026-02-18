import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from api.auth import get_current_user
from api.database import get_db
from api.models.backup_artifact import BackupArtifact
from api.schemas import BackupArtifactOut

router = APIRouter(prefix="/artifacts", tags=["artifacts"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[BackupArtifactOut])
async def search_artifacts(
    q: str | None = None,
    backup_type: str | None = None,
    domain: str | None = None,
    server_name: str | None = None,
    tags: list[str] | None = Query(None),
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = select(BackupArtifact).where(BackupArtifact.is_deleted == False).order_by(desc(BackupArtifact.created_at))

    if q:
        query = query.where(
            or_(
                BackupArtifact.filename.ilike(f"%{q}%"),
                BackupArtifact.db_name.ilike(f"%{q}%"),
                BackupArtifact.domain.ilike(f"%{q}%"),
                BackupArtifact.server_name.ilike(f"%{q}%"),
            )
        )
    if backup_type:
        query = query.where(BackupArtifact.backup_type == backup_type)
    if domain:
        query = query.where(BackupArtifact.domain == domain)
    if server_name:
        query = query.where(BackupArtifact.server_name == server_name)
    if tags:
        query = query.where(BackupArtifact.tags.overlap(tags))
    if from_date:
        query = query.where(BackupArtifact.created_at >= from_date)
    if to_date:
        query = query.where(BackupArtifact.created_at <= to_date)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{artifact_id}", response_model=BackupArtifactOut)
async def get_artifact(artifact_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BackupArtifact).where(BackupArtifact.id == artifact_id))
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@router.post("/{artifact_id}/restore")
async def restore_artifact(
    artifact_id: uuid.UUID,
    target_server_id: uuid.UUID | None = None,
    target_db_name: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(BackupArtifact).where(BackupArtifact.id == artifact_id))
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    from api.tasks.backup_tasks import run_restore_task
    task = run_restore_task.delay(str(artifact_id), str(target_server_id) if target_server_id else None, target_db_name)
    return {"task_id": task.id, "status": "queued", "artifact_id": str(artifact_id)}


@router.post("/{artifact_id}/verify")
async def verify_artifact(artifact_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BackupArtifact).where(BackupArtifact.id == artifact_id))
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    from api.tasks.backup_tasks import verify_artifact_checksum
    task = verify_artifact_checksum.delay(str(artifact_id))
    return {"task_id": task.id, "status": "queued"}
