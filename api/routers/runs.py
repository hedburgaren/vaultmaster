import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from api.auth import get_current_user
from api.database import async_session, get_db
from api.models.backup_run import BackupRun
from api.schemas import BackupRunOut

logger = logging.getLogger(__name__)

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
async def stream_run_log(run_id: uuid.UUID, request: Request):
    """SSE endpoint for live log streaming.

    Each iteration opens a fresh `async_session()` and re-reads the run row,
    so newly-appended `log_lines` from the worker are visible. The previous
    implementation captured `run` once outside the loop (and the only
    "re-fetch" was a dead `pass` inside an `async with`), which meant the
    UI saw the snapshot at SSE-open and nothing more — bug #11.

    Events emitted:
        - `status`  — fired once on connect AND every time `run.status`
                      changes (e.g. running → success).
        - `log`     — every newly-appended item in `run.log_lines`.
        - `done`    — terminal event when status reaches a terminal state
                      (success, failed, cancelled, partial). Stream then
                      closes from the server side.

    Idempotent reconnects: the client gets one `status` and the full log
    backlog up to `last_index = 0`. We don't try to deduplicate — SSE
    is fire-and-forget by design and clients re-render anyway.
    """

    async def event_generator():
        last_index = 0
        last_status: str | None = None

        # Verify the run exists once before starting the loop so we get a
        # proper 404 instead of an empty SSE stream.
        async with async_session() as db:
            r0 = (
                await db.execute(select(BackupRun).where(BackupRun.id == run_id))
            ).scalar_one_or_none()
        if not r0:
            yield {"event": "error", "data": json.dumps({"detail": "Run not found"})}
            return

        try:
            while True:
                if await request.is_disconnected():
                    break

                # Fresh session each iteration. expire_on_commit=False on the
                # global sessionmaker means the row is detached and stable
                # within the iteration — exactly what we want.
                async with async_session() as db:
                    run = (
                        await db.execute(
                            select(BackupRun).where(BackupRun.id == run_id)
                        )
                    ).scalar_one_or_none()

                if run is None:
                    yield {
                        "event": "error",
                        "data": json.dumps({"detail": "Run disappeared"}),
                    }
                    break

                # Status transitions
                if run.status != last_status:
                    yield {
                        "event": "status",
                        "data": json.dumps(
                            {
                                "status": run.status,
                                "started_at": run.started_at.isoformat()
                                if run.started_at
                                else None,
                                "finished_at": run.finished_at.isoformat()
                                if run.finished_at
                                else None,
                            }
                        ),
                    }
                    last_status = run.status

                # New log lines since last poll
                lines = run.log_lines or []
                if last_index < len(lines):
                    for line in lines[last_index:]:
                        yield {"event": "log", "data": json.dumps(line)}
                    last_index = len(lines)

                # Terminal state — emit `done` and close.
                if run.status in ("success", "failed", "cancelled", "partial"):
                    yield {
                        "event": "done",
                        "data": json.dumps(
                            {
                                "status": run.status,
                                "size_bytes": run.size_bytes,
                                "error_message": run.error_message,
                            }
                        ),
                    }
                    break

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            # Client disconnected mid-stream. Don't propagate — sse-starlette
            # already handles cleanup and re-raising spams the API log.
            return

    return EventSourceResponse(event_generator())


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Cancel a running backup.

    Two-step: (1) flip DB status so the SSE viewer immediately sees
    `cancelled`, (2) `celery_app.control.revoke(..., terminate=True)` so
    the worker actually stops instead of overwriting our DB-status with
    `success` 30s later. Bug #12.

    Legacy runs created before migration 0004 have `celery_task_id IS
    NULL` — for those we still flip DB status (best-effort), but the
    worker will keep running until completion. New runs cancel cleanly.
    """
    result = await db.execute(select(BackupRun).where(BackupRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "running":
        raise HTTPException(status_code=400, detail="Can only cancel running jobs")

    run.status = "cancelled"
    await db.flush()

    revoked = False
    if run.celery_task_id:
        try:
            # Import here to avoid pulling Celery into the request import
            # chain (and to keep the OpenAPI schema-gen lightweight).
            from api.tasks.celery_app import celery_app

            celery_app.control.revoke(
                run.celery_task_id, terminate=True, signal="SIGTERM"
            )
            revoked = True
            logger.info(
                "Revoked Celery task %s for run %s", run.celery_task_id, run_id
            )
        except Exception as exc:
            # We've already flipped DB status — don't fail the request just
            # because the broker hiccuped. Worker will eventually catch up
            # via the next visibility timeout.
            logger.warning(
                "control.revoke failed for run %s task %s: %s",
                run_id,
                run.celery_task_id,
                exc,
            )

    return {
        "status": "cancelled",
        "run_id": str(run_id),
        "revoked": revoked,
        "celery_task_id": run.celery_task_id,
    }


@router.post("/{run_id}/acknowledge")
async def acknowledge_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Mark a failed run as 'seen' so it disappears from the topbar
    notification panel. Doesn't change status — just hides it from the
    fresh-error feed."""
    from datetime import datetime, timezone
    result = await db.execute(select(BackupRun).where(BackupRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run.acknowledged_at = datetime.now(timezone.utc)
    await db.flush()
    return {"acknowledged": True, "run_id": str(run_id)}


@router.post("/acknowledge-all")
async def acknowledge_all(db: AsyncSession = Depends(get_db)):
    """Bulk-ack: clear all unacknowledged failed runs from the topbar
    panel in one click."""
    from datetime import datetime, timezone
    from sqlalchemy import update
    result = await db.execute(
        update(BackupRun)
        .where(BackupRun.status == "failed", BackupRun.acknowledged_at.is_(None))
        .values(acknowledged_at=datetime.now(timezone.utc))
        .returning(BackupRun.id)
    )
    ids = [str(r) for r in result.scalars().all()]
    return {"acknowledged": len(ids), "run_ids": ids}
