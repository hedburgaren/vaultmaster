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

# How old a file has to be before we'll delete it — must be longer than
# the longest expected backup timeout (currently 7200s for files / 3600s
# for postgres). We use 12h as a comfortable margin.
DEFAULT_ORPHAN_AGE_SECONDS = 12 * 3600


@celery_app.task(name="api.tasks.cleanup_tasks.scan_orphan_temp_files")
def scan_orphan_temp_files():
    """Scan all servers' work_dir for orphaned temp files older than
    DEFAULT_ORPHAN_AGE_SECONDS that aren't referenced by any artifact."""
    from api.tasks.backup_tasks import _run_async
    _run_async(_scan_orphans())


async def _scan_orphans():
    from sqlalchemy import select
    from api.models.server import Server
    from api.models.backup_artifact import BackupArtifact
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

    cleaned = 0
    bytes_freed = 0
    cutoff_age = DEFAULT_ORPHAN_AGE_SECONDS

    for server in servers:
        # `find` lists files in work_dir, prints "<mtime_epoch> <size> <path>"
        # so we can filter by age + name client-side and never depend on
        # find's mtime-arithmetic semantics across BSD/GNU.
        list_cmd = f"find {work_dir} -maxdepth 1 -type f -printf '%T@ %s %f\\n' 2>/dev/null"
        try:
            exit_code, stdout, stderr = await run_remote_command(server, list_cmd, timeout=30)
        except Exception as e:
            logger.warning(f"[cleanup] list failed on {server.name}: {e}")
            continue
        if exit_code != 0 or not stdout:
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

            ok, msg = await delete_remote_file(server, full_path)
            if ok:
                cleaned += 1
                bytes_freed += size
                logger.info(f"[cleanup] removed orphan {full_path} ({size} bytes)")
            else:
                logger.warning(f"[cleanup] failed to remove {full_path}: {msg}")

    logger.info(f"[cleanup] done — {cleaned} files, {bytes_freed} bytes")
    return {"cleaned": cleaned, "bytes_freed": bytes_freed}
