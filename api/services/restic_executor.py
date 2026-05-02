"""Restic backup executor.

Restic pushes directly to its own repo (S3/B2/SFTP/local/rclone-backed)
so we don't need a separate transfer step. The executor returns
`skip_transfer=True` to signal `backup_tasks.run_backup_task` that it
should not attempt rclone or SFTP transfer of a temp file.

Source-host requirement: `restic` >= 0.16 must be installed and on
$PATH for the SSH user. Repo password is taken from an environment
variable on the source host (default `RESTIC_PASSWORD`); set it via
the SSH user's profile or the systemd unit that runs as the user.

source_config schema:
    {
        "paths":            ["/path/to/data", ...],   # required
        "excludes":         ["**/cache/**", ...],     # optional
        "repo_url":         "rclone:b2:bucket-name",  # required
        "password_env_var": "RESTIC_PASSWORD",        # optional, default
        "tags":             ["seafile", "production"],# optional, extra tags
        "retention": {                                # optional
            "daily":   7,
            "weekly":  4,
            "monthly": 6
        }
    }
"""

from __future__ import annotations

import json
import logging
import shlex
from datetime import datetime, timezone

from api.services.ssh_client import run_remote_command


logger = logging.getLogger(__name__)


async def execute_restic_backup(server, job, run_id: str, db=None) -> dict:
    """Execute a restic backup over SSH."""
    config = job.source_config or {}
    paths = config.get("paths", [])
    excludes = config.get("excludes", [])
    repo_url = config.get("repo_url")
    password_env = config.get("password_env_var", "RESTIC_PASSWORD")
    extra_tags = config.get("tags", [])
    retention = config.get("retention", {}) or {}

    logs: list[dict] = []

    def log(level: str, msg: str) -> None:
        logs.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "msg": msg,
        })

    if not paths:
        return {"success": False, "error": "source_config.paths is required", "logs": logs}
    if not repo_url:
        return {"success": False, "error": "source_config.repo_url is required", "logs": logs}

    repo_q = shlex.quote(repo_url)
    pw_var_q = shlex.quote(password_env)
    env_prefix = (
        f"export RESTIC_REPOSITORY={repo_q}; "
        f'export RESTIC_PASSWORD="${{{password_env}}}"; '
        f'if [ -z "$RESTIC_PASSWORD" ]; then echo "RESTIC_PASSWORD env not set" >&2; exit 7; fi;'
    )

    log("info", f"Repo: {repo_url}, password from $%s" % password_env)

    # 1. Ensure repo exists (idempotent). `restic snapshots` succeeds if
    #    the repo is initialized; init only if it isn't.
    code, _, stderr = await run_remote_command(
        server,
        f"{env_prefix} restic snapshots --no-lock --json --quiet",
        timeout=120,
    )
    if code == 7:
        return {"success": False, "error": "RESTIC_PASSWORD env not set on source host", "logs": logs}
    if code != 0:
        log("warn", f"`restic snapshots` failed (exit {code}); attempting init")
        code2, _, stderr2 = await run_remote_command(server, f"{env_prefix} restic init", timeout=120)
        if code2 != 0:
            err = (stderr2 or stderr or "").strip()[:300]
            log("error", f"restic init failed: {err}")
            return {"success": False, "error": f"restic init failed: {err}", "logs": logs}
        log("info", "restic repo initialized")

    # 2. Backup
    tags = [f"job:{job.name}", f"run:{run_id}"] + list(extra_tags)
    tag_flags = " ".join(f"--tag {shlex.quote(t)}" for t in tags)
    exclude_flags = " ".join(f"--exclude {shlex.quote(e)}" for e in excludes)
    paths_quoted = " ".join(shlex.quote(p) for p in paths)

    cmd = (
        f"{env_prefix} restic backup {paths_quoted} {exclude_flags} {tag_flags} "
        f"--json --no-lock"
    )
    log("info", f"Starting restic backup: {paths_quoted}")
    code, stdout, stderr = await run_remote_command(server, cmd, timeout=86400)

    if code != 0:
        err = (stderr or "").strip()[:500]
        log("error", f"restic backup failed (exit {code}): {err}")
        return {"success": False, "error": f"restic backup failed: {err}", "logs": logs}

    snapshot_id = ""
    files_new = files_changed = total_files = 0
    data_added = total_bytes_processed = 0
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("message_type") == "summary":
            snapshot_id = obj.get("snapshot_id") or ""
            files_new = int(obj.get("files_new", 0))
            files_changed = int(obj.get("files_changed", 0))
            total_files = int(obj.get("total_files_processed", 0))
            data_added = int(obj.get("data_added", 0))
            total_bytes_processed = int(obj.get("total_bytes_processed", 0))

    if not snapshot_id:
        log("warn", "restic produced no summary line — backup may have stored nothing")
    else:
        log("info",
            f"Snapshot {snapshot_id[:12]}: new={files_new} changed={files_changed} "
            f"data_added={data_added} total_bytes={total_bytes_processed}")

    # 3. Forget + prune (optional)
    if retention:
        forget_args: list[str] = []
        for k in ("hourly", "daily", "weekly", "monthly", "yearly"):
            v = retention.get(k)
            if isinstance(v, int) and v > 0:
                forget_args.append(f"--keep-{k} {v}")
        if forget_args:
            tag_filter = f"--tag {shlex.quote('job:' + job.name)}"
            cmd = f"{env_prefix} restic forget {tag_filter} --prune --no-lock " + " ".join(forget_args)
            log("info", f"forget+prune: {' '.join(forget_args)}")
            code, _, stderr = await run_remote_command(server, cmd, timeout=3600)
            if code != 0:
                log("warn", f"restic forget+prune failed (exit {code}): {(stderr or '').strip()[:200]}")
            else:
                log("info", "forget+prune complete")

    return {
        "success": True,
        "filename": f"restic-snapshot-{snapshot_id[:12]}" if snapshot_id else "restic-empty",
        "remote_path": f"{repo_url}#{snapshot_id}" if snapshot_id else repo_url,
        "size_bytes": data_added,
        "checksum_sha256": snapshot_id or "",
        "skip_transfer": True,
        "logs": logs,
        "metadata": {
            "snapshot_id": snapshot_id,
            "files_new": files_new,
            "files_changed": files_changed,
            "total_files_processed": total_files,
            "data_added": data_added,
            "total_bytes_processed": total_bytes_processed,
            "repo_url": repo_url,
            "tags": tags,
        },
    }
