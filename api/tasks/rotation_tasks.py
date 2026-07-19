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
        newly_flagged = 0
        skipped: list[str] = []
        for job in jobs:
            overrides = job.retention_overrides or {}
            for dest_id in (job.destination_ids or []):
                dest_str = str(dest_id)
                policy_id = overrides.get(dest_str) or (
                    str(job.retention_id) if job.retention_id else None
                )
                policy = policies.get(str(policy_id)) if policy_id else None
                if not policy:
                    # A pair with no resolvable policy is never rotated and
                    # never purged, so it grows forever. Skipping it silently
                    # (which is what this did) makes that invisible.
                    skipped.append(f"{job.name}/{dest_str}")
                    continue
                res = await apply_rotation(db, policy, str(job.id), storage_id=dest_str)
                rotated += 1
                newly_flagged += res.get("deleted", 0)
        await db.commit()

        if skipped:
            # Loud on purpose: this is a retention hole, not a detail.
            logger.error(
                "enforce_retention: %d job/destination pair(s) have NO resolvable "
                "retention policy and were not rotated or purged. They will grow "
                "without bound: %s",
                len(skipped), ", ".join(skipped[:20]),
            )
            await notify_event(db, "retention.unconfigured", {
                "count": len(skipped),
                "pairs": ", ".join(skipped[:10]),
            })
            await db.commit()

        # Phase 2: reclaim the space. Flags alone were the original bug.
        if not getattr(settings, "purge_enabled", True):
            logger.info(
                "enforce_retention: rotation done (%d job/destination pairs), "
                "purge disabled by config", rotated,
            )
            return {"rotated": rotated, "purge": "disabled"}

        # `x or 3` would turn an explicit 0 back into 3, so a deliberate
        # "no floor" setting would silently not apply. 0 is a legitimate if
        # risky choice; honour it and say so rather than overriding it quietly.
        raw_floor = getattr(settings, "purge_safety_floor", 3)
        floor = 3 if raw_floor is None else int(raw_floor)
        if floor <= 0:
            logger.warning(
                "enforce_retention: purge_safety_floor is %d, so NO minimum number "
                "of backups is protected from deletion by policy.", floor,
            )
        plan = await plan_purge(db, safety_floor=floor)

        if plan["refused"]:
            for r in plan["refused"]:
                logger.warning("enforce_retention: refused %s (%s)", r["job"], r["reason"])

        if not plan["to_delete"]:
            logger.info("enforce_retention: rotation done (%d pairs), nothing to purge", rotated)
            return {"rotated": rotated, "newly_flagged": newly_flagged,
                    "skipped_no_policy": skipped, "deleted": 0, "reclaimed_bytes": 0}

        result = await execute_purge(db, plan)

        # Commit unconditionally: execute_purge mutates rows on the partial-
        # failure path too, and gating the commit on a non-zero delete count
        # would strand those changes.
        await db.commit()

        if result["deleted"] or result["failed"]:
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
        return {"rotated": rotated, "newly_flagged": newly_flagged,
                "skipped_no_policy": skipped, **result}


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
            # There is nothing to rotate for this scope. The old behaviour here
            # was to fall back to storage_id=None, which makes apply_rotation
            # pool every destination's artifacts into one bucket set. That is
            # bug #14 by construction: two copies of the same run compete for
            # the same slot and one gets flagged even though both were wanted.
            #
            # Falling back to a mode known to be wrong is worse than doing
            # nothing, because it produces confident output either way.
            logger.info(
                "Rotation: no artifacts with a storage_id in scope (job_id=%s), "
                "nothing to rotate", job_id,
            )
            return

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
