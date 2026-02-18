import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from api.auth import get_current_user
from api.database import get_db
from api.models.backup_run import BackupRun
from api.schemas import BackupRunOut

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[BackupRunOut])
async def list_runs(
    status: str | None = None,
    job_id: uuid.UUID | None = None,
    server_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = select(BackupRun).order_by(desc(BackupRun.created_at)).limit(limit).offset(offset)
    if status:
        query = query.where(BackupRun.status == status)
    if job_id:
        query = query.where(BackupRun.job_id == job_id)
    if server_id:
        query = query.where(BackupRun.server_id == server_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{run_id}", response_model=BackupRunOut)
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BackupRun).where(BackupRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/{run_id}/log")
async def stream_run_log(run_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    """SSE endpoint for live log streaming."""
    result = await db.execute(select(BackupRun).where(BackupRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    import asyncio
    import json

    async def event_generator():
        last_index = 0
        while True:
            if await request.is_disconnected():
                break
            # Re-fetch run to get latest log lines
            async with get_db().__class__(bind=None) as fresh_db:
                pass
            # For now, return existing log lines
            if run.log_lines and last_index < len(run.log_lines):
                for line in run.log_lines[last_index:]:
                    yield {"event": "log", "data": json.dumps(line)}
                last_index = len(run.log_lines)
            if run.status in ("success", "failed", "cancelled"):
                yield {"event": "done", "data": json.dumps({"status": run.status, "size_bytes": run.size_bytes})}
                break
            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BackupRun).where(BackupRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "running":
        raise HTTPException(status_code=400, detail="Can only cancel running jobs")
    run.status = "cancelled"
    await db.flush()
    return {"status": "cancelled", "run_id": str(run_id)}
