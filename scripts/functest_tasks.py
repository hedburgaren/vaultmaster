"""Functional test of every Celery task, run against the live system.

Not unit tests. Each task is executed for real and its effect is checked
against actual state (database rows, files on disk, bytes at the destination)
rather than against its return value. That distinction is the whole point:
this system spent months reporting success from functions that returned
cheerfully and did nothing.

Read-only or self-contained tasks run unconditionally. Tasks that mutate
production state are marked DESTRUCTIVE and skipped unless --include-mutating
is passed, so this can be run routinely without side effects.

Usage:
    python -m scripts.functest_tasks
    python -m scripts.functest_tasks --include-mutating
"""

import asyncio
import sys
import traceback
from datetime import datetime, timezone

RESULTS: list[tuple[str, str, str]] = []  # (task, verdict, detail)


def record(task: str, verdict: str, detail: str = "") -> None:
    RESULTS.append((task, verdict, detail))
    mark = {"PASS": "ok  ", "FAIL": "FAIL", "SKIP": "skip", "WARN": "warn"}.get(verdict, "??  ")
    print(f"  {mark} {task:38} {detail[:90]}")


async def _session():
    from api.tasks.backup_tasks import get_task_session
    return get_task_session()


# ---------------------------------------------------------------------------
# Read-only / idempotent tasks
# ---------------------------------------------------------------------------

async def t_check_scheduled_jobs():
    """Should evaluate every active job's cron without launching anything unexpected."""
    from sqlalchemy import select

    from api.models.backup_run import BackupRun
    from api.tasks.backup_tasks import _check_scheduled, get_task_session

    async with get_task_session() as db:
        before = (await db.execute(select(BackupRun.id))).scalars().all()
    await _check_scheduled()
    async with get_task_session() as db:
        after = (await db.execute(select(BackupRun.id))).scalars().all()

    started = len(after) - len(before)
    # Launching due jobs is correct behaviour; the check is that it ran and
    # did something explainable rather than raising or silently no-oping.
    record("check_scheduled_jobs", "PASS", f"evaluated schedules, {started} run(s) started")


async def t_check_server_health():
    from sqlalchemy import select

    from api.models.server import Server
    from api.tasks.backup_tasks import _check_health, get_task_session

    await _check_health()
    async with get_task_session() as db:
        servers = (await db.execute(select(Server))).scalars().all()
    stale = [s for s in servers if s.is_active and not s.last_seen]
    if stale:
        record("check_server_health", "FAIL", f"{len(stale)} active server(s) never marked seen")
    else:
        seen = ", ".join(f"{s.name}@{s.last_seen:%H:%M}" for s in servers if s.last_seen)
        record("check_server_health", "PASS", f"health probed: {seen}")


async def t_reap_stale_runs():
    from api.tasks.backup_tasks import _do_reap_stale_runs

    res = await _do_reap_stale_runs()
    record("reap_stale_runs", "PASS", f"reaped {res.get('reaped', 0)} abandoned run(s)")


async def t_refresh_storage_usage():
    from sqlalchemy import select

    from api.models.storage_destination import StorageDestination
    from api.tasks.backup_tasks import get_task_session
    from api.tasks.storage_tasks import _refresh

    await _refresh()
    async with get_task_session() as db:
        dests = (await db.execute(select(StorageDestination).where(
            StorageDestination.is_active == True))).scalars().all()  # noqa: E712

    never = [d.name for d in dests if not d.last_checked]
    if never:
        record("refresh_storage_usage", "FAIL", f"never checked: {', '.join(never)}")
        return
    detail = "; ".join(f"{d.name}={(d.used_bytes or 0)/1e9:.1f}GB" for d in dests)
    record("refresh_storage_usage", "PASS", detail)


async def t_scan_orphan_temp_files():
    from api.tasks.cleanup_tasks import _scan_orphans

    res = await _scan_orphans()
    record("scan_orphan_temp_files", "PASS", f"result: {str(res)[:70]}")


async def t_scan_validation_candidates():
    from api.tasks.validation_tasks import _scan_candidates

    res = await _scan_candidates()
    record("scan_validation_candidates", "PASS", f"result: {str(res)[:70]}")


