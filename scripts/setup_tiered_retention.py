"""Configure per-destination retention: granular locally, sparse but long offsite.

Rationale (2026-07-19): both destinations ran the same 90-day keep-everything
policy, which works out to 5.45 TiB per destination against a 5.00 TiB Google
Drive quota. Drive was ~34 days from full.

The fix is not "make Drive stingier". The two destinations answer different
questions and should be shaped differently:

  local   fast restore of recent mistakes. Wants every run, short reach.
          19 TB disk, so granularity is nearly free here.

  Drive   the only offsite copy. If the host is gone, this is everything that
          is left. Wants long reach, does not need four copies per day.
          5 TiB metered, so density is expensive here.

Shaping them this way gives 12 months of disaster-recovery reach instead of
today's 90 days, while using about a quarter of the space.

Mechanism: BackupJob.retention_overrides is a {dest_id: policy_id} map that has
existed all along and was never populated. rotation and purge both resolve
policy through it.

Usage:
    python -m scripts.setup_tiered_retention           # dry run
    python -m scripts.setup_tiered_retention --apply
"""

import asyncio
import sys

from sqlalchemy import select

from api.models.backup_job import BackupJob
from api.models.retention_policy import RetentionPolicy
from api.models.storage_destination import StorageDestination
from api.tasks.backup_tasks import get_task_session

LOCAL_POLICY = {
    "name": "Lokalt: 30d granulart",
    "keep_hourly": 0,
    "keep_daily": 0,
    "keep_weekly": 0,
    "keep_monthly": 0,
    "keep_yearly": 0,
    "max_age_days": 30,
}

# GFS: every keep_* > 0 makes rotation thin anything no bucket claims, so this
# keeps 7 daily + 4 weekly + 12 monthly restore points and drops the rest.
# max_age_days is a backstop only; the buckets do the real work.
DRIVE_POLICY = {
    "name": "Drive: GFS 7d+4w+12m",
    "keep_hourly": 0,
    "keep_daily": 7,
    "keep_weekly": 4,
    "keep_monthly": 12,
    "keep_yearly": 0,
    "max_age_days": 400,
}


async def upsert_policy(db, spec: dict) -> RetentionPolicy:
    existing = (await db.execute(
        select(RetentionPolicy).where(RetentionPolicy.name == spec["name"])
    )).scalar_one_or_none()
    if existing:
        for k, v in spec.items():
            setattr(existing, k, v)
        return existing
    import uuid as _uuid
    policy = RetentionPolicy(id=_uuid.uuid4(), **spec)
    db.add(policy)
    await db.flush()
    return policy


async def main(apply: bool) -> int:
    async with get_task_session() as db:
        dests = (await db.execute(select(StorageDestination))).scalars().all()
        local = next((d for d in dests if d.backend == "local"), None)
        drive = next((d for d in dests if d.backend != "local"), None)
        if not local or not drive:
            print("Hittade inte bada destinationerna, avbryter.")
            return 1

        print(f"Lokal destination : {local.name} ({local.id})")
        print(f"Offsite           : {drive.name} ({drive.id})")
        print()
        for label, spec in (("LOKALT", LOCAL_POLICY), ("DRIVE", DRIVE_POLICY)):
            print(f"{label}: {spec['name']}")
            print(f"  hourly={spec['keep_hourly']} daily={spec['keep_daily']} "
                  f"weekly={spec['keep_weekly']} monthly={spec['keep_monthly']} "
                  f"yearly={spec['keep_yearly']} max_age={spec['max_age_days']}d")
        print()

        jobs = (await db.execute(select(BackupJob))).scalars().all()
        print(f"Jobb som far ny retention: {len(jobs)}")

        if not apply:
            print()
            print("DRY RUN. Inget skrivet. Kor med --apply.")
            return 0

        local_policy = await upsert_policy(db, LOCAL_POLICY)
        drive_policy = await upsert_policy(db, DRIVE_POLICY)

        for job in jobs:
            job.retention_id = local_policy.id
            overrides = dict(job.retention_overrides or {})
            overrides[str(drive.id)] = str(drive_policy.id)
            # Reassign rather than mutate: SQLAlchemy does not track in-place
            # edits to a JSONB dict, so mutating would silently persist nothing.
            job.retention_overrides = overrides

        await db.commit()
        print()
        print(f"KLART. {len(jobs)} jobb uppdaterade.")
        print(f"  retention_id        -> {local_policy.name}")
        print(f"  overrides[{drive.name}] -> {drive_policy.name}")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(apply="--apply" in sys.argv)))
