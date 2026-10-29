"""Reclaim disk and Drive space by deleting expired backup artifacts.

Dry run by default. See api/services/purge.py for the safety rules.

Usage:
    python -m scripts.purge_expired                  # dry run
    python -m scripts.purge_expired --apply          # delete
    python -m scripts.purge_expired --apply --limit 100
    python -m scripts.purge_expired --floor 5        # keep 5 newest per job+dest
"""

import asyncio
import sys
from collections import defaultdict

from api.services.purge import DEFAULT_SAFETY_FLOOR, execute_purge, plan_purge
from api.tasks.backup_tasks import get_task_session


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


def _arg(name: str, default):
    if name in sys.argv:
        return type(default)(sys.argv[sys.argv.index(name) + 1])
    return default


async def main() -> int:
    apply = "--apply" in sys.argv
    floor = _arg("--floor", DEFAULT_SAFETY_FLOOR)
    limit = _arg("--limit", 0) or None

    async with get_task_session() as db:
        plan = await plan_purge(db, safety_floor=floor)

        print(f"Artefakter totalt      : {plan['total_artifacts']}")
        print(f"Skyddade av golvet     : {plan['kept_by_safety_floor']} (nyaste {plan['safety_floor']} per jobb+destination)")
        print(f"Att radera             : {plan['delete_count']}")
        print(f"Utrymme att aterta     : {_gb(plan['reclaim_bytes'])}")

        if plan["refused"]:
            print()
            print("VAGRADE (skulle tomma jobbet helt):")
            for r in plan["refused"]:
                print(f"  {r['job']}: {r['reason']}")

        if plan["to_delete"]:
            per_job = defaultdict(lambda: [0, 0])
            for d in plan["to_delete"]:
                per_job[d["job"]][0] += 1
                per_job[d["job"]][1] += d["size_bytes"]
            print()
            print("Per jobb:")
            for job, (n, size) in sorted(per_job.items(), key=lambda kv: -kv[1][1])[:15]:
                print(f"  {job:32} {n:5} st  {_gb(size):>10}")

            oldest = min(d["age_days"] for d in plan["to_delete"])
            print()
            print(f"Yngsta artefakt som raderas ar {oldest} dagar gammal.")

        if not apply:
            print()
            print("DRY RUN. Inget raderat. Kor med --apply.")
            return 0

        if not plan["to_delete"]:
            print()
            print("Inget att radera.")
            return 0

        print()
        print(f"RADERAR{f' (max {limit})' if limit else ''}...")
        res = await execute_purge(db, plan, limit=limit)
        print(f"  raderade : {res['deleted']}")
        print(f"  atertaget: {_gb(res['reclaimed_bytes'])}")
        print(f"  misslyckades: {res['failed']}")
        for e in res["errors"]:
            print(f"    {e}")
        return 0 if res["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