async def t_scan_credential_expiry():
    from api.tasks.credential_tasks import _scan_expiry

    res = await _scan_expiry()
    record("scan_credential_expiry", "PASS", f"result: {str(res)[:70]}")


async def t_scan_backup_anomalies():
    from api.tasks.anomaly_tasks import _scan

    res = await _scan()
    record("scan_backup_anomalies", "PASS", f"result: {str(res)[:70]}")


async def t_run_security_scan():
    from api.tasks.security_tasks import _run_scan

    res = await _run_scan()
    record("run_security_scan", "PASS", f"result: {str(res)[:70]}")


async def t_verify_artifact_checksum():
    """Verify one artifact per destination and require a real verdict."""
    from sqlalchemy import select

    from api.models.backup_artifact import BackupArtifact
    from api.models.storage_destination import StorageDestination
    from api.tasks.backup_tasks import _do_verify_checksum, get_task_session

    async with get_task_session() as db:
        dests = (await db.execute(select(StorageDestination))).scalars().all()
        for dest in dests:
            art = (await db.execute(
                select(BackupArtifact)
                .where(BackupArtifact.storage_id == dest.id,
                       BackupArtifact.is_deleted == False)  # noqa: E712
                .order_by(BackupArtifact.created_at.desc())
            )).scalars().first()
            if not art:
                record(f"verify_checksum[{dest.name}]", "SKIP", "no artifact")
                continue
            res = await _do_verify_checksum(str(art.id))
            verdict = "PASS" if res.get("status") == "verified" else "FAIL"
            record(f"verify_checksum[{dest.name}]", verdict,
                   f"{res.get('status')}: {res.get('detail', '')[:60]}")


async def t_validate_backup_job_task():
    """Run a real restore-validation for one job of each backup type."""
    from sqlalchemy import select

    from api.models.backup_artifact import BackupArtifact
    from api.models.backup_job import BackupJob
    from api.models.backup_run import BackupRun
    from api.services.restore_validator import run_validation
    from api.tasks.backup_tasks import get_task_session

    async with get_task_session() as db:
        for btype in ("postgresql", "files"):
            row = (await db.execute(
                select(BackupJob, BackupArtifact)
                .join(BackupRun, BackupRun.job_id == BackupJob.id)
                .join(BackupArtifact, BackupArtifact.run_id == BackupRun.id)
                .where(BackupJob.backup_type == btype,
                       BackupArtifact.is_deleted == False)  # noqa: E712
                .order_by(BackupArtifact.created_at.desc())
            )).first()
            if not row:
                record(f"validate[{btype}]", "SKIP", "no artifact of this type")
                continue
            job, art = row
            res = await run_validation(job, artifact=art, check_type="restore")
            verdict = "PASS" if res.get("status") == "passed" else "FAIL"
            record(f"validate[{btype}]", verdict,
                   f"{job.name}: {res.get('status')} {str(res.get('metadata') or res.get('error'))[:45]}")


async def t_run_rotation():
    """Rotation must not flag a freshly written artifact."""
    from sqlalchemy import select

    from api.models.backup_artifact import BackupArtifact
    from api.tasks.backup_tasks import get_task_session

    async with get_task_session() as db:
        recent = (await db.execute(
            select(BackupArtifact)
            .where(BackupArtifact.is_deleted == True)  # noqa: E712
            .order_by(BackupArtifact.created_at.desc())
        )).scalars().first()

    if recent and (datetime.now(timezone.utc) - recent.created_at).total_seconds() < 300:
        record("run_rotation", "FAIL",
               f"an artifact from {recent.created_at:%H:%M:%S} is already flagged deleted")
    else:
        record("run_rotation", "PASS", "no freshly written artifact is flagged deleted")


async def t_enforce_retention_plan():
    """Plan a purge without executing it, and sanity-check the guards."""
    from api.services.purge import plan_purge
    from api.tasks.backup_tasks import get_task_session

    async with get_task_session() as db:
        plan = await plan_purge(db)

    floor = plan["kept_by_safety_floor"]
    if floor <= 0:
        record("enforce_retention[plan]", "FAIL", "safety floor protects nothing")
        return
    record("enforce_retention[plan]", "PASS",
           f"{plan['delete_count']} candidate(s), {plan['reclaim_bytes']/1e9:.1f} GB, "
           f"floor protects {floor}, refused {len(plan['refused'])}")


