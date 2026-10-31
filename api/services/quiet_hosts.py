"""Quiet failures for machines that are expected to be away.

A laptop that is closed in a bag in the evening is unreachable by design, and a
failed backup or an offline alarm for it every evening is noise that teaches
the reader to ignore the alarm channel (Chrille 2026-10-31, plastop).

A server tagged ``intermittent`` is therefore quiet in two places:

- ``server.offline`` never fires for it: being offline is its normal state.
- ``run.failed`` for one of its jobs stays quiet while the job has a
  successful run younger than ``intermittent_grace_hours``. Once the newest
  success is older than that (or the job never succeeded), the failure alarms
  as usual, so a laptop that silently stops backing up is still noticed.

Everything else (success, partial, corrupt artifacts, validations, abandoned
runs) is untouched. The failed run is still recorded and visible in the UI;
only the notification is held back.
"""

from datetime import datetime, timedelta, timezone

QUIET_TAG = "intermittent"


def is_intermittent(server) -> bool:
    tags = getattr(server, "tags", None) or []
    return any(str(t).strip().lower() == QUIET_TAG for t in tags)


def failure_stays_quiet(server, last_success_at, grace_hours, now=None) -> bool:
    """True when a failed run on this server should not notify."""
    if not is_intermittent(server):
        return False
    if last_success_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    if last_success_at.tzinfo is None:
        last_success_at = last_success_at.replace(tzinfo=timezone.utc)
    return now - last_success_at < timedelta(hours=grace_hours)


async def last_success_at(db, job_id):
    """finished_at of the job's newest successful run, or None."""
    from sqlalchemy import select, func
    from api.models.backup_run import BackupRun

    result = await db.execute(
        select(func.max(BackupRun.finished_at)).where(
            BackupRun.job_id == job_id, BackupRun.status == "success"
        )
    )
    return result.scalar_one_or_none()


async def quiet_failure(db, job, server, grace_hours) -> bool:
    if not is_intermittent(server):
        return False
    return failure_stays_quiet(server, await last_success_at(db, job.id), grace_hours)
