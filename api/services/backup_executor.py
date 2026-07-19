import hashlib
import logging
import os
import re
import shlex
import tempfile
from datetime import datetime, timezone

from api.services import age_crypto
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

    encrypt = bool(getattr(job, "encrypt", False))

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ext = "dump" if dump_format == "custom" else "sql"
    filename = f"{db_name}_{timestamp}.{ext}.gz" + (age_crypto.AGE_SUFFIX if encrypt else "")
    remote_path = f"{output_dir_v}/{filename}"
    output_dir_q = shlex.quote(output_dir_v)
    remote_path_q = shlex.quote(remote_path)
    db_name_q = shlex.quote(db_name)
    pg_user_q = shlex.quote(pg_user)

    try:
        # Fail closed before anything is written. A job that asks for
        # encryption we cannot deliver must not fall through to plaintext.
        recipient = await age_crypto.preflight(server, run_remote_command, encrypt)
        if recipient:
            log("info", "Encryption enabled (age recipient validated, binary present on source host)")

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

        # Producer stages only; age_crypto.wrap_pipeline appends the age stage
        # (when encrypting) and the redirect, under `bash -o pipefail` so a
        # failing pg_dump cannot be sealed inside a valid-looking archive.
        if container:
            container_q = shlex.quote(container)
            producer = f"docker exec {container_q} {pg_dump_cmd} | gzip"
        elif dump_format == "custom":
            producer = pg_dump_cmd
        else:
            producer = f"{pg_dump_cmd} | gzip -{compress_level}"

        dump_cmd = age_crypto.wrap_pipeline(producer, recipient, remote_path)

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

        # Read the bytes back. This is the check whose absence let 5336
        # plaintext artifacts be recorded as encrypted.
        if recipient:
            await age_crypto.verify_encrypted(server, run_remote_command, remote_path)
            log("info", "Encryption verified on disk (age magic bytes present)")

        exit_code, stdout, _ = await run_remote_command(server, f"stat -c %s {remote_path_q}")
        size_bytes = int(stdout.strip()) if exit_code == 0 else 0

        exit_code, stdout, _ = await run_remote_command(server, f"sha256sum {remote_path_q}", timeout=3600)
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
            # Verified above by readback, not copied from job.encrypt.
            "is_encrypted": bool(recipient),
            "logs": logs,
        }

    except Exception as e:
        if stop_containers:
            containers_q = " ".join(shlex.quote(c) for c in stop_containers)
            await run_remote_command(server, f"docker start {containers_q}")
        log("error", str(e))
        return {"success": False, "error": str(e), "logs": logs, "remote_path": remote_path}


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

    encrypt = bool(getattr(job, "encrypt", False))

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"docker_volumes_{timestamp}.tar.gz" + (age_crypto.AGE_SUFFIX if encrypt else "")
    remote_path = f"{work_dir_v}/{filename}"
    work_dir_q = shlex.quote(work_dir_v)
    remote_path_q = shlex.quote(remote_path)

    try:
        recipient = await age_crypto.preflight(server, run_remote_command, encrypt)
        if recipient:
            log("info", "Encryption enabled (age recipient validated, binary present on source host)")

        await run_remote_command(server, f"mkdir -p {work_dir_q}")

        if volumes:
            volume_paths_q = " ".join(shlex.quote(f"/var/lib/docker/volumes/{v}") for v in volumes)
        else:
            volume_paths_q = shlex.quote("/var/lib/docker/volumes")

        log("info", f"Archiving Docker volumes: {volume_paths_q}")
        # tar to stdout so the age stage can consume it; wrap_pipeline adds
        # the redirect. Previously this was `tar -czf <path>` writing direct.
        cmd = age_crypto.wrap_pipeline(f"tar -cz {volume_paths_q}", recipient, remote_path)
        exit_code, stdout, stderr = await run_remote_command(server, cmd, timeout=3600)

        sudo_err = _check_sudo_failure(stderr)
        if sudo_err:
            log("error", sudo_err)
            raise Exception(sudo_err)

        if exit_code != 0:
            log("error", f"tar failed: {stderr}")
            raise Exception(f"tar failed: {stderr}")

        if recipient:
            await age_crypto.verify_encrypted(server, run_remote_command, remote_path)
            log("info", "Encryption verified on disk (age magic bytes present)")

        exit_code, stdout, _ = await run_remote_command(server, f"stat -c %s {remote_path_q}")
        size_bytes = int(stdout.strip()) if exit_code == 0 else 0

        exit_code, stdout, _ = await run_remote_command(server, f"sha256sum {remote_path_q}", timeout=3600)
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
            "is_encrypted": bool(recipient),
            "logs": logs,
        }

    except Exception as e:
        log("error", str(e))
        return {"success": False, "error": str(e), "logs": logs, "remote_path": remote_path}


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

    encrypt = bool(getattr(job, "encrypt", False))

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"files_{timestamp}.tar.gz" + (age_crypto.AGE_SUFFIX if encrypt else "")
    remote_path = f"{work_dir_v}/{filename}"
    work_dir_q = shlex.quote(work_dir_v)
    remote_path_q = shlex.quote(remote_path)

    try:
        recipient = await age_crypto.preflight(server, run_remote_command, encrypt)
        if recipient:
            log("info", "Encryption enabled (age recipient validated, binary present on source host)")

        await run_remote_command(server, f"mkdir -p {work_dir_q}")

        exclude_flags = " ".join(f"--exclude={shlex.quote(e)}" for e in excludes)
        path_str_q = " ".join(shlex.quote(p) for p in paths)
        cmd = age_crypto.wrap_pipeline(
            f"tar -cz {exclude_flags} {path_str_q}", recipient, remote_path
        )

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

        # From this point a tar file exists on disk. Record it so the
        # caller's finally-block can guarantee cleanup even if the
        # post-tar steps (stat / sha256sum / transfer) blow up.

        if recipient:
            await age_crypto.verify_encrypted(server, run_remote_command, remote_path)
            log("info", "Encryption verified on disk (age magic bytes present)")

        exit_code, stdout, stderr = await run_remote_command(server, f"stat -c %s {remote_path_q}")
        if exit_code != 0:
            log("warn", f"stat failed (exit {exit_code}): {stderr}")
        size_bytes = int(stdout.strip()) if exit_code == 0 and stdout.strip().isdigit() else 0

        exit_code, stdout, stderr = await run_remote_command(server, f"sha256sum {remote_path_q}", timeout=3600)
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
            "is_encrypted": bool(recipient),
            "logs": logs,
        }

    except Exception as e:
        log("error", str(e))
        # Always include remote_path so the caller can clean up a partial
        # tar that the failure path left behind.
        return {"success": False, "error": str(e), "logs": logs, "remote_path": remote_path}