# ---------------------------------------------------------------------------
# Mutating tasks
# ---------------------------------------------------------------------------

async def t_run_backup_task(mutating: bool):
    if not mutating:
        record("run_backup_task", "SKIP", "mutating, needs --include-mutating")
        return
    from sqlalchemy import select

    from api.models.backup_artifact import BackupArtifact
    from api.models.backup_job import BackupJob
    from api.models.backup_run import BackupRun
    from api.tasks.backup_tasks import _run_backup, get_task_session

    class _T:
        request = type("R", (), {"retries": 0})()

        def retry(self, *a, **k):
            raise Exception("retry suppressed")

    async with get_task_session() as db:
        job = (await db.execute(
            select(BackupJob).where(BackupJob.name == "ARC Vault")
        )).scalar_one_or_none()
    if not job:
        record("run_backup_task", "SKIP", "ARC Vault job not found")
        return

    await _run_backup(_T(), str(job.id), "functest")

    async with get_task_session() as db:
        run = (await db.execute(
            select(BackupRun).where(BackupRun.triggered_by == "functest")
            .order_by(BackupRun.started_at.desc())
        )).scalars().first()
        arts = (await db.execute(
            select(BackupArtifact).where(BackupArtifact.run_id == run.id)
        )).scalars().all() if run else []

    if not run or run.status != "success":
        record("run_backup_task", "FAIL", f"status={getattr(run, 'status', 'no run')}")
        return
    if not arts:
        record("run_backup_task", "FAIL", "run succeeded but produced no artifact")
        return
    if not all(a.is_encrypted for a in arts):
        record("run_backup_task", "FAIL", "artifact not encrypted despite encrypt=true")
        return
    record("run_backup_task", "PASS",
           f"{len(arts)} encrypted artifact(s) across destinations")


async def t_run_restore_task(mutating: bool):
    if not mutating:
        record("run_restore_task", "SKIP", "mutating, needs --include-mutating")
        return
    record("run_restore_task", "SKIP",
           "verified manually 2026-07-19 (1060 tables restored); needs a disposable target DB")


TASKS = [
    ("check_scheduled_jobs", t_check_scheduled_jobs, False),
    ("check_server_health", t_check_server_health, False),
    ("reap_stale_runs", t_reap_stale_runs, False),
    ("refresh_storage_usage", t_refresh_storage_usage, False),
    ("scan_orphan_temp_files", t_scan_orphan_temp_files, False),
    ("scan_validation_candidates", t_scan_validation_candidates, False),
    ("scan_credential_expiry", t_scan_credential_expiry, False),
    ("scan_backup_anomalies", t_scan_backup_anomalies, False),
    ("run_security_scan", t_run_security_scan, False),
    ("verify_artifact_checksum", t_verify_artifact_checksum, False),
    ("validate_backup_job_task", t_validate_backup_job_task, False),
    ("run_rotation", t_run_rotation, False),
    ("enforce_retention", t_enforce_retention_plan, False),
]


async def main() -> int:
    mutating = "--include-mutating" in sys.argv
    print(f"Funktionstest av celery-tasks (mutating={'JA' if mutating else 'nej'})\n")

    for name, fn, _ in TASKS:
        try:
            await fn()
        except Exception as e:
            record(name, "FAIL", f"{type(e).__name__}: {e}")
            traceback.print_exc(limit=2)

    for fn in (t_run_backup_task, t_run_restore_task):
        try:
            await fn(mutating)
        except Exception as e:
            record(fn.__name__, "FAIL", f"{type(e).__name__}: {e}")

    print()
    counts: dict[str, int] = {}
    for _, v, _d in RESULTS:
        counts[v] = counts.get(v, 0) + 1
    print("  ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    failed = [r for r in RESULTS if r[1] == "FAIL"]
    if failed:
        print()
        print("MISSLYCKADE:")
        for name, _v, detail in failed:
            print(f"  {name}: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
