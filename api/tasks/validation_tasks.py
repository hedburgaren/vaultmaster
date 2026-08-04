"""Celery tasks for backup-restore validation.

Two entry points:
  validate_backup_job_task(job_id, artifact_id?)  manual or post-backup trigger
  scan_validation_candidates()                    beat-scheduled, finds jobs
                                                  whose last validation is older
                                                  than the cooldown, queues them
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from api.tasks.celery_app import celery_app
from api.tasks.backup_tasks import _run_async, get_task_session

logger = logging.getLogger(__name__)

# How often the beat scan runs, and how stale a job's last real validation must
# be before the scan re-queues it. Kept as named values because the correctness
# of the second depends entirely on the first.
#
# The cooldown is 23 hours rather than 24 on purpose. A job validated at
# 23:47:23 was not eligible again until 23:47:23 the next day, and the 23:47:00
# tick missed it by twenty-three seconds. So it fired at the 00:47 tick
# instead, and one tick later again the day after: the whole schedule walked
# forward about an hour per day. Real example, one job across eight days:
# 14:40, 15:40, 16:40, 17:40, 18:40, 19:40, 20:40, 21:47.
#
# An hour of slack absorbs the miss without letting a job come round twice in
# one day. The permitted range is narrow in both directions and is asserted by
# test_validation_schedule_does_not_drift:
#
#   too low  (<= 24 - 2*SCAN)  a job is eligible at the previous tick, so the
#                              schedule drifts earlier instead of later
#   too high (>  24 - SCAN)    the tick can miss the boundary again, which is
#                              the original bug
#
# This holds while a queued validation starts within one scan interval of the
# tick that queued it. A long enough worker backlog would reintroduce drift,
# more slowly; that would be a queue problem, not a scheduling one.
SCAN_INTERVAL_HOURS = 1
VALIDATION_COOLDOWN_HOURS = 23


@celery_app.task(name="api.tasks.validation_tasks.validate_backup_job_task")
def validate_backup_job_task(job_id: str, artifact_id: str | None = None, triggered_by: str = "scheduler"):
    """Run a restore-validation for the given job's most recent (or
    specified) artifact, recording a BackupValidationRun row."""
    _run_async(_validate_job(job_id, artifact_id, triggered_by))


@celery_app.task(name="api.tasks.validation_tasks.scan_validation_candidates")
def scan_validation_candidates():
    """Find every active job whose backup_type is validatable and whose last
    real validation is older than VALIDATION_COOLDOWN_HOURS; queue a
    validation task for each. The effect is one validation per job per day,
    on a stable hour."""
    _run_async(_scan_candidates())


async def _validate_job(job_id: str, artifact_id: str | None, triggered_by: str) -> None:
    from sqlalchemy import select, desc
    from api.models.backup_job import BackupJob
    from api.models.backup_artifact import BackupArtifact
    from api.models.backup_validation_run import BackupValidationRun
    from api.models.server import Server
    from api.services.restore_validator import run_validation

    async with get_task_session() as db:
        result = await db.execute(select(BackupJob).where(BackupJob.id == uuid.UUID(job_id)))
        job = result.scalar_one_or_none()
        if not job:
            logger.error(f"validation: job {job_id} not found")
            return

        result = await db.execute(select(Server).where(Server.id == job.server_id))
        server = result.scalar_one_or_none()

        artifact = None
        if (job.backup_type or "").lower() == "restic":
            pass
        else:
            if artifact_id:
                result = await db.execute(
                    select(BackupArtifact).where(BackupArtifact.id == uuid.UUID(artifact_id))
                )
            else:
                result = await db.execute(
                    select(BackupArtifact)
                    .join(BackupArtifact.run)
                    .where(BackupArtifact.run.has(job_id=job.id))
                    .where(BackupArtifact.is_deleted == False)
                    .order_by(desc(BackupArtifact.created_at))
                    .limit(1)
                )
            artifact = result.scalar_one_or_none()

        run = BackupValidationRun(
            job_id=job.id,
            artifact_id=artifact.id if artifact else None,
            check_type="restore",
            status="running",
            started_at=datetime.now(timezone.utc),
            triggered_by=triggered_by,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        try:
            result_data = await run_validation(job, artifact=artifact, server=server)
            run.status = result_data["status"]
            run.error_message = result_data.get("error")
            run.log_lines = result_data.get("logs", [])
            run.finished_at = datetime.now(timezone.utc)
            if run.started_at and run.finished_at:
                run.duration_seconds = int((run.finished_at - run.started_at).total_seconds())
            await db.commit()
            logger.info(f"validation {run.id} for job {job.name}: {run.status}")

            from api.services.notifier import notify_event
            event = "validation.failed" if run.status == "failed" else (
                "validation.passed" if run.status == "passed" else "validation.skipped"
            )
            await notify_event(db, event, {
                "job_name": job.name,
                "server_name": server.name if server else "",
                "validation_status": run.status,
                "error": run.error_message,
                "duration": run.duration_seconds,
            })
        except Exception as e:
            run.status = "failed"
            run.error_message = f"{type(e).__name__}: {str(e)}"[:1000]
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error(f"validation task crashed for job {job_id}: {e}")
            raise


async def _scan_candidates() -> None:
    from sqlalchemy import select, desc, and_
    from api.models.backup_job import BackupJob
    from api.models.backup_validation_run import BackupValidationRun

    async with get_task_session() as db:
        validatable_types = ("postgresql", "files", "docker_volumes", "restic")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=VALIDATION_COOLDOWN_HOURS)

        result = await db.execute(
            select(BackupJob)
            .where(BackupJob.is_active == True)
            .where(BackupJob.backup_type.in_(validatable_types))
        )
        jobs = result.scalars().all()

        queued = 0
        never_validated = []
        for j in jobs:
            # The cooldown must be driven by the last run that actually
            # validated something. This used to take the latest run of any
            # status, so a "skipped" row (written whenever there was no
            # artifact to check) consumed the whole 24h window and silenced
            # the hourly scan until the next day. Observed in production:
            # 210 skips in one week, and ARC Gruppen Odoo DB never once
            # validated successfully while the scan kept reporting itself
            # as having run.
            result = await db.execute(
                select(BackupValidationRun)
                .where(BackupValidationRun.job_id == j.id)
                .where(BackupValidationRun.status.in_(("passed", "failed")))
                .order_by(desc(BackupValidationRun.created_at))
                .limit(1)
            )
            last_real = result.scalar_one_or_none()
            if last_real and last_real.created_at and last_real.created_at > cutoff:
                continue
            if last_real is None:
                never_validated.append(j.name)
            validate_backup_job_task.delay(str(j.id), None, "scheduler")
            queued += 1
            logger.info(f"validation queued for job {j.name} ({j.id})")

        logger.info(f"validation scan: queued {queued} of {len(jobs)} validatable jobs")

        if never_validated:
            # A job that has never produced a passed or failed validation has
            # never been proven restorable.
            #
            # Deliberately a log line and NOT a notification. This is a standing
            # condition, not an event: it stays true until somebody fixes it, so
            # notifying on it would repeat the same message every hour for the
            # same jobs. That is how the backup.anomaly scan turned into 23
            # Discord messages an hour and trained everyone to ignore the
            # channel, which costs more than the missing alert ever would.
            #
            # Standing conditions belong on the dashboard or in a digest.
            logger.error(
                "validation scan: %d job(s) have NEVER completed a validation "
                "(no passed or failed run on record): %s",
                len(never_validated), ", ".join(never_validated[:20]),
            )
