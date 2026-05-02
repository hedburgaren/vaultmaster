import hashlib
import logging
import os
import re
import shlex
import tempfile
from datetime import datetime, timezone

from api.services.ssh_client import run_remote_command

logger = logging.getLogger(__name__)

DEFAULT_WORK_DIR = "/tmp/vaultmaster"

# Pattern for plain identifier-like values (postgres user, db name, docker
# container name, docker volume name). No spaces, no shell metacharacters.
_IDENT_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,63}$")
# Patterns we accept inside paths (absolute or relative).
_PATH_RE = re.compile(r"^[A-Za-z0-9_.\-/+@:= ]{1,1024}$")


def _safe_ident(name: str, kind: str) -> str:
    """Validate an identifier-like input or raise. Returned value is safe
    to interpolate into shell commands without further quoting (but we
    still shlex.quote it at the call site as defense in depth)."""
    s = "" if name is None else str(name)
    if not _IDENT_RE.match(s):
        raise ValueError(f"Invalid {kind}: {s!r} (must match [A-Za-z0-9_.-]{{1,63}})")
    return s


def _safe_path(value: str, kind: str = "path") -> str:
    s = "" if value is None else str(value)
    if not _PATH_RE.match(s):
        raise ValueError(f"Invalid {kind}: {s!r}")
    return s


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
    """Execute a PostgreSQL backup via pg_dump (over SSH or via docker exec)."""
    work_dir = await get_work_dir(db)
    config = job.source_config
    logs = []

    def log(level: str, msg: str):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg}
        logs.append(entry)
        logger.info(f"[{run_id}] {msg}")

    try:
        container_raw = config.get("container")
        container = _safe_ident(container_raw, "container") if container_raw else None
        db_name = _safe_ident(
            config.get("database") or config.get("db_name", "postgres"),
            "db_name",
        )
        pg_user = _safe_ident(
            config.get("username") or config.get("pg_user", "postgres"),
            "pg_user",
        )
        dump_format = config.get("format") or config.get("dump_format", "custom")
        if dump_format not in ("custom", "plain"):
            raise ValueError(f"Invalid dump_format: {dump_format!r}")
        try:
            compress_level = int(config.get("compress_level", 9))
        except (TypeError, ValueError):
            raise ValueError("compress_level must be an int 0..9")
        if not 0 <= compress_level <= 9:
            raise ValueError("compress_level must be 0..9")

        stop_containers_raw = config.get("stop_containers", []) or []
        stop_containers = [_safe_ident(c, "container_name") for c in stop_containers_raw]

        output_dir_v = _safe_path(config.get("output_dir") or work_dir, "output_dir")
    except ValueError as e:
        log("error", str(e))
        return {"success": False, "error": str(e), "logs": logs}

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ext = "dump" if dump_format == "custom" else "sql"
    filename = f"{db_name}_{timestamp}.{ext}.gz"
    remote_path = f"{output_dir_v}/{filename}"
    output_dir_q = shlex.quote(output_dir_v)
    remote_path_q = shlex.quote(remote_path)
    db_name_q = shlex.quote(db_name)
    pg_user_q = shlex.quote(pg_user)

    try:
        await run_remote_command(server, f"mkdir -p {output_dir_q}")

        if stop_containers:
            containers_q = " ".join(shlex.quote(c) for c in stop_containers)
            log("info", f"Stopping containers: {containers_q}")
            await run_remote_command(server, f"docker stop {containers_q}")

        # Build pg_dump invocation; format dictates whether gzip is needed.
        if dump_format == "custom":
            pg_dump_cmd = f"pg_dump -U {pg_user_q} -Fc -Z {compress_level} {db_name_q}"
        else:
            pg_dump_cmd = f"pg_dump -U {pg_user_q} {db_name_q}"

        if container:
            container_q = shlex.quote(container)
            dump_cmd = f"docker exec {container_q} {pg_dump_cmd} | gzip > {remote_path_q}"
        elif dump_format == "custom":
            dump_cmd = f"{pg_dump_cmd} > {remote_path_q}"
        else:
            dump_cmd = f"{pg_dump_cmd} | gzip -{compress_level} > {remote_path_q}"

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

        exit_code, stdout, _ = await run_remote_command(server, f"stat -c %s {remote_path_q}")
        size_bytes = int(stdout.strip()) if exit_code == 0 else 0

        exit_code, stdout, _ = await run_remote_command(server, f"sha256sum {remote_path_q}")
        checksum = stdout.split()[0] if exit_code == 0 else ""

        if size_bytes == 0:
            log("error", "Backup file is 0 bytes — pg_dump likely failed silently")
            raise Exception("Backup file is 0 bytes")

        log("info", f"Backup size: {size_bytes} bytes, checksum: {checksum[:16]}...")

        if stop_containers:
            containers_q = " ".join(shlex.quote(c) for c in stop_containers)
            log("info", f"Restarting containers: {containers_q}")
            await run_remote_command(server, f"docker start {containers_q}")

        return {
            "success": True,
            "filename": filename,
            "remote_path": remote_path,
            "size_bytes": size_bytes,
            "checksum_sha256": checksum,
            "logs": logs,
        }

    except Exception as e:
        if stop_containers:
            containers_q = " ".join(shlex.quote(c) for c in stop_containers)
            await run_remote_command(server, f"docker start {containers_q}")
        log("error", str(e))
        return {"success": False, "error": str(e), "logs": logs}


