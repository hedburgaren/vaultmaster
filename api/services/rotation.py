import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.backup_artifact import BackupArtifact
from api.models.retention_policy import RetentionPolicy

logger = logging.getLogger(__name__)


def _assign_bucket(dt: datetime) -> dict:
    """Assign time buckets for GFS rotation."""
    return {
        "year": dt.year,
        "month": (dt.year, dt.month),
        "week": dt.isocalendar()[:2],  # (year, week)
        "day": dt.date(),
        "hour": (dt.date(), dt.hour),
    }


async def apply_rotation(db: AsyncSession, policy: RetentionPolicy, job_id: str | None = None) -> dict:
    """Apply GFS rotation: keep configured number per time bucket, mark rest as deleted."""
    query = select(BackupArtifact).where(BackupArtifact.is_deleted == False)
    if job_id:
        from api.models.backup_run import BackupRun
        run_ids = await db.execute(select(BackupRun.id).where(BackupRun.job_id == job_id))
        query = query.where(BackupArtifact.run_id.in_([r for r in run_ids.scalars().all()]))

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

    # Mark deletions
    deleted = []
    for artifact in artifacts:
        should_delete = False
        if artifact.id not in keep_ids:
            should_delete = True
        if max_age_cutoff and artifact.created_at < max_age_cutoff:
            should_delete = True

        if should_delete and artifact.id not in keep_ids:
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

    would_delete = []
    for artifact in artifacts:
        if artifact.id not in keep_ids:
            would_delete.append({
                "id": str(artifact.id),
                "filename": artifact.filename,
                "created_at": artifact.created_at.isoformat(),
                "size_bytes": artifact.size_bytes,
                "reason": "max_age" if max_age_cutoff and artifact.created_at < max_age_cutoff else "rotation",
            })

    return {
        "total_artifacts": len(artifacts),
        "would_keep": len(keep_ids),
        "would_delete": len(would_delete),
        "artifacts_to_delete": would_delete,
    }
