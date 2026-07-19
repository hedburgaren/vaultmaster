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


@celery_app.task(name="api.tasks.rotation_tasks.enforce_retention")
def enforce_retention():
    """Scheduled retention enforcement: rotate every job, then reclaim space.

    Added 2026-07-19. Before this, retention was never enforced by anything on
    a schedule. Rotation only ran inline after a successful backup of that one
    job, and nothing at all deleted files. Consequences, all of them observed
    in production:

      - A job that stopped running never rotated again. Its artifacts sat
        forever, because the only trigger was its own next successful backup.
      - A policy change was never applied to existing artifacts until each job
        happened to run again.
      - No file was ever deleted, so the archive grew without bound. The oldest
        artifact on disk was 138 days old under a 90-day policy.

    This task closes that loop: it evaluates every job against its current
    policy regardless of whether the job still runs, then physically deletes
    what the policy says should be gone. The guards live in
    api.services.purge (safety floor, refuse-to-empty, recompute from policy
    rather than trusting is_deleted).
    """
    return _run_async(_do_enforce_retention())


async def _do_enforce_retention():
    from sqlalchemy import select

    from api.config import get_settings
    from api.models.backup_job import BackupJob
    from api.models.retention_policy import RetentionPolicy
    from api.services.notifier import notify_event
    from api.services.purge import execute_purge, plan_purge
    from api.services.rotation import apply_rotation

    settings = get_settings()

    async with get_task_session() as db:
        # Phase 1: refresh flags for every job and destination, including jobs
        # that no longer run. Inline rotation only ever covers the job that
        # just backed up.
        jobs = (await db.execute(select(BackupJob))).scalars().all()
        policies = {
            str(p.id): p
            for p in (await db.execute(select(RetentionPolicy))).scalars().all()
        }

        rotated = 0
        for job in jobs:
            overrides = job.retention_overrides or {}
            for dest_id in (job.destination_ids or []):
                dest_str = str(dest_id)
                policy_id = overrides.get(dest_str) or (
                    str(job.retention_id) if job.retention_id else None
                )
                policy = policies.get(str(policy_id)) if policy_id else None
                if not policy:
                    continue
                await apply_rotation(db, policy, str(job.id), storage_id=dest_str)
                rotated += 1
        await db.commit()

        # Phase 2: reclaim the space. Flags alone were the original bug.
        if not getattr(settings, "purge_enabled", True):
            logger.info(
                "enforce_retention: rotation done (%d job/destination pairs), "
                "purge disabled by config", rotated,
            )
            return {"rotated": rotated, "purge": "disabled"}

        floor = int(getattr(settings, "purge_safety_floor", 3) or 3)
        plan = await plan_purge(db, safety_floor=floor)

        if plan["refused"]:
            for r in plan["refused"]:
                logger.warning("enforce_retention: refused %s (%s)", r["job"], r["reason"])

        if not plan["to_delete"]:
            logger.info("enforce_retention: rotation done (%d pairs), nothing to purge", rotated)
            return {"rotated": rotated, "deleted": 0, "reclaimed_bytes": 0}

        result = await execute_purge(db, plan)

        if result["deleted"]:
            await notify_event(db, "retention.purged", {
                "deleted": result["deleted"],
                "reclaimed_gb": round(result["reclaimed_bytes"] / 1e9, 1),
                "failed": result["failed"],
            })
            await db.commit()

        logger.info(
            "enforce_retention: rotated %d pairs, deleted %d artifacts, reclaimed %.1f GB",
            rotated, result["deleted"], result["reclaimed_bytes"] / 1e9,
        )
        return {"rotated": rotated, **result}


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
