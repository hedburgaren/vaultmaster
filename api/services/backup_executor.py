import hashlib
import logging
import os
import tempfile
from datetime import datetime, timezone

from api.services.ssh_client import run_remote_command

logger = logging.getLogger(__name__)


async def execute_postgresql_backup(server, job, run_id: str) -> dict:
    """Execute a PostgreSQL backup via pg_dump over SSH."""
    config = job.source_config
    db_name = config.get("db_name", "postgres")
    pg_user = config.get("pg_user", "postgres")
    dump_format = config.get("dump_format", "custom")
    compress_level = config.get("compress_level", 9)
    stop_containers = config.get("stop_containers", [])

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ext = "dump" if dump_format == "custom" else "sql"
    filename = f"{db_name}_{timestamp}.{ext}.gz"
    remote_path = f"/tmp/vaultmaster/{filename}"

    logs = []

    def log(level: str, msg: str):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg}
        logs.append(entry)
        logger.info(f"[{run_id}] {msg}")

    try:
        # Ensure temp dir exists
        await run_remote_command(server, "mkdir -p /tmp/vaultmaster")

        # Stop containers if configured
        if stop_containers:
            containers = " ".join(stop_containers)
            log("info", f"Stopping containers: {containers}")
            await run_remote_command(server, f"docker stop {containers}")

        # Run pg_dump
        if dump_format == "custom":
            dump_cmd = f"pg_dump -U {pg_user} -Fc -Z {compress_level} {db_name} > {remote_path}"
        else:
            dump_cmd = f"pg_dump -U {pg_user} {db_name} | gzip -{compress_level} > {remote_path}"

        log("info", f"Running pg_dump for {db_name}")
        exit_code, stdout, stderr = await run_remote_command(server, dump_cmd, timeout=3600)

        if exit_code != 0:
            log("error", f"pg_dump failed: {stderr}")
            raise Exception(f"pg_dump failed with exit code {exit_code}: {stderr}")

        log("info", "pg_dump completed successfully")

        # Get file size and checksum
        exit_code, stdout, _ = await run_remote_command(server, f"stat -c %s {remote_path}")
        size_bytes = int(stdout.strip()) if exit_code == 0 else 0

        exit_code, stdout, _ = await run_remote_command(server, f"sha256sum {remote_path}")
        checksum = stdout.split()[0] if exit_code == 0 else ""

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


async def execute_docker_volumes_backup(server, job, run_id: str) -> dict:
    """Backup Docker volumes via tar over SSH."""
    config = job.source_config
    volumes = config.get("volumes", [])
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"docker_volumes_{timestamp}.tar.gz"
    remote_path = f"/tmp/vaultmaster/{filename}"

    logs = []

    def log(level: str, msg: str):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg}
        logs.append(entry)

    try:
        await run_remote_command(server, "mkdir -p /tmp/vaultmaster")

        if volumes:
            volume_paths = " ".join(f"/var/lib/docker/volumes/{v}" for v in volumes)
        else:
            volume_paths = "/var/lib/docker/volumes"

        log("info", f"Archiving Docker volumes: {volume_paths}")
        cmd = f"tar -czf {remote_path} {volume_paths}"
        exit_code, stdout, stderr = await run_remote_command(server, cmd, timeout=3600)

        if exit_code != 0:
            log("error", f"tar failed: {stderr}")
            raise Exception(f"tar failed: {stderr}")

        exit_code, stdout, _ = await run_remote_command(server, f"stat -c %s {remote_path}")
        size_bytes = int(stdout.strip()) if exit_code == 0 else 0

        exit_code, stdout, _ = await run_remote_command(server, f"sha256sum {remote_path}")
        checksum = stdout.split()[0] if exit_code == 0 else ""

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


async def execute_files_backup(server, job, run_id: str) -> dict:
    """Backup files/directories via tar over SSH."""
    config = job.source_config
    paths = config.get("paths", [])
    excludes = config.get("excludes", [])
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"files_{timestamp}.tar.gz"
    remote_path = f"/tmp/vaultmaster/{filename}"

    logs = []

    def log(level: str, msg: str):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg}
        logs.append(entry)

    try:
        await run_remote_command(server, "mkdir -p /tmp/vaultmaster")

        exclude_flags = " ".join(f"--exclude='{e}'" for e in excludes)
        path_str = " ".join(paths)
        cmd = f"tar -czf {remote_path} {exclude_flags} {path_str}"

        log("info", f"Archiving files: {path_str}")
        exit_code, stdout, stderr = await run_remote_command(server, cmd, timeout=7200)

        if exit_code != 0 and exit_code != 1:  # tar returns 1 for "file changed during read"
            log("error", f"tar failed: {stderr}")
            raise Exception(f"tar failed: {stderr}")

        exit_code, stdout, _ = await run_remote_command(server, f"stat -c %s {remote_path}")
        size_bytes = int(stdout.strip()) if exit_code == 0 else 0

        exit_code, stdout, _ = await run_remote_command(server, f"sha256sum {remote_path}")
        checksum = stdout.split()[0] if exit_code == 0 else ""

        log("info", f"File backup complete: {size_bytes} bytes")

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


async def execute_custom_backup(server, job, run_id: str) -> dict:
    """Execute a custom shell script for backup."""
    config = job.source_config
    script = config.get("script", "")
    if not script:
        return {"success": False, "error": "No script configured", "logs": []}

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
