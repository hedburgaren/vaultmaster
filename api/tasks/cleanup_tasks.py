"""Periodic disk-hygiene tasks.

The 2026-05-02 incident dumped 1.6 TB of orphaned tar.gz files into the
work_dir because the success-path cleanup never ran (worker killed,
task redelivered, or backup failed before reaching the cleanup line).
The finally-block in `_run_backup` is the primary defence; this task
is the safety net that catches edge cases the finally-block can't —
worker SIGKILL, container OOM, host reboot mid-backup.

Approach: scan each known server's work_dir for files older than the
configured TTL that are NOT referenced by any artifact. Delete them.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone

from api.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


# tar.gz / dump.gz / sql.gz / files_*.tar.gz produced by executors
_TEMP_FILE_RE = re.compile(
    r"^("
    r"files_\d{8}_\d{6}\.tar\.gz|"
    r"docker_volumes_\d{8}_\d{6}\.tar\.gz|"
    r"[A-Za-z0-9_.\-]+_\d{8}_\d{6}\.(dump|sql)\.gz"
    r")$"
)


def _get_orphan_age_seconds() -> int:
    """Return the cutoff age for orphan deletion, configurable via
    `CLEANUP_ORPHAN_AGE_HOURS` env var (Bug #2). Default 12h is a
    comfortable margin over the longest expected backup timeout
    (currently 7200s for files / 3600s for postgres).
    """
    raw = os.getenv("CLEANUP_ORPHAN_AGE_HOURS", "12")
    try:
        hours = float(raw)
        if hours <= 0:
            raise ValueError("must be positive")
    except (TypeError, ValueError):
        logger.warning(
            f"[cleanup] invalid CLEANUP_ORPHAN_AGE_HOURS={raw!r}, falling back to 12h"
        )
        hours = 12.0
    return int(hours * 3600)


# Backwards-compat constant for callers/tests still importing the symbol.
DEFAULT_ORPHAN_AGE_SECONDS = 12 * 3600


@celery_app.task(name="api.tasks.cleanup_tasks.scan_orphan_temp_files")
def scan_orphan_temp_files():
    """Scan all servers' work_dir for orphaned temp files older than
    DEFAULT_ORPHAN_AGE_SECONDS that aren't referenced by any artifact."""
    from api.tasks.backup_tasks import _run_async
    _run_async(_scan_orphans())


async def _scan_orphans():
    import shlex as _shlex

    from sqlalchemy import select
    from api.models.server import Server
    from api.models.backup_artifact import BackupArtifact
    from api.models.backup_run import BackupRun
    from api.services.backup_executor import get_work_dir
    from api.services.ssh_client import run_remote_command, delete_remote_file
    from api.tasks.backup_tasks import get_task_session

    async with get_task_session() as db:
        work_dir = await get_work_dir(db)

        # Collect all currently-referenced filenames so we never delete
        # a file that a real artifact still points to (even if it's old).
        result = await db.execute(select(BackupArtifact.remote_path, BackupArtifact.filename))
        referenced: set[str] = set()
        for rp, fn in result.all():
            if rp:
                referenced.add(rp)
            if fn:
                referenced.add(fn)

        result = await db.execute(select(Server))
        servers = result.scalars().all()

        # Bug #2: per-server set of servers with an active run. Cleanup
        # must never touch a server while a run is in flight, because
        # the new BackupArtifact row isn't committed yet and we'd race
        # against an in-flight gzip/tar.
        result = await db.execute(
            select(BackupRun.server_id).where(BackupRun.status.in_(("pending", "running")))
        )
        busy_server_ids = {row[0] for row in result.all()}

    cleaned = 0
    bytes_freed = 0
    skipped_busy_servers = 0
    skipped_inuse_files = 0
    failed_listings: list[str] = []
    cutoff_age = _get_orphan_age_seconds()

    for server in servers:
        if server.id in busy_server_ids:
            logger.info(
                f"[cleanup] skipping {server.name} — backup run in flight"
            )
            skipped_busy_servers += 1
            continue

        # `find` lists files in work_dir, prints "<mtime_epoch> <size> <path>"
        # so we can filter by age + name client-side and never depend on
        # find's mtime-arithmetic semantics across BSD/GNU.
        # work_dir comes from a SystemSetting row, so it is operator-editable
        # via the UI. Unquoted it broke on any path containing a space, and
        # 2>/dev/null then hid the reason. Quote it and keep stderr.
        list_cmd = (
            f"find {_shlex.quote(work_dir)} -maxdepth 1 -type f "
            f"-printf '%T@ %s %f\\n'"
        )
        try:
            exit_code, stdout, stderr = await run_remote_command(server, list_cmd, timeout=30)
        except Exception as e:
            logger.warning(f"[cleanup] list failed on {server.name}: {e}")
            failed_listings.append(f"{server.name}: {e}")
            continue
        if exit_code != 0:
            # A failed listing is not an empty directory. Treating it as one
            # made every unreadable or non-GNU-find host report "0 files,
            # 0 bytes cleaned" as though the work had been done.
            logger.error(
                "[cleanup] listing FAILED on %s (exit %s): %s. Not treating this "
                "as an empty work_dir.",
                server.name, exit_code, (stderr or "").strip()[:200],
            )
            failed_listings.append(
                f"{server.name}: find exit {exit_code} {(stderr or '').strip()[:100]}"
            )
            continue
        if not stdout:
            continue

        now_ts = datetime.now(timezone.utc).timestamp()
        for line in stdout.splitlines():
            parts = line.strip().split(" ", 2)
            if len(parts) != 3:
                continue
            try:
                mtime = float(parts[0])
                size = int(parts[1])
            except ValueError:
                continue
            fname = parts[2]
            if not _TEMP_FILE_RE.match(fname):
                continue
            if (now_ts - mtime) < cutoff_age:
                continue
            full_path = f"{work_dir}/{fname}"
            if full_path in referenced or fname in referenced:
                continue

            # Bug #2: even after the busy-server filter, an in-flight
            # process (gzip, tar, scp) could have a stale work_dir
            # entry as an open FD. `fuser -s` is silent and returns 0
            # iff the file is in use by some process. We treat any
            # in-use signal as "skip" — better leak a few hours of disk
            # than yank the rug from under a live backup.
            quoted = _shlex.quote(full_path)
            try:
                fuser_rc, _, _ = await run_remote_command(
                    server, f"fuser -s {quoted}", timeout=10
                )
            except Exception as e:
                logger.warning(
                    f"[cleanup] fuser check failed for {full_path} on {server.name}: {e} — skipping"
                )
                skipped_inuse_files += 1
                continue
            # `fuser -s` exits 0 for in-use and 1 for not-in-use. Every other
            # code (127 missing binary, 126 permission denied, and so on) means
            # the check did not work. Treating those as "not in use" silently
            # disarmed this guard, so a host without fuser would delete backup
            # archives while they were still being written.
            from api.tasks.backup_tasks import file_is_free

            if not file_is_free(fuser_rc):
                logger.info(
                    f"[cleanup] {full_path} not confirmed free (fuser rc={fuser_rc}), skipping"
                )
                skipped_inuse_files += 1
                continue

            ok, msg = await delete_remote_file(server, full_path)
            if ok:
                cleaned += 1
                bytes_freed += size
                logger.info(f"[cleanup] removed orphan {full_path} ({size} bytes)")
            else:
                logger.warning(f"[cleanup] failed to remove {full_path}: {msg}")

    if failed_listings:
        logger.error(
            "[cleanup] %d server(s) could not be listed at all, their work_dir "
            "was NOT inspected: %s",
            len(failed_listings), "; ".join(failed_listings[:10]),
        )

    logger.info(
        f"[cleanup] done, {cleaned} files, {bytes_freed} bytes; "
        f"skipped_busy_servers={skipped_busy_servers}, "
        f"skipped_inuse_files={skipped_inuse_files}, "
        f"failed_listings={len(failed_listings)}"
    )
    return {
        "cleaned": cleaned,
        "bytes_freed": bytes_freed,
        "skipped_busy_servers": skipped_busy_servers,
        "skipped_inuse_files": skipped_inuse_files,
        "failed_listings": failed_listings,
    }