async def execute_docker_volumes_backup(server, job, run_id: str, db=None) -> dict:
    """Backup Docker volumes via tar over SSH."""
    work_dir = await get_work_dir(db)
    config = job.source_config
    logs = []

    def log(level: str, msg: str):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg}
        logs.append(entry)

    try:
        volumes_raw = config.get("volumes", []) or []
        volumes = [_safe_ident(v, "volume_name") for v in volumes_raw]
        work_dir_v = _safe_path(work_dir, "work_dir")
    except ValueError as e:
        log("error", str(e))
        return {"success": False, "error": str(e), "logs": logs}

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"docker_volumes_{timestamp}.tar.gz"
    remote_path = f"{work_dir_v}/{filename}"
    work_dir_q = shlex.quote(work_dir_v)
    remote_path_q = shlex.quote(remote_path)

    try:
        await run_remote_command(server, f"mkdir -p {work_dir_q}")

        if volumes:
            volume_paths_q = " ".join(shlex.quote(f"/var/lib/docker/volumes/{v}") for v in volumes)
        else:
            volume_paths_q = shlex.quote("/var/lib/docker/volumes")

        log("info", f"Archiving Docker volumes: {volume_paths_q}")
        cmd = f"tar -czf {remote_path_q} {volume_paths_q}"
        exit_code, stdout, stderr = await run_remote_command(server, cmd, timeout=3600)

        sudo_err = _check_sudo_failure(stderr)
        if sudo_err:
            log("error", sudo_err)
            raise Exception(sudo_err)

        if exit_code != 0:
            log("error", f"tar failed: {stderr}")
            raise Exception(f"tar failed: {stderr}")

        exit_code, stdout, _ = await run_remote_command(server, f"stat -c %s {remote_path_q}")
        size_bytes = int(stdout.strip()) if exit_code == 0 else 0

        exit_code, stdout, _ = await run_remote_command(server, f"sha256sum {remote_path_q}")
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
    logs = []

    def log(level: str, msg: str):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg}
        logs.append(entry)

    try:
        paths_raw = config.get("paths", []) or []
        excludes_raw = config.get("excludes", []) or []
        paths = [_safe_path(p, "source path") for p in paths_raw]
        # Excludes are tar glob patterns — restrict to a slightly wider
        # but still printable-ASCII subset.
        for e in excludes_raw:
            if not re.fullmatch(r"[A-Za-z0-9_./*?\-+@: ]{1,256}", str(e)):
                raise ValueError(f"Invalid exclude pattern: {e!r}")
        excludes = [str(e) for e in excludes_raw]
        work_dir_v = _safe_path(work_dir, "work_dir")
    except ValueError as e:
        log("error", str(e))
        return {"success": False, "error": str(e), "logs": logs}

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"files_{timestamp}.tar.gz"
    remote_path = f"{work_dir_v}/{filename}"
    work_dir_q = shlex.quote(work_dir_v)
    remote_path_q = shlex.quote(remote_path)

    try:
        await run_remote_command(server, f"mkdir -p {work_dir_q}")

        exclude_flags = " ".join(f"--exclude={shlex.quote(e)}" for e in excludes)
        path_str_q = " ".join(shlex.quote(p) for p in paths)
        cmd = f"tar -czf {remote_path_q} {exclude_flags} {path_str_q}"

        log("info", f"Archiving files: {path_str_q}")
        log("info", f"Work dir: {work_dir_v} → {remote_path}")
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

        exit_code, stdout, stderr = await run_remote_command(server, f"stat -c %s {remote_path_q}")
        if exit_code != 0:
            log("warn", f"stat failed (exit {exit_code}): {stderr}")
        size_bytes = int(stdout.strip()) if exit_code == 0 and stdout.strip().isdigit() else 0

        exit_code, stdout, stderr = await run_remote_command(server, f"sha256sum {remote_path_q}")
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
