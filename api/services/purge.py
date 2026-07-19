"""Physical deletion of expired backup artifacts.

Until 2026-07-19 nothing in VaultMaster ever deleted a file. Rotation set
`is_deleted` in the database and stopped there, so retention was enforced on
paper and nowhere else. The archive reached 3.1 TB locally and 2.96 TiB of a
5 TiB Google Drive quota, growing 62 GB per day per destination.

This module is the part that actually reclaims space, which makes it the most
dangerous code in the project. Three rules follow from that:

1. **Never trust `is_deleted`.** Expiry is recomputed from the retention policy
   on every run. The flag is corrupt for 8305 historical rows thanks to the
   rotation bug fixed the same day, and deleting files based on it would
   destroy live backups. The flag is an output of this module, never an input.

2. **Keep a floor.** The newest `safety_floor` artifacts per (job, destination)
   are never deleted, whatever the policy says. A policy edited to `max_age_days
   = 1` should thin history, not leave a job with nothing restorable.

3. **Never empty a job.** If applying the policy would delete every artifact a
   job has at a destination, the whole batch for that pair is refused. That is a
   misconfiguration, not a retention outcome.

Deletion order is file first, then flag. If the file delete fails the row keeps
its previous state and the next run retries. The reverse order could mark a row
deleted while the file lingers forever, which is how the archive grew in the
first place.
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from api.models.backup_artifact import BackupArtifact
from api.models.backup_job import BackupJob
from api.models.backup_run import BackupRun
from api.models.retention_policy import RetentionPolicy
from api.models.storage_destination import StorageDestination
from api.services.rclone_client import delete_file_from_storage
from api.services.rotation import select_expired

logger = logging.getLogger(__name__)

# Newest N artifacts per (job, destination) are never purged.
DEFAULT_SAFETY_FLOOR = 3


def purge_decision(live_count: int, live_expired: int, total: int) -> tuple[bool, str]:
    """Decide whether a (job, destination) group may be purged at all.

    Three cases, and the middle one is the whole reason this exists:

      total == 0            nothing recorded, nothing to protect, proceed
      live_count == 0       rows exist but none are live. That is not an empty
                            group, it is a group whose every row claims to be
                            deleted, which is exactly the corruption this module
                            was written to survive (8305 rows once claimed that
                            while the files sat on disk). Refuse.
      live_expired >= live  purging would remove every surviving copy. Refuse.

    An earlier version wrote `if live_count and len(live_expired) >= live_count`,
    so the zero case short-circuited the guard entirely and purge proceeded to
    delete the only files that were actually there. Zero is an anomaly to stop
    on, never a licence.
    """
    if total == 0:
        return True, ""
    if live_count == 0:
        return False, (
            f"all {total} artifact(s) are flagged deleted and none are live. "
            "Refusing to purge: this is the flag-corruption state, and the files "
            "may still exist. Reconcile the flags first "
            "(scripts/repair_rotation_flags.py)."
        )
    if live_expired >= live_count:
        return False, f"would delete all {live_count} surviving artifact(s)"
    return True, ""


def select_floor(artifacts, safety_floor: int) -> list:
    """Return the newest `safety_floor` artifacts that still exist.

    The floor exists to guarantee a job never drops below N restorable copies,
    whatever the policy says. Taking the newest N rows from the raw list (which
    is what this did until an adversarial audit caught it) counts rows already
    flagged is_deleted, whose files are gone. A job whose newest three rows are
    deleted ghosts then has a floor made entirely of nothing, and its oldest
    surviving backup becomes a deletion candidate.

    That was not hypothetical: at the time this was written, ten job/destination
    pairs had all three of their newest artifacts flagged deleted.

    Note the direction of the trade. Using is_deleted here only ever makes the
    floor reach FURTHER down the list and protect MORE real backups, which is
    why it does not conflict with the rule that the delete decision itself is
    recomputed from policy and never read from that flag.
    """
    live = [a for a in artifacts if not getattr(a, "is_deleted", False)]
    live.sort(key=lambda a: a.created_at, reverse=True)
    return live[:safety_floor]


async def plan_purge(db, safety_floor: int = DEFAULT_SAFETY_FLOOR) -> dict:
    """Work out what would be deleted, without touching anything.

    Returns a plan dict. `plan_purge` is pure: callers can show it, log it, or
    hand it to execute_purge. Both the dry-run report and the real run go
    through this same function so they cannot disagree.
    """
    now = datetime.now(timezone.utc)

    # deleted_at, not is_deleted. Only execute_purge sets deleted_at, and only
    # after the backend confirmed the file is gone, so it means "physically
    # purged by us". is_deleted is the weaker signal: rotation sets it from
    # policy alone, which is why 8305 historical rows carried it without any
    # file ever having been removed.
    #
    # Without this filter every already-purged row was re-planned on every run.
    # delete_file_from_storage answers "already absent" with ok=True, so the
    # same artifacts were counted as freshly deleted and their bytes as freshly
    # reclaimed, every single day, forever. The daily retention.purged notice
    # reported the same GB over and over for space that was released once.
    rows = (await db.execute(
        select(BackupArtifact, BackupJob)
        .join(BackupRun, BackupRun.id == BackupArtifact.run_id)
        .join(BackupJob, BackupJob.id == BackupRun.job_id)
        .where(BackupArtifact.deleted_at.is_(None))
    )).all()

    all_policies = {
        str(p.id): p
        for p in (await db.execute(select(RetentionPolicy))).scalars().all()
    }

    # Group by (job, destination). Retention is resolved per destination, not
    # per job: BackupJob.retention_overrides is a {dest_id: policy_id} map that
    # lets a cheap, roomy local disk keep more history than a metered cloud
    # quota. Ignoring it here would clean the cloud copy on the local disk's
    # generous schedule, which is the destination that cannot afford it.
    grouped: dict[tuple, list] = defaultdict(list)
    policies: dict[tuple, RetentionPolicy] = {}
    job_names: dict[tuple, str] = {}
    for artifact, job in rows:
        dest_str = str(artifact.storage_id)
        key = (str(job.id), dest_str)

        overrides = job.retention_overrides or {}
        policy_id = overrides.get(dest_str) or (str(job.retention_id) if job.retention_id else None)
        policy = all_policies.get(str(policy_id)) if policy_id else None
        if not policy:
            # No resolvable policy means no retention instruction. Keeping the
            # artifact is the only safe reading.
            continue

        grouped[key].append(artifact)
        policies[key] = policy
        job_names[key] = job.name

    to_delete = []
    refused = []
    kept_by_floor = 0

    for key, artifacts in grouped.items():
        policy = policies[key]
        artifacts.sort(key=lambda a: a.created_at, reverse=True)

        # Same decision function rotation uses, so the flag and the file can
        # never disagree. Recomputed from the policy, never read from
        # is_deleted, which is corrupt for 8305 historical rows.
        expired_ids = select_expired(artifacts, policy, now)

        floor = select_floor(artifacts, safety_floor)
        floor_ids = {a.id for a in floor}
        candidates = [a for a in artifacts if a.id not in floor_ids]
        kept_by_floor += len(floor)

        expired = [a for a in candidates if a.id in expired_ids]
        if not expired:
            continue

        # Rule 3, delegated to purge_decision so the zero-live case cannot be
        # short-circuited by a falsy count again. Both sides count live rows
        # only: an earlier version compared expired-including-ghosts against
        # live, and refused to purge jobs that were in no danger at all.
        live_count = sum(1 for a in artifacts if not getattr(a, "is_deleted", False))
        live_expired = sum(1 for a in expired if not getattr(a, "is_deleted", False))
        may_purge, why = purge_decision(live_count, live_expired, len(artifacts))
        if not may_purge:
            logger.warning("purge: refusing %s/%s: %s", job_names[key], key[1], why)
            refused.append({
                "job": job_names[key],
                "storage_id": key[1],
                "reason": why,
            })
            continue

        for a in expired:
            to_delete.append({
                "artifact_id": str(a.id),
                "job": job_names[key],
                "storage_id": str(a.storage_id),
                "filename": a.filename,
                "remote_path": a.remote_path,
                "size_bytes": a.size_bytes or 0,
                "created_at": a.created_at,
                "age_days": (now - a.created_at).days,
                "max_age_days": int(getattr(policy, "max_age_days", 0) or 0),
            })

    return {
        "total_artifacts": len(rows),
        "to_delete": to_delete,
        "delete_count": len(to_delete),
        "reclaim_bytes": sum(d["size_bytes"] for d in to_delete),
        "kept_by_safety_floor": kept_by_floor,
        "refused": refused,
        "safety_floor": safety_floor,
    }


async def execute_purge(db, plan: dict, limit: int | None = None) -> dict:
    """Delete the files in `plan`, then flag the rows.

    File first, then flag: a failed delete leaves the row untouched so the next
    run retries it. Flagging first would strand the file forever.
    """
    dests = {
        str(d.id): d
        for d in (await db.execute(select(StorageDestination))).scalars().all()
    }

    deleted = 0
    failed = 0
    already_gone = 0
    reclaimed = 0
    errors = []

    items = plan["to_delete"]
    if limit is not None:
        items = items[:limit]

    for item in items:
        dest = dests.get(item["storage_id"])
        if not dest:
            failed += 1
            errors.append(f"{item['filename']}: unknown destination {item['storage_id']}")
            continue

        ok, msg = await delete_file_from_storage(dest, item["remote_path"])
        if not ok:
            failed += 1
            errors.append(f"{item['filename']}: {msg}")
            logger.warning("purge: %s", msg)
            continue

        # Explicit UUID cast. plan_purge stores ids as str, and comparing a str
        # against a UUID column silently matches nothing on some dialects.
        # rotation.py already documents this as bug #13; it was reintroduced
        # here and caught by an adversarial audit. The consequence was the exact
        # defect this module is written to prevent: the file gets deleted, the
        # row is never flagged, and the counters report the deletion anyway.
        try:
            artifact_uuid = uuid.UUID(str(item["artifact_id"]))
        except (ValueError, TypeError, AttributeError):
            failed += 1
            errors.append(f"{item['filename']}: unparseable artifact id {item['artifact_id']!r}")
            continue

        artifact = (await db.execute(
            select(BackupArtifact).where(BackupArtifact.id == artifact_uuid)
        )).scalar_one_or_none()

        if artifact is None:
            # The file is gone but we cannot record that. Count it as a failure
            # so the number never claims more than was actually reconciled.
            failed += 1
            errors.append(
                f"{item['filename']}: file deleted but artifact row "
                f"{item['artifact_id']} not found, flag NOT set"
            )
            continue

        artifact.is_deleted = True
        artifact.deleted_at = datetime.now(timezone.utc)

        # delete_file_from_storage answers ok=True both for "I removed it" and
        # for "it was not there". Reconciling the row is right either way, but
        # only the first case freed any space. Counting the second inflates
        # reclaimed_bytes with bytes that were released by some earlier run,
        # or never existed.
        if msg.startswith("already absent"):
            already_gone += 1
        else:
            deleted += 1
            reclaimed += item["size_bytes"]

    await db.commit()

    logger.info(
        "purge: deleted %d artifacts (%.1f GB reclaimed), %d were already gone, %d failed",
        deleted, reclaimed / 1e9, already_gone, failed,
    )
    return {
        "deleted": deleted,
        "already_gone": already_gone,
        "failed": failed,
        "reclaimed_bytes": reclaimed,
        "errors": errors[:20],
    }
