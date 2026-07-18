"""Backup restore-validator.

Verifies that a backup is actually restorable. The 2026-05-01 incident
showed that completion-status alone is not enough — the seafile job had
been "running" for months without producing usable output.

Strategy per backup_type:

  postgresql       Spin up a temp postgres:16-alpine container, pg_restore
                   the dump into a fresh DB, run a smoke query
                   (SELECT count(*) FROM pg_class WHERE relkind='r'),
                   tear down the container.

  files            tar -tzf to list contents (without extracting). Pass if
                   it lists at least one file and reports no error. Cheap
                   sanity check — proves the archive isn't truncated.

  restic           `restic check --read-data-subset=<pct>%` against a
                   sampled fraction of the repo. Restic is content-addressed
                   so the integrity check is cryptographic.

  docker_volumes   tar -tzf same as files (volume archives are tar.gz).

  custom           Skipped (unknown contents). status='skipped'.

Each validation runs in its own isolated work directory under /tmp/vm-validate
and cleans up on exit, including failure paths.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from api.services import age_crypto

logger = logging.getLogger(__name__)

POSTGRES_IMAGE = "postgres:16-alpine"
TEMP_DB = "vmverify"
TEMP_USER = "postgres"
TEMP_PASSWORD = "vmverify-temp-password"


async def _decrypt_if_needed(local_path: str, log) -> str:
    """Decrypt an age-encrypted artifact in place, returning the usable path.

    Dispatches on the file's actual magic bytes rather than artifact.is_encrypted,
    because that column lied for every artifact written before 2026-07-19 (5336
    rows claimed encryption that never happened). Reading the bytes works for
    both the old plaintext artifacts and the new encrypted ones, which is what
    lets validation span the changeover without special-casing.
    """
    if not age_crypto.file_is_age_encrypted(local_path):
        return local_path

    if local_path.endswith(age_crypto.AGE_SUFFIX):
        decrypted = local_path[: -len(age_crypto.AGE_SUFFIX)]
    else:
        decrypted = f"{local_path}.decrypted"

    log("info", "Artifact is age-encrypted, decrypting with configured identity")
    await age_crypto.decrypt_local_file(local_path, decrypted, _run)

    try:
        os.remove(local_path)
    except OSError:
        pass

    log("info", f"Decrypted to {os.path.basename(decrypted)} ({os.path.getsize(decrypted)} bytes)")
    return decrypted


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run(cmd: list[str], timeout: int = 600) -> tuple[int, str, str]:
    """Run a subprocess, return (exit, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", "TIMEOUT"
    return proc.returncode or 0, stdout_b.decode(errors="replace"), stderr_b.decode(errors="replace")


async def _download_artifact_to_temp(artifact, dest_path: str) -> tuple[bool, str]:
    """Download an artifact from its storage_destination to a local file.

    Uses a per-call engine so this works correctly from Celery tasks
    that own their own event loop. Sharing api.database.async_session
    across loops triggers asyncpg "another operation is in progress".
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from api.config import get_settings
    from api.models.storage_destination import StorageDestination
    from api.services.rclone_client import download_file_from_storage

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False, pool_size=2, max_overflow=2)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            result = await db.execute(select(StorageDestination).where(StorageDestination.id == artifact.storage_id))
            dest = result.scalar_one_or_none()
            if not dest:
                return False, f"storage destination {artifact.storage_id} not found"
    finally:
        await engine.dispose()

    return await download_file_from_storage(dest, artifact.remote_path, dest_path)


async def validate_postgresql_artifact(job, artifact) -> dict:
    """Restore a postgres dump into a temp container and run a smoke query."""
    logs: list[dict] = []

    def log(level: str, msg: str) -> None:
        logs.append({"ts": _now(), "level": level, "msg": msg})

    if not artifact:
        return {"status": "skipped", "error": "no artifact to validate", "logs": logs}

    # Bug #18: full UUID (no truncation) prevents collisions when two
    # validations run for artifacts that happen to share the first 8 chars.
    # Defensive `docker rm -f` before `docker run` covers the edge case where
    # a stale container with the exact same name still exists from a
    # previously-killed validation (rare but observed in tests).
    container_name = f"vm-validate-{artifact.id}"
    workdir = tempfile.mkdtemp(prefix="vm-validate-")
    local_dump = os.path.join(workdir, artifact.filename or "dump.gz")

    try:
        log("info", f"Downloading artifact {artifact.filename} from storage")
        ok, msg = await _download_artifact_to_temp(artifact, local_dump)
        if not ok:
            log("error", f"download failed: {msg}")
            return {"status": "failed", "error": f"download failed: {msg}", "logs": logs}

        size = os.path.getsize(local_dump) if os.path.isfile(local_dump) else 0
        log("info", f"Downloaded {size} bytes to {local_dump}")
        if size == 0:
            return {"status": "failed", "error": "downloaded artifact is 0 bytes", "logs": logs}

        # Must happen before the workdir is mounted into the temp container:
        # pg_restore cannot read an age file.
        local_dump = await _decrypt_if_needed(local_dump, log)

        # Defensive cleanup of any stale container with the same name.
        # `docker rm -f` exits non-zero if it doesn't exist — that's fine,
        # we ignore the rc and only care about the subsequent `run`.
        await _run(["docker", "rm", "-f", container_name], timeout=15)

        log("info", f"Starting temp postgres container: {container_name}")
        code, _, stderr = await _run([
            "docker", "run", "--rm", "-d",
            "--name", container_name,
            "-e", f"POSTGRES_DB={TEMP_DB}",
            "-e", f"POSTGRES_USER={TEMP_USER}",
            "-e", f"POSTGRES_PASSWORD={TEMP_PASSWORD}",
            "-v", f"{workdir}:/dump:ro",
            POSTGRES_IMAGE,
        ], timeout=120)
        if code != 0:
            log("error", f"docker run failed (exit {code}): {stderr.strip()[:300]}")
            return {"status": "failed", "error": f"could not start temp container: {stderr.strip()[:200]}", "logs": logs}

        for attempt in range(30):
            code, _, _ = await _run([
                "docker", "exec", container_name,
                "pg_isready", "-U", TEMP_USER, "-d", TEMP_DB,
            ], timeout=10)
            if code == 0:
                break
            await asyncio.sleep(1)
        else:
            log("error", "postgres did not become ready within 30s")
            return {"status": "failed", "error": "postgres did not become ready", "logs": logs}

        log("info", "postgres ready, restoring dump")

        in_container = f"/dump/{os.path.basename(local_dump)}"
        if local_dump.endswith(".dump.gz") or local_dump.endswith(".gz"):
            restore_cmd = (
                f"gunzip -c {shlex.quote(in_container)} | "
                f"pg_restore -U {TEMP_USER} -d {TEMP_DB} --no-owner --no-acl 2>&1 || "
                f"gunzip -c {shlex.quote(in_container)} | "
                f"psql -U {TEMP_USER} -d {TEMP_DB} 2>&1"
            )
        elif local_dump.endswith(".dump"):
            restore_cmd = f"pg_restore -U {TEMP_USER} -d {TEMP_DB} --no-owner --no-acl {shlex.quote(in_container)} 2>&1"
        elif local_dump.endswith(".sql"):
            restore_cmd = f"psql -U {TEMP_USER} -d {TEMP_DB} -f {shlex.quote(in_container)} 2>&1"
        else:
            log("warn", f"unknown dump extension, trying pg_restore: {local_dump}")
            restore_cmd = f"pg_restore -U {TEMP_USER} -d {TEMP_DB} --no-owner --no-acl {shlex.quote(in_container)} 2>&1"

        code, stdout, stderr = await _run([
            "docker", "exec", container_name,
            "sh", "-c", restore_cmd,
        ], timeout=3600)

        out = (stdout or stderr or "").strip()
        if code != 0:
            log("error", f"restore failed (exit {code}): {out[:500]}")
            return {"status": "failed", "error": f"pg_restore exit {code}", "logs": logs}

        # Smoke query: count user tables. >0 means schema landed.
        log("info", "restore finished, running smoke query")
        code, stdout, stderr = await _run([
            "docker", "exec", container_name,
            "psql", "-U", TEMP_USER, "-d", TEMP_DB, "-tAc",
            "SELECT count(*) FROM pg_class WHERE relkind='r' AND relnamespace IN "
            "(SELECT oid FROM pg_namespace WHERE nspname NOT IN ('pg_catalog','information_schema'))",
        ], timeout=60)
        if code != 0:
            log("error", f"smoke query failed: {stderr.strip()[:200]}")
            return {"status": "failed", "error": f"smoke query exit {code}", "logs": logs}

        try:
            table_count = int((stdout or "").strip() or "0")
        except ValueError:
            table_count = 0
        log("info", f"smoke query passed: {table_count} user tables present")

        if table_count == 0:
            log("warn", "0 user tables — restore may be empty; treating as failed")
            return {"status": "failed", "error": "restored DB has 0 user tables", "logs": logs}

        return {
            "status": "passed",
            "error": None,
            "logs": logs,
            "metadata": {"user_tables": table_count, "artifact_size_bytes": size},
        }

    finally:
        await _run(["docker", "stop", container_name], timeout=30)
        if os.path.isfile(local_dump):
            try:
                os.remove(local_dump)
            except OSError:
                pass
        try:
            os.rmdir(workdir)
        except OSError:
            pass


async def validate_files_artifact(job, artifact) -> dict:
    """Smoke-test a tar.gz artifact by listing contents."""
    logs: list[dict] = []

    def log(level: str, msg: str) -> None:
        logs.append({"ts": _now(), "level": level, "msg": msg})

    if not artifact:
        return {"status": "skipped", "error": "no artifact to validate", "logs": logs}

    workdir = tempfile.mkdtemp(prefix="vm-validate-")
    local_path = os.path.join(workdir, artifact.filename or "archive.tar.gz")
    try:
        log("info", f"Downloading {artifact.filename}")
        ok, msg = await _download_artifact_to_temp(artifact, local_path)
        if not ok:
            return {"status": "failed", "error": f"download failed: {msg}", "logs": logs}

        size = os.path.getsize(local_path) if os.path.isfile(local_path) else 0
        if size == 0:
            return {"status": "failed", "error": "downloaded archive is 0 bytes", "logs": logs}

        # tar cannot read an age file. Reassigning local_path also keeps the
        # finally-block cleanup pointed at the file that actually exists.
        local_path = await _decrypt_if_needed(local_path, log)
        size = os.path.getsize(local_path)

        log("info", f"tar -tzf check on {size} bytes")
        code, stdout, stderr = await _run(["tar", "-tzf", local_path], timeout=600)
        if code != 0:
            log("error", f"tar list failed (exit {code}): {stderr.strip()[:200]}")
            return {"status": "failed", "error": f"tar -tzf exit {code}", "logs": logs}

        n = sum(1 for _ in (stdout or "").splitlines())
        log("info", f"archive contains {n} entries")
        if n == 0:
            return {"status": "failed", "error": "archive contains 0 entries", "logs": logs}

        return {"status": "passed", "error": None, "logs": logs, "metadata": {"entries": n, "size_bytes": size}}
    finally:
        if os.path.isfile(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
        try:
            os.rmdir(workdir)
        except OSError:
            pass


async def validate_restic_job(job, server, snapshot_id: str | None = None) -> dict:
    """Run `restic check --read-data-subset` for a restic-backed job."""
    from api.services.ssh_client import run_remote_command

    logs: list[dict] = []

    def log(level: str, msg: str) -> None:
        logs.append({"ts": _now(), "level": level, "msg": msg})

    config = job.source_config or {}
    repo_url = config.get("repo_url")
    password_env = config.get("password_env_var", "RESTIC_PASSWORD")
    if not repo_url:
        return {"status": "skipped", "error": "no repo_url in source_config", "logs": logs}

    repo_q = shlex.quote(repo_url)
    env_prefix = (
        f"export RESTIC_REPOSITORY={repo_q}; "
        f'export RESTIC_PASSWORD="${{{password_env}}}"; '
        f'if [ -z "$RESTIC_PASSWORD" ]; then echo "RESTIC_PASSWORD env not set" >&2; exit 7; fi;'
    )

    log("info", f"restic check on {repo_url}")
    cmd = f"{env_prefix} restic check --no-lock --read-data-subset=1%"
    code, stdout, stderr = await run_remote_command(server, cmd, timeout=3600)
    if code != 0:
        log("error", f"restic check failed (exit {code}): {(stderr or '').strip()[:300]}")
        return {"status": "failed", "error": f"restic check exit {code}", "logs": logs}

    log("info", "restic check passed")
    return {"status": "passed", "error": None, "logs": logs, "metadata": {"repo_url": repo_url}}


async def run_validation(job, artifact=None, server=None, check_type: str = "restore") -> dict:
    """Dispatch to the right validator for the job's backup_type."""
    bt = (job.backup_type or "").lower()
    if bt == "postgresql":
        return await validate_postgresql_artifact(job, artifact)
    if bt in ("files", "docker_volumes"):
        return await validate_files_artifact(job, artifact)
    if bt == "restic":
        snap_id = (artifact and getattr(artifact, "checksum_sha256", None)) or None
        return await validate_restic_job(job, server, snap_id)
    return {"status": "skipped", "error": f"backup_type '{bt}' not validatable", "logs": []}
