import asyncio
import logging

from api.tasks.celery_app import celery_app
from api.tasks.backup_tasks import get_task_session

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="api.tasks.rotation_tasks.run_rotation")
def run_rotation(policy_id: str, job_id: str | None = None):
    """Run GFS rotation for a specific retention policy."""
    _run_async(_do_rotation(policy_id, job_id))


async def _do_rotation(policy_id: str, job_id: str | None):
    import uuid
    from sqlalchemy import select
    from api.models.backup_artifact import BackupArtifact
    from api.models.backup_run import BackupRun
    from api.models.retention_policy import RetentionPolicy
    from api.services.rotation import apply_rotation
    from api.services.notifier import notify_event

    async with get_task_session() as db:
        result = await db.execute(select(RetentionPolicy).where(RetentionPolicy.id == uuid.UUID(policy_id)))
        policy = result.scalar_one_or_none()
        if not policy:
            logger.error(f"Retention policy {policy_id} not found")
            return

        # Bug #14: iterate per storage destination so two artifacts from the
        # SAME run that landed in different buckets aren't pitted against
        # each other (same created_at → bucket-keep keeps one, deletes the
        # other, which is wrong — both copies should survive).
        storage_query = select(BackupArtifact.storage_id).where(
            BackupArtifact.is_deleted == False,
            BackupArtifact.storage_id.is_not(None),
        ).distinct()
        if job_id:
            try:
                job_uuid = uuid.UUID(str(job_id))
            except (ValueError, TypeError):
                logger.error(f"_do_rotation: invalid job_id {job_id!r}")
                return
            run_ids_result = await db.execute(
                select(BackupRun.id).where(BackupRun.job_id == job_uuid)
            )
            run_ids = list(run_ids_result.scalars().all())
            if not run_ids:
                logger.info(f"Rotation: no runs for job {job_id}, nothing to do")
                return
            storage_query = storage_query.where(BackupArtifact.run_id.in_(run_ids))

        storage_ids_result = await db.execute(storage_query)
        storage_ids = [str(s) for s in storage_ids_result.scalars().all()]

        if not storage_ids:
            # Legacy path: no storage_id partitioning available — fall back to
            # global rotation. (Old artifacts before storage_id was added.)
            storage_ids = [None]

        total_kept = 0
        total_deleted = 0
        for sid in storage_ids:
            partial = await apply_rotation(db, policy, job_id, storage_id=sid)
            total_kept += partial["kept"]
            total_deleted += partial["deleted"]

        await db.commit()

        if total_deleted > 0:
            await notify_event(db, "rotation.completed", {
                "policy_name": policy.name,
                "kept": total_kept,
                "deleted": total_deleted,
            })
            await db.commit()

        logger.info(f"Rotation complete: kept={total_kept}, deleted={total_deleted} across {len(storage_ids)} destination(s)")