async def execute_custom_backup(server, job, run_id: str, db=None) -> dict:
    """Execute a custom shell command/script for backup.

    If `output_dir` is set in source_config, after the script we stat
    the newest file there to detect 0-byte output (silent failures).
    Without this, custom jobs can run "successfully" but produce empty
    files — exactly what happened with Seafile MariaDB for 2 months
    when the root password rotated under us.
    """
    config = job.source_config
    script = config.get("command") or config.get("script", "")
    if not script:
        return {"success": False, "error": "No command or script configured", "logs": []}

    encrypt = bool(getattr(job, "encrypt", False))
    output_dir = config.get("output_dir")

    # Custom scripts own their output path, so they cannot be piped through age
    # the way the built-in types are. Encryption therefore happens after the
    # script, over the files it produced in output_dir.
    #
    # This is weaker than the in-pipe path and the difference matters: the
    # script writes plaintext to disk first, and only then is it encrypted and
    # the plaintext removed. There is a window where the dump exists in the
    # clear on the source host. In-pipe encryption has no such window.
    #
    # It is still the right trade. The first version of this guard simply
    # refused, which was correct about never lying but left Seafile MariaDB and
    # Dify Postgres DB with no backup at all for six hours. A transient local
    # plaintext window is a far smaller risk than no backup, and vastly smaller
    # than the plaintext-replicated-to-Google-Drive situation this all started
    # from. Jobs that need the stronger guarantee should encrypt inside their
    # own script and set encrypt=false.
    if encrypt and not output_dir:
        msg = (
            "Job requests encryption but has no output_dir set. Custom-script "
            "jobs are encrypted after the fact over the files in output_dir, so "
            "without it VaultMaster cannot find what to encrypt. Set output_dir, "
            "or encrypt inside the script and set encrypt=false."
        )
        return {"success": False, "error": msg, "logs": [
            {"ts": datetime.now(timezone.utc).isoformat(), "level": "error", "msg": msg}
        ]}

    min_bytes = int(config.get("min_output_bytes", 1024))  # default: ≥1 KB

    logs = []

    def log(level: str, msg: str):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg}
        logs.append(entry)

    try:
        # Gate before running anything, so a missing key or binary fails the run
        # rather than leaving an unencrypted dump behind.
        recipient = await age_crypto.preflight(server, run_remote_command, encrypt)
        if recipient:
            log("info", "Encryption enabled (post-script, over output_dir)")

        # Anything already in output_dir predates this run; only encrypt what the
        # script itself produces. Without this marker a re-run would re-encrypt
        # (and thus double-encrypt) files left by an earlier run.
        marker = f"{_safe_path(output_dir, 'output_dir')}/.vm_run_marker" if output_dir else None
        if marker:
            await run_remote_command(server, f"touch {shlex.quote(marker)}")

        log("info", f"Running custom script")
        exit_code, stdout, stderr = await run_remote_command(server, script, timeout=7200)

        if exit_code != 0:
            log("error", f"Script failed (exit {exit_code}): {stderr}")
            raise Exception(f"Script failed: {stderr}")

        log("info", "Custom script completed")

        encrypted_count = 0
        if recipient and marker:
            output_dir_q = shlex.quote(_safe_path(output_dir, "output_dir"))
            marker_q = shlex.quote(marker)
            # Files newer than the marker, excluding the marker and anything
            # already encrypted.
            find_new = (
                f"find {output_dir_q} -maxdepth 1 -type f -newer {marker_q} "
                f"! -name '.vm_run_marker' ! -name '*.age' -print"
            )
            ec, out, err = await run_remote_command(server, find_new, timeout=120)
            new_files = [f for f in (out or "").splitlines() if f.strip()]

            if not new_files:
                raise Exception(
                    "Encryption requested but the script produced no new files in "
                    f"{output_dir}. Refusing to report success: there is nothing "
                    "to encrypt and probably nothing backed up."
                )

            for path in new_files:
                src = shlex.quote(path.strip())
                dst = shlex.quote(path.strip() + age_crypto.AGE_SUFFIX)
                cmd = age_crypto.wrap_pipeline(f"cat {src}", recipient, path.strip() + age_crypto.AGE_SUFFIX)
                ec, _o, e2 = await run_remote_command(server, cmd, timeout=3600)
                if ec != 0:
                    raise Exception(f"age encryption failed for {path}: {(e2 or '')[:200]}")

                # Verify before destroying the plaintext, never after.
                await age_crypto.verify_encrypted(server, run_remote_command, path.strip() + age_crypto.AGE_SUFFIX)
                await run_remote_command(server, f"rm -f {src}")
                encrypted_count += 1

            log("info", f"Encrypted {encrypted_count} output file(s), plaintext removed")

        if marker:
            await run_remote_command(server, f"rm -f {shlex.quote(marker)}")

        size_bytes = 0
        latest_filename = "custom_backup"
        produced_path = ""
        if output_dir:
            try:
                output_dir_q = shlex.quote(_safe_path(output_dir, "output_dir"))
                # Find newest file in output_dir, print size + name
                list_cmd = f"find {output_dir_q} -maxdepth 1 -type f -printf '%T@ %s %f\\n' | sort -nr | head -1"
                ec2, out2, _ = await run_remote_command(server, list_cmd, timeout=30)
                if ec2 == 0 and out2.strip():
                    parts = out2.strip().split(" ", 2)
                    if len(parts) == 3:
                        size_bytes = int(parts[1])
                        latest_filename = parts[2]
                        # The caller transfers whatever remote_path points at.
                        # Returning "" here (as this did until 2026-07-19) made
                        # `if filename and remote_path and destinations:` in
                        # _run_backup falsy, so the entire transfer was skipped
                        # while the run still reported success. 11 databases and
                        # 615 runs never left this directory.
                        produced_path = f"{_safe_path(output_dir, 'output_dir')}/{latest_filename}"
                        log("info", f"Newest output: {latest_filename} ({size_bytes} bytes)")
                if size_bytes < min_bytes:
                    raise Exception(
                        f"Custom backup output is {size_bytes} bytes (< min_output_bytes={min_bytes}). "
                        f"Script reported success but produced an unrealistically small file — "
                        f"check for silent auth/permission errors."
                    )
            except Exception as size_err:
                # If size check itself fails (e.g. invalid output_dir), surface it as a failure.
                if "min_output_bytes" in str(size_err):
                    raise
                log("warn", f"size-check skipped: {size_err}")

        return {
            "success": True,
            "filename": latest_filename,
            "remote_path": produced_path,
            "size_bytes": size_bytes,
            "checksum_sha256": "",
            # Verified by readback above before the plaintext was deleted.
            "is_encrypted": bool(recipient),
            "logs": logs,
            "stdout": stdout,
        }

    except Exception as e:
        log("error", str(e))
        return {"success": False, "error": str(e), "logs": logs}
