import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.backup_artifact import BackupArtifact
from api.models.retention_policy import RetentionPolicy

logger = logging.getLogger(__name__)


def _gfs_configured(policy: RetentionPolicy) -> bool:
    """True when the policy asks for any grandfather-father-son thinning.

    When every keep_* is 0 the policy is pure max-age: keep everything until it
    passes max_age_days. Distinguishing the two is what stops rotation from
    treating "no bucket claimed this" as "delete this".
    """
    return any(
        int(getattr(policy, attr, 0) or 0) > 0
        for attr in ("keep_hourly", "keep_daily", "keep_weekly", "keep_monthly", "keep_yearly")
    )


def _assign_bucket(dt: datetime) -> dict:
    """Assign time buckets for GFS rotation."""
    return {
        "year": dt.year,
        "month": (dt.year, dt.month),
        "week": dt.isocalendar()[:2],  # (year, week)
        "day": dt.date(),
        "hour": (dt.date(), dt.hour),
    }


async def apply_rotation(db: AsyncSession, policy: RetentionPolicy, job_id: str | None = None, storage_id: str | None = None) -> dict:
    """Apply GFS rotation: keep configured number per time bucket, mark rest as deleted.

    Bug #13: explicit UUID cast on job_id (BackupRun.job_id is UUID, str equality
    silently returns no rows on some dialects). Tom run_ids list short-circuits
    så vi inte producerar `IN ()` SQL.

    Bug #14: when job has multiple destinations (storage A + storage B), two
    artifacts from the SAME run share created_at — bucket-keep keeps one and
    rotation marks the other deleted, even though the user wanted both kept.
    Caller is now expected to pass storage_id and call once per destination.
    """
    import uuid as _uuid

    query = select(BackupArtifact).where(BackupArtifact.is_deleted == False)
    if job_id:
        from api.models.backup_run import BackupRun
        try:
            job_uuid = _uuid.UUID(str(job_id))
        except (ValueError, AttributeError, TypeError) as exc:
            logger.error(f"apply_rotation: invalid job_id {job_id!r}: {exc}")
            return {"kept": 0, "deleted": 0, "artifacts_deleted": []}
        run_ids_result = await db.execute(select(BackupRun.id).where(BackupRun.job_id == job_uuid))
        run_ids = list(run_ids_result.scalars().all())
        if not run_ids:
            # No runs for this job → nothing to rotate. Avoid `IN ()` SQL error.
            return {"kept": 0, "deleted": 0, "artifacts_deleted": []}
        query = query.where(BackupArtifact.run_id.in_(run_ids))
    if storage_id:
        try:
            storage_uuid = _uuid.UUID(str(storage_id))
        except (ValueError, AttributeError, TypeError) as exc:
            logger.error(f"apply_rotation: invalid storage_id {storage_id!r}: {exc}")
            return {"kept": 0, "deleted": 0, "artifacts_deleted": []}
        query = query.where(BackupArtifact.storage_id == storage_uuid)

    result = await db.execute(query.order_by(BackupArtifact.created_at.desc()))
    artifacts = result.scalars().all()

    if not artifacts:
        return {"kept": 0, "deleted": 0, "artifacts_deleted": []}

    # Max age filter
    now = datetime.now(timezone.utc)
    max_age_cutoff = now - timedelta(days=policy.max_age_days) if policy.max_age_days > 0 else None

    # Assign buckets
    buckets = {
        "hourly": defaultdict(list),
        "daily": defaultdict(list),
        "weekly": defaultdict(list),
        "monthly": defaultdict(list),
        "yearly": defaultdict(list),
    }

    for artifact in artifacts:
        b = _assign_bucket(artifact.created_at)
        buckets["hourly"][b["hour"]].append(artifact)
        buckets["daily"][b["day"]].append(artifact)
        buckets["weekly"][b["week"]].append(artifact)
        buckets["monthly"][b["month"]].append(artifact)
        buckets["yearly"][b["year"]].append(artifact)

    # Determine which to keep
    keep_ids = set()

    def keep_from_bucket(bucket_dict: dict, keep_count: int):
        sorted_keys = sorted(bucket_dict.keys(), reverse=True)
        for key in sorted_keys[:keep_count]:
            # Keep the newest in each bucket
            if bucket_dict[key]:
                keep_ids.add(bucket_dict[key][0].id)

    keep_from_bucket(buckets["hourly"], policy.keep_hourly)
    keep_from_bucket(buckets["daily"], policy.keep_daily)
    keep_from_bucket(buckets["weekly"], policy.keep_weekly)
    keep_from_bucket(buckets["monthly"], policy.keep_monthly)
    keep_from_bucket(buckets["yearly"], policy.keep_yearly)

    gfs_configured = _gfs_configured(policy)

    # Mark deletions
    #
    # Bug (found 2026-07-19): this used to read "if artifact.id not in keep_ids:
    # should_delete = True", i.e. anything no GFS bucket claimed was deleted.
    # For a pure-max-age policy (all keep_* = 0, which is what all 47 jobs
    # actually use) keep_ids is always empty, so every artifact was marked
    # deleted 1 to 15 seconds after it was created, including the one the run
    # had just produced. 8305 of 8311 artifacts were flagged deleted while the
    # files sat on disk, which hid real backups from the restore path.
    #
    # Correct semantics: max_age is the sole criterion when no GFS buckets are
    # configured. GFS thinning only applies when the policy actually asks for
    # it. A policy that specifies neither keeps everything, which is the safe
    # direction to fail.
    deleted = []
    for artifact in artifacts:
        if artifact.id in keep_ids:
            continue

        too_old = bool(max_age_cutoff and artifact.created_at < max_age_cutoff)
        should_delete = gfs_configured or too_old

        if should_delete:
            artifact.is_deleted = True
            artifact.deleted_at = now
            deleted.append(str(artifact.id))

    await db.flush()

    logger.info(f"Rotation applied: kept {len(keep_ids)}, deleted {len(deleted)}")
    return {"kept": len(keep_ids), "deleted": len(deleted), "artifacts_deleted": deleted}


