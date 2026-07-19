"""One-time repair for artifacts wrongly flagged as deleted.

Background: until 2026-07-19 rotation treated "no GFS bucket claimed this
artifact" as "delete this artifact". Every job here uses a pure-max-age policy
(all keep_* = 0), so keep_ids was always empty and every artifact was flagged
deleted 1 to 15 seconds after it was written. 8305 of 8311 rows were marked
deleted while the files sat untouched on disk.

The rotation code is fixed, but it only ever sets is_deleted True, never back to
False, so it does not self-heal. This script does that one repair.

Deliberately conservative. A row is only un-deleted when ALL of:
  - it is inside its own job's retention window (created_at >= now - max_age)
  - the artifact file still exists on disk (local destinations only)

Rows past max_age stay deleted: those are correctly expired. Rows on remote
destinations are reported but not touched, since existence cannot be confirmed
cheaply and claiming a backup exists when it does not is the exact class of bug
this whole change is about.

Usage:
    python -m scripts.repair_rotation_flags            # dry run, default
    python -m scripts.repair_rotation_flags --apply    # write changes
"""

import asyncio
import os
import sys

from sqlalchemy import select, text

from api.services.rclone_client import normalize_stored_path
from api.tasks.backup_tasks import get_task_session


QUERY = text("""
    SELECT a.id,
           a.remote_path,
           a.filename,
           sd.backend,
           (a.created_at >= now() - (rp.max_age_days || ' days')::interval) AS inside_window
    FROM backup_artifact a
    JOIN backup_run r          ON r.id  = a.run_id
    JOIN backup_job j          ON j.id  = r.job_id
    JOIN retention_policy rp   ON rp.id = j.retention_id
    JOIN storage_destination sd ON sd.id = a.storage_id
    WHERE a.is_deleted = true
""")


async def main(apply: bool) -> int:
    stats = {
        "total_flagged": 0,
        "outside_window": 0,
        "remote_skipped": 0,
        "file_missing": 0,
        "to_restore": 0,
    }
    restore_ids = []

    async with get_task_session() as db:
        rows = (await db.execute(QUERY)).all()
        stats["total_flagged"] = len(rows)

        for art_id, remote_path, filename, backend, inside_window in rows:
            if not inside_window:
                stats["outside_window"] += 1
                continue
            if backend != "local":
                stats["remote_skipped"] += 1
                continue

            path = normalize_stored_path(remote_path or "")
            if not path or not os.path.isfile(path):
                stats["file_missing"] += 1
                continue

            stats["to_restore"] += 1
            restore_ids.append(art_id)

        print("Artefakter flaggade is_deleted :", stats["total_flagged"])
        print("  utanfor retention-fonstret   :", stats["outside_window"], "(korrekt raderade, ror ej)")
        print("  remote destination           :", stats["remote_skipped"], "(kan ej verifieras billigt, ror ej)")
        print("  fil saknas pa disk           :", stats["file_missing"], "(ror ej)")
        print("  ATERSTALLS                   :", stats["to_restore"])

        if not apply:
            print()
            print("DRY RUN. Inget skrivet. Kor med --apply for att genomfora.")
            return 0

        if not restore_ids:
            print()
            print("Inget att aterstalla.")
            return 0

        CHUNK = 500
        for i in range(0, len(restore_ids), CHUNK):
            batch = restore_ids[i:i + CHUNK]
            await db.execute(
                text(
                    "UPDATE backup_artifact "
                    "SET is_deleted = false, deleted_at = NULL "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": batch},
            )
        await db.commit()
        print()
        print(f"KLART. {len(restore_ids)} artefakter aterstallda.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(apply="--apply" in sys.argv)))
