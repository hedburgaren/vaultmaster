"""Reconcile is_deleted flags with what retention policy actually says.

Background: until 2026-07-19 rotation treated "no GFS bucket claimed this" as
"delete this". Every job ran a pure-max-age policy (all keep_* = 0), so the
keep set was always empty and every artifact was flagged deleted seconds after
it was written. Roughly 8300 rows were marked deleted while the files sat
untouched on disk.

Nothing ever read those flags to delete files, so no data was lost. The harm is
that restore and restore-validation filter on `is_deleted == False`, so real,
restorable backups were invisible to the only paths that would use them. That
is why 2396 validation runs reported "no artifact to validate".

Rotation only ever sets the flag True, never back to False, so it cannot
self-heal. This script does the one-time reconciliation.

It resolves policy the same way rotation and purge do, honouring
retention_overrides so each destination is judged by its own policy, and it
uses the same select_expired() decision function. Being wrong in the other
direction matters: un-flagging a row whose file is gone would advertise a
backup that cannot be restored, which is worse than hiding one that can. So a
row is only un-flagged when its file is confirmed present.

Usage:
    python -m scripts.repair_rotation_flags            # dry run
    python -m scripts.repair_rotation_flags --apply
"""

import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select, text

from api.models.backup_artifact import BackupArtifact
from api.models.backup_job import BackupJob
from api.models.backup_run import BackupRun
from api.models.retention_policy import RetentionPolicy
from api.models.storage_destination import StorageDestination
from api.services.rclone_client import _build_backend, _run_rclone, normalize_stored_path
from api.services.rotation import select_expired
from api.tasks.backup_tasks import get_task_session


async def remote_file_index(dest) -> set[str]:
    """One listing of a remote destination, as a set of basenames.

    One call instead of one existence check per artifact. Basenames are enough:
    artifact filenames carry a timestamp and are unique per job.
    """
    remote, flags = _build_backend(dest)
    base = remote.split("/")[0]
    if not base.endswith(":"):
        base += ":"
    code, out, err = await _run_rclone(
        ["lsjson", base, "--recursive", "--files-only"] + flags, timeout=900
    )
    if code != 0:
        raise RuntimeError(f"could not list {dest.name}: {(err or '')[:200]}")
    return {os.path.basename(i["Path"]) for i in json.loads(out or "[]")}


async def main(apply: bool) -> int:
    now = datetime.now(timezone.utc)

    async with get_task_session() as db:
        dests = {
            str(d.id): d
            for d in (await db.execute(select(StorageDestination))).scalars().all()
        }
        policies = {
            str(p.id): p
            for p in (await db.execute(select(RetentionPolicy))).scalars().all()
        }
        rows = (await db.execute(
            select(BackupArtifact, BackupJob)
            .join(BackupRun, BackupRun.id == BackupArtifact.run_id)
            .join(BackupJob, BackupJob.id == BackupRun.job_id)
        )).all()

        grouped = defaultdict(list)
        pol_for = {}
        for artifact, job in rows:
            ds = str(artifact.storage_id)
            key = (str(job.id), ds)
            overrides = job.retention_overrides or {}
            pid = overrides.get(ds) or (str(job.retention_id) if job.retention_id else None)
            policy = policies.get(str(pid)) if pid else None
            if not policy:
                continue
            grouped[key].append(artifact)
            pol_for[key] = policy

        # Build remote listings once per non-local destination.
        remote_index = {}
        for did, d in dests.items():
            if d.backend == "local":
                continue
            try:
                remote_index[did] = await remote_file_index(d)
                print(f"listade {d.name}: {len(remote_index[did])} filer")
            except RuntimeError as e:
                print(f"VARNING: {e}")
                print(f"  hoppar over {d.name}, ror inga rader dar")

        stats = {"retain": 0, "unflag": 0, "missing": 0, "unlistable": 0, "already_ok": 0}
        to_unflag = []

        for key, artifacts in grouped.items():
            policy = pol_for[key]
            expired = select_expired(artifacts, policy, now)
            dest = dests.get(key[1])

            for a in artifacts:
                if a.id in expired:
                    continue  # policy says gone; purge handles the file
                stats["retain"] += 1
                if not a.is_deleted:
                    stats["already_ok"] += 1
                    continue

                # Flagged deleted but policy says retain. Only trust it if the
                # file is really there.
                if dest is None:
                    stats["unlistable"] += 1
                    continue
                if dest.backend == "local":
                    present = os.path.isfile(normalize_stored_path(a.remote_path or ""))
                else:
                    idx = remote_index.get(str(dest.id))
                    if idx is None:
                        stats["unlistable"] += 1
                        continue
                    present = os.path.basename(
                        normalize_stored_path(a.remote_path or "")
                    ) in idx

                if present:
                    stats["unflag"] += 1
                    to_unflag.append(a.id)
                else:
                    stats["missing"] += 1

        print()
        print(f"Artefakter som policyn behaller : {stats['retain']}")
        print(f"  redan korrekt oflaggade       : {stats['already_ok']}")
        print(f"  ATERSTALLS (fil finns)        : {stats['unflag']}")
        print(f"  fil saknas, lamnas flaggade   : {stats['missing']}")
        print(f"  kunde ej verifieras           : {stats['unlistable']}")

        if not apply:
            print()
            print("DRY RUN. Inget skrivet. Kor med --apply.")
            return 0
        if not to_unflag:
            print()
            print("Inget att aterstalla.")
            return 0

        for i in range(0, len(to_unflag), 500):
            await db.execute(
                text("UPDATE backup_artifact SET is_deleted=false, deleted_at=NULL "
                     "WHERE id = ANY(:ids)"),
                {"ids": to_unflag[i:i + 500]},
            )
        await db.commit()
        print()
        print(f"KLART. {len(to_unflag)} artefakter aterstallda.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(apply="--apply" in sys.argv)))
