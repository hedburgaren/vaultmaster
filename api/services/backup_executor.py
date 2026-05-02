import hashlib
import logging
import os
import tempfile
from datetime import datetime, timezone

from api.services.ssh_client import run_remote_command

logger = logging.getLogger(__name__)

DEFAULT_WORK_DIR = "/tmp/vaultmaster"


def _check_sudo_failure(stderr: str) -> str | None:
    """Return an error message if stderr indicates a sudo failure, else None."""
    if stderr and ("sudo:" in stderr.lower() and ("password is required" in stderr.lower() or "no tty present" in stderr.lower())):
        return f"sudo failed: {stderr.strip()} — configure passwordless sudo (NOPASSWD) for the SSH user or disable use_sudo on this server"
    return None


async def get_work_dir(db=None) -> str:
    """Get the configured work directory from system settings, or default."""
    try:
        if db:
            from sqlalchemy import select
            from api.models.system_settings import SystemSetting
            result = await db.execute(select(SystemSetting).where(SystemSetting.key == "work_dir"))
            setting = result.scalar_one_or_none()
            if setting and setting.value.strip():
                return setting.value.strip()
    except Exception:
        pass
    return DEFAULT_WORK_DIR


async def execute_postgresql_backup(server, job, run_id: str, db=None) -> dict:
    """Execute a PostgreSQL backup via pg_dump over SSH."""
    work_dir = await get_work_dir(db)
    config = job.source_config
    container = config.get("container")
    db_name = config.get("database") or config.get("db_name", "postgres")
    pg_user = config.get("username") or config.get("pg_user", "postgres")
    dump_format = config.get("format") or config.get("dump_format", "custom")
    compress_level = config.get("compress_level", 9)
    output_dir = config.get("output_dir", work_dir)
    stop_containers = config.get("stop_containers", [])

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ext = "dump" if dump_format == "custom" else "sql"
    filename = f"{db_name}_{timestamp}.{ext}.gz"
    remote_path = f"{output_dir}/{filename}"

    logs = []

    def log(level: str, msg: str):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg}
        logs.append(entry)
        logger.info(f"[{run_id}] {msg}")

    try:
        # Ensure output dir exists
        await run_remote_command(server, f"mkdir -p {output_dir}")

        # Stop containers if configured
        if stop_containers:
            containers = " ".join(stop_containers)
            log("info", f"Stopping containers: {containers}")
            await run_remote_command(server, f"docker stop {containers}")

        # Run pg_dump — via docker exec if container is specified
        if dump_format == "custom":
            pg_dump_cmd = f"pg_dump -U {pg_user} -Fc -Z {compress_level} {db_name}"
        else:
            pg_dump_cmd = f"pg_dump -U {pg_user} {db_name}"

        if container:
            dump_cmd = f"docker exec {container} {pg_dump_cmd} | gzip > {remote_path}"
        elif dump_format == "custom":
            dump_cmd = f"{pg_dump_cmd} > {remote_path}"
        else:
            dump_cmd = f"{pg_dump_cmd} | gzip -{compress_level} > {remote_path}"

        log("info", f"Running pg_dump for {db_name}" + (f" via container {container}" if container else ""))
        exit_code, stdout, stderr = await run_remote_command(server, dump_cmd, timeout=3600)

        sudo_err = _check_sudo_failure(stderr)
        if sudo_err:
            log("error", sudo_err)
            raise Exception(sudo_err)

        if exit_code != 0:
            log("error", f"pg_dump failed: {stderr}")
            raise Exception(f"pg_dump failed with exit code {exit_code}: {stderr}")

        log("info", "pg_dump completed successfully")

        # Get file size and checksum
        exit_code, stdout, _ = await run_remote_command(server, f"stat -c %s {remote_path}")
        size_bytes = int(stdout.strip()) if exit_code == 0 else 0

        exit_code, stdout, _ = await run_remote_command(server, f"sha256sum {remote_path}")
        checksum = stdout.split()[0] if exit_code == 0 else ""

        if size_bytes == 0:
            log("error", "Backup file is 0 bytes — pg_dump likely failed silently")
            raise Exception("Backup file is 0 bytes")

        log("info", f"Backup size: {size_bytes} bytes, checksum: {checksum[:16]}...")

        # Restart containers
        if stop_containers:
            containers = " ".join(stop_containers)
            log("info", f"Restarting containers: {containers}")
            await run_remote_command(server, f"docker start {containers}")

        return {
            "success": True,
            "filename": filename,
            "remote_path": remote_path,
            "size_bytes": size_bytes,
            "checksum_sha256": checksum,
            "logs": logs,
        }

    except Exception as e:
        # Restart containers on failure
        if stop_containers:
            containers = " ".join(stop_containers)
            await run_remote_command(server, f"docker start {containers}")
        log("error", str(e))
        return {"success": False, "error": str(e), "logs": logs}