async def preview_rotation(db: AsyncSession, policy: RetentionPolicy, job_id: str | None = None) -> dict:
    """Preview what rotation would do without actually deleting."""
    query = select(BackupArtifact).where(BackupArtifact.is_deleted == False)
    result = await db.execute(query.order_by(BackupArtifact.created_at.desc()))
    artifacts = result.scalars().all()

    now = datetime.now(timezone.utc)
    max_age_cutoff = now - timedelta(days=policy.max_age_days) if policy.max_age_days > 0 else None

    buckets = {
        "hourly": defaultdict(list),
        "daily": defaultdict(list),
        "weekly": defaultdict(list),
        "monthly": defaultdict(list),
        "yearly": defaultdict(list),
    }

    for artifact in artifacts:
        b = _assign_bucket(artifact.created_at)
        buckets["hourly"][b["hour"]].append(artifact)
        buckets["daily"][b["day"]].append(artifact)
        buckets["weekly"][b["week"]].append(artifact)
        buckets["monthly"][b["month"]].append(artifact)
        buckets["yearly"][b["year"]].append(artifact)

    keep_ids = set()

    def keep_from_bucket(bucket_dict, keep_count):
        sorted_keys = sorted(bucket_dict.keys(), reverse=True)
        for key in sorted_keys[:keep_count]:
            if bucket_dict[key]:
                keep_ids.add(bucket_dict[key][0].id)

    keep_from_bucket(buckets["hourly"], policy.keep_hourly)
    keep_from_bucket(buckets["daily"], policy.keep_daily)
    keep_from_bucket(buckets["weekly"], policy.keep_weekly)
    keep_from_bucket(buckets["monthly"], policy.keep_monthly)
    keep_from_bucket(buckets["yearly"], policy.keep_yearly)

    gfs_configured = _gfs_configured(policy)

    # Must mirror apply_rotation exactly. A preview that disagrees with the
    # real thing is worse than no preview, since it is used to sanity-check
    # policy changes before they run.
    would_delete = []
    for artifact in artifacts:
        if artifact.id in keep_ids:
            continue

        too_old = bool(max_age_cutoff and artifact.created_at < max_age_cutoff)
        if gfs_configured or too_old:
            would_delete.append({
                "id": str(artifact.id),
                "filename": artifact.filename,
                "created_at": artifact.created_at.isoformat(),
                "size_bytes": artifact.size_bytes,
                "reason": "max_age" if too_old else "rotation",
            })

    return {
        "total_artifacts": len(artifacts),
        "would_keep": len(keep_ids),
        "would_delete": len(would_delete),
        "artifacts_to_delete": would_delete,
    }