async def execute_docker_volumes_backup(server, job, run_id: str, db=None) -> dict:
    """Backup Docker volumes via tar over SSH."""
    work_dir = await get_work_dir(db)
    config = job.source_config
    volumes = config.get("volumes", [])
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"docker_volumes_{timestamp}.tar.gz"
    remote_path = f"{work_dir}/{filename}"

    logs = []

    def log(level: str, msg: str):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg}
        logs.append(entry)

    try:
        await run_remote_command(server, f"mkdir -p {work_dir}")

        if volumes:
            volume_paths = " ".join(f"/var/lib/docker/volumes/{v}" for v in volumes)
        else:
            volume_paths = "/var/lib/docker/volumes"

        log("info", f"Archiving Docker volumes: {volume_paths}")
        cmd = f"tar -czf {remote_path} {volume_paths}"
        exit_code, stdout, stderr = await run_remote_command(server, cmd, timeout=3600)

        sudo_err = _check_sudo_failure(stderr)
        if sudo_err:
            log("error", sudo_err)
            raise Exception(sudo_err)

        if exit_code != 0:
            log("error", f"tar failed: {stderr}")
            raise Exception(f"tar failed: {stderr}")

        exit_code, stdout, _ = await run_remote_command(server, f"stat -c %s {remote_path}")
        size_bytes = int(stdout.strip()) if exit_code == 0 else 0

        exit_code, stdout, _ = await run_remote_command(server, f"sha256sum {remote_path}")
        checksum = stdout.split()[0] if exit_code == 0 else ""

        if size_bytes == 0:
            log("error", "Backup file is 0 bytes — tar likely failed silently")
            raise Exception("Backup file is 0 bytes")

        log("info", f"Docker volumes backup complete: {size_bytes} bytes")

        return {
            "success": True,
            "filename": filename,
            "remote_path": remote_path,
            "size_bytes": size_bytes,
            "checksum_sha256": checksum,
            "logs": logs,
        }

    except Exception as e:
        log("error", str(e))
        return {"success": False, "error": str(e), "logs": logs}


async def execute_files_backup(server, job, run_id: str, db=None) -> dict:
    """Backup files/directories via tar over SSH."""
    work_dir = await get_work_dir(db)
    config = job.source_config
    paths = config.get("paths", [])
    excludes = config.get("excludes", [])
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"files_{timestamp}.tar.gz"
    remote_path = f"{work_dir}/{filename}"

    logs = []

    def log(level: str, msg: str):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg}
        logs.append(entry)

    try:
        await run_remote_command(server, f"mkdir -p {work_dir}")

        exclude_flags = " ".join(f"--exclude='{e}'" for e in excludes)
        path_str = " ".join(paths)
        cmd = f"tar -czf {remote_path} {exclude_flags} {path_str}"

        log("info", f"Archiving files: {path_str}")
        log("info", f"Work dir: {work_dir} → {remote_path}")
        exit_code, stdout, stderr = await run_remote_command(server, cmd, timeout=7200)

        sudo_err = _check_sudo_failure(stderr)
        if sudo_err:
            log("error", sudo_err)
            raise Exception(sudo_err)

        if exit_code != 0 and exit_code != 1:  # tar returns 1 for "file changed during read"
            log("error", f"tar failed (exit {exit_code}): {stderr}")
            raise Exception(f"tar failed: {stderr}")

        if exit_code == 1:
            log("warn", f"tar warning (exit 1): {stderr.strip()[:200] if stderr else 'file changed during read'}")

        exit_code, stdout, stderr = await run_remote_command(server, f"stat -c %s {remote_path}")
        if exit_code != 0:
            log("warn", f"stat failed (exit {exit_code}): {stderr}")
        size_bytes = int(stdout.strip()) if exit_code == 0 and stdout.strip().isdigit() else 0

        exit_code, stdout, stderr = await run_remote_command(server, f"sha256sum {remote_path}")
        if exit_code != 0:
            log("warn", f"sha256sum failed (exit {exit_code}): {stderr}")
        checksum = stdout.split()[0] if exit_code == 0 and stdout.strip() else ""

        # Fail if backup produced an empty file
        if size_bytes == 0:
            log("error", "Backup file is 0 bytes — backup likely failed silently")
            raise Exception("Backup file is 0 bytes")

        log("info", f"File backup complete: {size_bytes} bytes, checksum: {checksum[:16]}..." if checksum else f"File backup complete: {size_bytes} bytes (no checksum)")

        return {
            "success": True,
            "filename": filename,
            "remote_path": remote_path,
            "size_bytes": size_bytes,
            "checksum_sha256": checksum,
            "logs": logs,
        }

    except Exception as e:
        log("error", str(e))
        return {"success": False, "error": str(e), "logs": logs}


async def execute_custom_backup(server, job, run_id: str, db=None) -> dict:
    """Execute a custom shell command/script for backup."""
    config = job.source_config
    script = config.get("command") or config.get("script", "")
    if not script:
        return {"success": False, "error": "No command or script configured", "logs": []}

    logs = []

    def log(level: str, msg: str):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg}
        logs.append(entry)

    try:
        log("info", f"Running custom script")
        exit_code, stdout, stderr = await run_remote_command(server, script, timeout=7200)

        if exit_code != 0:
            log("error", f"Script failed (exit {exit_code}): {stderr}")
            raise Exception(f"Script failed: {stderr}")

        log("info", "Custom script completed")

        return {
            "success": True,
            "filename": "custom_backup",
            "remote_path": "",
            "size_bytes": 0,
            "checksum_sha256": "",
            "logs": logs,
            "stdout": stdout,
        }

    except Exception as e:
        log("error", str(e))
        return {"success": False, "error": str(e), "logs": logs}
