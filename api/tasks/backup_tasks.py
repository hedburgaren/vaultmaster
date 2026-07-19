import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from api.tasks.celery_app import celery_app
from api.config import get_settings

logger = logging.getLogger(__name__)


def summarise_transfers(results: list[tuple[str, bool]]) -> dict:
    """Decide what a set of per-destination transfer outcomes actually means.

    Extracted so the decision is testable on its own. Until 2026-07-19 it was
    inline and wrong: a failed transfer was logged, the artifact row was created
    anyway pointing at the SOURCE temp path, and the temp file was then deleted
    unconditionally. The backup existed in neither place and the run said
    'success'.

    `safe_to_delete_source` is deliberately strict. The source copy may only go
    once EVERY destination has its own copy. A partial success still needs the
    source, because the destination that failed has to be retried from
    somewhere. Keeping a temp file costs disk; deleting it too early costs the
    backup.
    """
    if not results:
        return {"any_ok": False, "all_ok": False, "safe_to_delete_source": False,
                "ok_count": 0, "total": 0, "failed": []}

    ok_count = sum(1 for _, ok in results if ok)
    failed = [dest for dest, ok in results if not ok]
    all_ok = ok_count == len(results)
    return {
        "any_ok": ok_count > 0,
        "all_ok": all_ok,
        "safe_to_delete_source": all_ok,
        "ok_count": ok_count,
        "total": len(results),
        "failed": failed,
    }


def withdraw_from_cleanup(entries: list, server, path: str) -> list:
    """Remove one (server, path) pair from the guaranteed-cleanup list.

    The finally block in _run_backup deletes every registered temp file no
    matter how the run ended, which is correct for the normal case: an orphaned
    temp file would otherwise leak forever.

    It is wrong for the one case where the temp file is the only surviving copy.
    When a destination fails, the source must be kept so the transfer can be
    retried, and that decision has to physically withdraw the file from the
    cleanup list. An earlier version only logged its intention and let the
    finally block delete the file anyway, so the log claimed the source was
    preserved while it was being removed. Announcing a decision is not the same
    as taking it.
    """
    return [(s, p) for (s, p) in entries if not (s is server and p == path)]


def file_is_free(fuser_rc: int | None) -> bool:
    """True only when `fuser` positively reported the file as unused.

    `fuser -s` exits 0 when a file IS in use and 1 when it is not. Every other
    exit code means the check itself did not work: 127 for a missing binary,
    126 for permission denied, and so on. Treating those as "not in use" (which
    is what the code did until 2026-07-19) silently disarms the guard protecting
    in-flight backup files, so a host without `fuser` installed would delete
    archives mid-write.

    Anything other than a clean rc=1 is treated as unknown, and unknown means
    do not delete.
    """
    return fuser_rc == 1


def _run_async(coro):
    """Helper to run async code from sync Celery tasks."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@asynccontextmanager
async def get_task_session():
    """Create a fresh async engine + session per task invocation.

    This avoids the asyncpg 'another operation is in progress' error
    caused by sharing the global engine across different event loops.
    """
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=3,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
    await engine.dispose()


@celery_app.task(bind=True, name="api.tasks.backup_tasks.run_backup_task", max_retries=3)
def run_backup_task(self, job_id: str, triggered_by: str = "manual"):
    """Execute a backup job."""
    _run_async(_run_backup(self, job_id, triggered_by))


async def _run_backup(task, job_id: str, triggered_by: str = "manual"):
    from sqlalchemy import select, text
    from api.models.backup_job import BackupJob
    from api.models.backup_run import BackupRun
    from api.models.server import Server
    from api.models.backup_artifact import BackupArtifact
    from api.services.backup_executor import (
        execute_postgresql_backup,
        execute_docker_volumes_backup,
        execute_files_backup,
        execute_custom_backup,
    )
    from api.services.restic_executor import execute_restic_backup

    async with get_task_session() as db:
        # Advisory lock per job_id — prevents two concurrent task deliveries
        # from racing on the same backup job (visibility_timeout redelivery,
        # manual + scheduler overlap, etc). Transaction-level lock — released
        # automatically at the next commit/rollback. NOTE: this guards the
        # initial run-record creation only; if duplicate prevention is needed
        # for the entire job duration, switch to pg_try_advisory_lock (session)
        # plus an explicit pg_advisory_unlock in the finally-block.
        job_uuid = uuid.UUID(job_id)
        lock_key = int.from_bytes(job_uuid.bytes[:8], "big", signed=True)
        got_lock = (await db.execute(
            text("SELECT pg_try_advisory_xact_lock(:k)").bindparams(k=lock_key)
        )).scalar()
        if not got_lock:
            logger.warning(f"Job {job_id} already running (advisory lock held), skipping duplicate task")
            return

        # Load job and server
        result = await db.execute(select(BackupJob).where(BackupJob.id == uuid.UUID(job_id)))
        job = result.scalar_one_or_none()
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        result = await db.execute(select(Server).where(Server.id == job.server_id))
        server = result.scalar_one_or_none()
        if not server:
            logger.error(f"Server {job.server_id} not found for job {job_id}")
            return

        # Create run record. Capture the Celery task id so the cancel-
        # endpoint can issue a control.revoke(...) instead of only flipping
        # DB status — bug #12. `task.request.id` is set by Celery for every
        # bound task; manual instantiations (no .delay/.apply_async) won't
        # have one, hence the getattr-with-default.
        celery_task_id = None
        try:
            celery_task_id = getattr(getattr(task, "request", None), "id", None)
        except Exception:
            pass
        run = BackupRun(
            job_id=job.id,
            server_id=server.id,
            status="running",
            started_at=datetime.now(timezone.utc),
            triggered_by=triggered_by,
            celery_task_id=celery_task_id,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        # Track temp files we create so we can guarantee cleanup even on
        # exception, retry, or worker kill. The orphaned-1.6 TB incident
        # 2026-05-02 happened because the cleanup at the end of the success
        # path never ran when the task was redelivered or killed mid-flight.
        temp_files_to_clean: list[tuple[object, str]] = []  # (server, remote_path)

        try:
            # Execute based on backup type
            executors = {
                "postgresql": execute_postgresql_backup,
                "docker_volumes": execute_docker_volumes_backup,
                "files": execute_files_backup,
                "custom": execute_custom_backup,
                "restic": execute_restic_backup,
            }

            executor = executors.get(job.backup_type)
            if not executor:
                raise Exception(f"Unknown backup type: {job.backup_type}")

            result_data = await executor(server, job, str(run.id), db=db)
            # Register the temp file produced by the executor (if any) so
            # the finally-block can guarantee removal.
            rp = result_data.get("remote_path") if isinstance(result_data, dict) else None
            if rp and not result_data.get("skip_transfer"):
                temp_files_to_clean.append((server, rp))

            if result_data["success"]:
                run.status = "success"
                run.size_bytes = result_data.get("size_bytes", 0)
                run.log_lines = result_data.get("logs", [])
                run.finished_at = datetime.now(timezone.utc)

                # Restic and similar push-based executors handle their own
                # storage transfer + retention; skip the rclone path entirely.
                if result_data.get("skip_transfer"):
                    meta = result_data.get("metadata") or {}
                    if meta:
                        logger.info(f"[{run.id}] push-based backup metadata: {meta}")
                    await db.commit()

                    from api.services.notifier import notify_event
                    await notify_event(db, "run.success", {
                        "job_name": job.name,
                        "server_name": server.name,
                        "size_bytes": run.size_bytes,
                        "duration": str(run.finished_at - run.started_at) if run.finished_at and run.started_at else None,
                        "snapshot_id": meta.get("snapshot_id"),
                        "repo_url": meta.get("repo_url"),
                    })
                    return

                # --- Transfer file to storage destinations ---
                from api.models.storage_destination import StorageDestination
                from api.services.ssh_client import is_local_server, download_remote_file, delete_remote_file
                from api.services.rclone_client import copy_file_to_storage

                remote_path = result_data.get("remote_path", "")
                filename = result_data.get("filename", "")
                local_file = None  # path accessible inside container
                sftp_tmp = None    # temp file downloaded via SFTP (cleanup later)

                if filename and remote_path and (job.destination_ids or []):
                    # Resolve a container-accessible path to the backup file
                    if is_local_server(server):
                        # Localhost: file is on the Docker host.
                        # If work_dir is under a bind-mounted path it's directly accessible.
                        if os.path.isfile(remote_path):
                            local_file = remote_path
                            logger.info(f"[{run.id}] Local file accessible via bind-mount: {local_file}")
                        else:
                            # Bind-mount doesn't cover this path — download via SFTP
                            logger.info(f"[{run.id}] File not accessible locally, downloading via SFTP from host")
                            sftp_tmp = f"/tmp/{filename}"
                            ok, msg = await download_remote_file(server, remote_path, sftp_tmp)
                            if ok:
                                local_file = sftp_tmp
                            else:
                                logger.warning(f"[{run.id}] SFTP download failed: {msg}")
                    else:
                        # Remote server: always download via SFTP
                        logger.info(f"[{run.id}] Downloading backup from remote server via SFTP")
                        sftp_tmp = f"/tmp/{filename}"
                        ok, msg = await download_remote_file(server, remote_path, sftp_tmp)
                        if ok:
                            local_file = sftp_tmp
                        else:
                            logger.warning(f"[{run.id}] SFTP download failed: {msg}")

                    # Copy to each storage destination
                    transfer_results: list[tuple[str, bool]] = []
                    for dest_id in (job.destination_ids or []):
                        dest_result = await db.execute(
                            select(StorageDestination).where(StorageDestination.id == dest_id)
                        )
                        dest = dest_result.scalar_one_or_none()
                        if not dest:
                            logger.warning(f"[{run.id}] Storage destination {dest_id} not found")
                            continue
                        # Skip inactive destinations (e.g. expired OAuth)
                        # otherwise rclone hangs on the auth refresh and
                        # blocks the queue for the whole transfer timeout.
                        if not dest.is_active:
                            logger.info(f"[{run.id}] Skipping inactive destination {dest.name}")
                            continue

                        # Build sub-path: server_name/job_name/filename
                        sub_path = f"{server.name}/{job.name}/{filename}"
                        stored_path = ""
                        transferred = False

                        if local_file:
                            ok, msg = await copy_file_to_storage(dest, local_file, sub_path)
                            if ok:
                                # msg is the stored path now, not a sentence.
                                stored_path = msg
                                transferred = True
                                logger.info(f"[{run.id}] Transferred to {dest.name}: {msg}")
                            else:
                                logger.error(f"[{run.id}] Transfer to {dest.name} failed: {msg}")
                        else:
                            logger.error(
                                f"[{run.id}] No local file available for {dest.name}; "
                                f"nothing was transferred"
                            )

                        transfer_results.append((str(dest_id), transferred))

                        # Only record an artifact for a destination that actually
                        # received the file. Recording one for a failed transfer
                        # (which is what happened until 2026-07-19) tells restore
                        # a copy exists where none does.
                        if not transferred:
                            continue

                        artifact = BackupArtifact(
                            run_id=run.id,
                            storage_id=dest_id,
                            filename=filename,
                            remote_path=stored_path or remote_path,
                            size_bytes=result_data.get("size_bytes", 0),
                            checksum_sha256=result_data.get("checksum_sha256") or "pending",
                            is_encrypted=bool(result_data.get("is_encrypted", False)),
                            backup_type=job.backup_type,
                            tags=job.tags,
                            domain=job.domain,
                            db_name=job.source_config.get("db_name"),
                            server_name=server.name,
                        )
                        db.add(artifact)

                    # Cleanup: remove SFTP temp file
                    if sftp_tmp and os.path.isfile(sftp_tmp):
                        try:
                            os.remove(sftp_tmp)
                            logger.info(f"[{run.id}] Cleaned up temp file: {sftp_tmp}")
                        except OSError:
                            pass

                    # Cleanup: remove the source temp file ONLY once every
                    # destination has its own copy.
                    #
                    # This used to be an unconditional delete. Combined with the
                    # artifact row being written even for failed transfers, a
                    # failing destination produced: no copy at the destination,
                    # no copy at the source, an artifact claiming both, and a run
                    # marked 'success'. Total silent data loss, reported green.
                    summary = summarise_transfers(transfer_results)

                    if summary["safe_to_delete_source"]:
                        if remote_path:
                            await delete_remote_file(server, remote_path)
                            logger.info(f"[{run.id}] Cleaned up remote temp file: {remote_path}")
                    else:
                        # Withdraw it from the finally-block cleanup, otherwise
                        # this branch only logs an intention that the finally
                        # block then overrides.
                        temp_files_to_clean = withdraw_from_cleanup(
                            temp_files_to_clean, server, remote_path
                        )
                        logger.error(
                            f"[{run.id}] KEEPING source file {remote_path}: only "
                            f"{summary['ok_count']}/{summary['total']} destination(s) "
                            f"received it. Failed: {summary['failed']}. "
                            f"Withdrawn from temp cleanup so it can be retried."
                        )

                    # A run where nothing reached storage is not a success. The
                    # whole point of the job is the copy at the destination.
                    if not summary["any_ok"]:
                        raise Exception(
                            f"Backup produced a file but no destination accepted it "
                            f"(0/{summary['total']} transfers succeeded). The source "
                            f"copy has been kept at {remote_path}."
                        )
                    if not summary["all_ok"]:
                        # Local import: the module-level one above lives inside
                        # the skip_transfer branch, which does not run here.
                        from api.services.notifier import notify_event as _notify
                        await _notify(db, "backup.partial_transfer", {
                            "job_name": job.name,
                            "ok": summary["ok_count"],
                            "total": summary["total"],
                            "failed_destinations": ", ".join(summary["failed"]),
                        })

                elif filename:
                    # No destinations configured — just record artifacts without transfer
                    for dest_id in (job.destination_ids or []):
                        artifact = BackupArtifact(
                            run_id=run.id,
                            storage_id=dest_id,
                            filename=filename,
                            remote_path=remote_path,
                            size_bytes=result_data.get("size_bytes", 0),
                            checksum_sha256=result_data.get("checksum_sha256") or "pending",
                            is_encrypted=bool(result_data.get("is_encrypted", False)),
                            backup_type=job.backup_type,
                            tags=job.tags,
                            domain=job.domain,
                            db_name=job.source_config.get("db_name"),
                            server_name=server.name,
                        )
                        db.add(artifact)
                else:
                    logger.warning(f"[{run.id}] No filename in result — skipping artifact creation")

                # Apply rotation after successful backup — per destination
                from api.models.retention_policy import RetentionPolicy
                from api.services.rotation import apply_rotation
                overrides = job.retention_overrides or {}
                for dest_id in (job.destination_ids or []):
                    dest_str = str(dest_id)
                    # Use override policy if set, otherwise fall back to job default
                    policy_id = overrides.get(dest_str, str(job.retention_id) if job.retention_id else None)
                    if not policy_id:
                        continue
                    ret_result = await db.execute(
                        select(RetentionPolicy).where(RetentionPolicy.id == uuid.UUID(policy_id))
                    )
                    policy = ret_result.scalar_one_or_none()
                    if policy:
                        await apply_rotation(db, policy, str(job.id), storage_id=dest_str)

            else:
                error_msg = (result_data.get("error") or "Unknown error").strip()
                logs_list = result_data.get("logs", []) or []
                last_error_log = next(
                    (l for l in reversed(logs_list) if isinstance(l, dict) and l.get("level") == "error"),
                    None,
                )
                if last_error_log and last_error_log.get("msg"):
                    last_msg = str(last_error_log["msg"]).strip()
                    if last_msg and last_msg not in error_msg:
                        error_msg = f"{error_msg} | last log: {last_msg[:300]}"

                run.status = "failed"
                run.error_message = error_msg
                run.log_lines = logs_list
                run.finished_at = datetime.now(timezone.utc)

                # Retry if configured. Pass the concrete error as exc so
                # Celery's task message reflects what actually broke
                # instead of just "Retry in 60s".
                if run.retry_count < job.max_retries:
                    run.retry_count += 1
                    await db.commit()
                    countdown = 60 * run.retry_count
                    retry_label = f"[retry {run.retry_count}/{job.max_retries} in {countdown}s] {error_msg[:200]}"
                    logger.warning(f"[{run.id}] {retry_label}")
                    raise task.retry(exc=Exception(retry_label), countdown=countdown)

            await db.commit()

            # Send notifications
            from api.services.notifier import notify_event
            event = f"run.{run.status}"
            await notify_event(db, event, {
                "job_name": job.name,
                "server_name": server.name,
                "size_bytes": run.size_bytes,
                "error": run.error_message,
                "duration": str(run.finished_at - run.started_at) if run.finished_at and run.started_at else None,
            })

        except Exception as e:
            # Don't squash a Retry, let Celery handle it.
            from celery.exceptions import Retry
            if isinstance(e, Retry):
                raise
            run.status = "failed"
            run.error_message = f"{type(e).__name__}: {str(e)}"[:1000]
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error(f"Backup task failed for job {job_id}: {type(e).__name__}: {e}")
            # Notify on exception-path failures too. Previously notify_event
            # only fired on the normal-exit failure path (rad ~341), so any
            # backup that died via raised exception (ssh timeout, executor
            # crash, transfer error) silently skipped all configured channels.
            try:
                from api.services.notifier import notify_event
                await notify_event(db, "run.failed", {
                    "job_name": job.name,
                    "server_name": server.name,
                    "size_bytes": run.size_bytes,
                    "error": run.error_message,
                    "duration": str(run.finished_at - run.started_at) if run.finished_at and run.started_at else None,
                })
            except Exception as notify_err:
                logger.warning(f"[{run.id}] notify on exception-path failed: {notify_err}")
            raise

        finally:
            # Guaranteed temp-file cleanup. Runs whether the task succeeded,
            # failed, was killed, or got redelivered. If transfer succeeded
            # the file was already removed at the end of the success path —
            # delete_remote_file is tolerant of missing files.
            if temp_files_to_clean:
                from api.services.ssh_client import delete_remote_file
                for srv, path in temp_files_to_clean:
                    try:
                        await delete_remote_file(srv, path)
                        logger.info(f"[{run.id}] finally: cleaned temp file {path}")
                    except Exception as cleanup_err:
                        logger.warning(f"[{run.id}] finally: cleanup of {path} failed: {cleanup_err}")


@celery_app.task(name="api.tasks.backup_tasks.reap_stale_runs")
def reap_stale_runs():
    """Fail runs that have been 'running' far longer than any job could take.

    Added 2026-07-19 after two runs were orphaned by a worker recreation during
    their upload phase. A run whose worker dies keeps status='running' forever,
    and check_scheduled_jobs skips a job while a previous run is still in
    progress. So the job silently stops backing up: no failure, no alert, just
    absence. `Home: Chrille` (tagged critical) went unbacked-up for 8 hours
    that way, and PlastShop Odoo DB with it.

    Silence is the dangerous part. A stuck run must become a visible failure,
    because a failed backup gets noticed and a missing one does not.

    Time-based rather than heartbeat-based on purpose: a heartbeat needs the
    worker to be alive to report, which is exactly what is not true here. The
    threshold is deliberately generous (default 6h) since the longest real run
    is a 23 GB archive plus its upload.
    """
    return _run_async(_do_reap_stale_runs())


async def _do_reap_stale_runs():
    from datetime import timedelta

    from sqlalchemy import select

    from api.models.backup_job import BackupJob
    from api.models.backup_run import BackupRun
    from api.services.notifier import notify_event

    settings = get_settings()
    hours = int(getattr(settings, "stale_run_hours", 6) or 6)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with get_task_session() as db:
        stale = (await db.execute(
            select(BackupRun, BackupJob)
            .join(BackupJob, BackupJob.id == BackupRun.job_id)
            .where(BackupRun.status == "running", BackupRun.started_at < cutoff)
        )).all()

        if not stale:
            return {"reaped": 0}

        names = []
        for run, job in stale:
            age = datetime.now(timezone.utc) - run.started_at
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = (
                f"Abandoned: still 'running' after {age.total_seconds() / 3600:.1f}h "
                f"(threshold {hours}h). The worker executing it most likely died "
                f"mid-run. Marked failed so the schedule is released."
            )
            names.append(job.name)
            logger.warning(
                "reap_stale_runs: %s run %s abandoned after %.1fh, marked failed",
                job.name, run.id, age.total_seconds() / 3600,
            )

        await db.commit()
        await notify_event(db, "run.abandoned", {
            "count": len(stale),
            "jobs": ", ".join(sorted(set(names))),
            "threshold_hours": hours,
        })
        await db.commit()
        return {"reaped": len(stale), "jobs": names}


@celery_app.task(name="api.tasks.backup_tasks.run_restore_task")
def run_restore_task(artifact_id: str, target_server_id: str | None = None, target_db_name: str | None = None):
    """Restore a backup artifact into an explicitly named target database.

    Previously this was a stub that logged "queued" and returned, which is worse
    than not existing: a caller could reasonably believe a restore had happened.

    Restoring overwrites whatever is in the target, so the target is never
    inferred. Both target_server_id and target_db_name are required, and the
    task refuses to restore into the database the artifact was taken from unless
    that database is named explicitly. The intent is that you cannot clobber
    production by accident, only on purpose.

    Non-destructive verification lives in api.services.restore_validator, which
    restores into a throwaway container and is what the hourly validation sweep
    uses. Prefer that for "does this backup work?".
    """
    return _run_async(_run_restore(artifact_id, target_server_id, target_db_name))


async def _run_restore(artifact_id: str, target_server_id: str | None, target_db_name: str | None):
    import shlex
    import shutil
    import tempfile

    from sqlalchemy import select

    from api.models.backup_artifact import BackupArtifact
    from api.models.server import Server
    from api.services import age_crypto
    from api.services.restore_validator import _download_artifact_to_temp, _decrypt_if_needed, _run
    from api.services.ssh_client import run_remote_command

    logs: list[str] = []

    def log(msg: str) -> None:
        logs.append(msg)
        logger.info(f"[restore {artifact_id}] {msg}")

    if not target_server_id or not target_db_name:
        msg = (
            "Restore refused: both target_server_id and target_db_name are required. "
            "The restore target is never inferred, because restoring overwrites it. "
            "To verify a backup without overwriting anything, use the restore "
            "validator (it restores into a throwaway container)."
        )
        logger.error(f"[restore {artifact_id}] {msg}")
        return {"status": "refused", "error": msg}

    workdir = tempfile.mkdtemp(prefix="vm-restore-")
    try:
        async with get_task_session() as db:
            artifact = (await db.execute(
                select(BackupArtifact).where(BackupArtifact.id == uuid.UUID(str(artifact_id)))
            )).scalar_one_or_none()
            if not artifact:
                return {"status": "failed", "error": f"artifact {artifact_id} not found"}

            server = (await db.execute(
                select(Server).where(Server.id == uuid.UUID(str(target_server_id)))
            )).scalar_one_or_none()
            if not server:
                return {"status": "failed", "error": f"target server {target_server_id} not found"}

            filename = artifact.filename or "restore.dump.gz"
            backup_type = artifact.backup_type

        local_path = os.path.join(workdir, filename)
        log(f"downloading {filename}")
        ok, msg = await _download_artifact_to_temp(artifact, local_path)
        if not ok:
            return {"status": "failed", "error": f"download failed: {msg}", "logs": logs}

        if not os.path.isfile(local_path) or os.path.getsize(local_path) == 0:
            return {"status": "failed", "error": "downloaded artifact is 0 bytes", "logs": logs}

        # Dispatch on magic bytes, not artifact.is_encrypted. That column is
        # untrustworthy for anything written before 2026-07-19.
        local_path = await _decrypt_if_needed(local_path, lambda _lvl, m: log(m))

        if backup_type != "postgresql":
            return {
                "status": "failed",
                "error": (
                    f"Automated restore is only implemented for postgresql artifacts, "
                    f"got backup_type={backup_type!r}. The artifact has been downloaded "
                    f"and decrypted to {local_path} for manual restore."
                ),
                "logs": logs,
            }

        db_q = shlex.quote(target_db_name)
        log(f"restoring into database {target_db_name} on {server.name}")

        remote_tmp = f"/tmp/vaultmaster/restore_{artifact_id}"
        await run_remote_command(server, f"mkdir -p {shlex.quote(os.path.dirname(remote_tmp))}")

        code, out, err = await _run(
            ["scp", "-P", str(server.port), local_path,
             f"{server.ssh_user}@{server.host}:{remote_tmp}"],
            timeout=3600,
        )
        if code != 0:
            return {"status": "failed", "error": f"scp to target failed: {(err or out)[:300]}", "logs": logs}

        # Same masking hazard as restore_validator: a bare `pg_restore || psql`
        # reports only the fallback's status, so a failed restore looks like a
        # success. Each reader's outcome is captured explicitly instead, and
        # ON_ERROR_STOP makes psql fail on the first error rather than plough on.
        q = shlex.quote(remote_tmp)
        restore_cmd = (
            f"set -o pipefail; "
            f"if gunzip -c {q} | pg_restore --no-owner --no-acl -d {db_q} 2>&1; then "
            f"  echo 'VM_RESTORE_VIA=pg_restore'; "
            f"elif gunzip -c {q} | psql -d {db_q} -v ON_ERROR_STOP=1 2>&1; then "
            f"  echo 'VM_RESTORE_VIA=psql'; "
            f"else "
            f"  echo 'VM_RESTORE_VIA=none'; exit 1; "
            f"fi"
        )
        exit_code, stdout, stderr = await run_remote_command(server, restore_cmd, timeout=7200)
        await run_remote_command(server, f"rm -f {shlex.quote(remote_tmp)}")

        if exit_code != 0:
            return {
                "status": "failed",
                "error": f"restore failed (exit {exit_code}): {(stderr or stdout or '').strip()[:500]}",
                "logs": logs,
            }

        log("restore completed")
        return {"status": "completed", "target_db": target_db_name, "logs": logs}

    except Exception as e:
        logger.exception(f"[restore {artifact_id}] failed")
        return {"status": "failed", "error": f"{type(e).__name__}: {e}", "logs": logs}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@celery_app.task(name="api.tasks.backup_tasks.verify_artifact_checksum")
def verify_artifact_checksum(artifact_id: str):
    """Verify the checksum of a stored artifact."""
    logger.info(f"Checksum verification queued for artifact {artifact_id}")
    # TODO: Implement checksum verification


@celery_app.task(name="api.tasks.backup_tasks.check_scheduled_jobs")
def check_scheduled_jobs():
    """Check for jobs that need to run based on their cron schedule."""
    _run_async(_check_scheduled())


async def _check_scheduled():
    """Bug #28: bredare window (300s i st.f. 60s) + Redis SETNX-dedup.

    Tidigare: 60-sekunders window. Om beat-tickern var sen (worker omstart,
    GC-paus, tung scheduler-tick) eller om ``check-scheduled-jobs`` schemat
    sköts upp 90s missades körningen helt — *jobbet kördes aldrig den
    schemalagda timmen*.

    Nu: 300s window + Redis SETNX på ``vm:last_scheduled:<job_id>:<epoch>``
    (key TTL 1h) så att även om vi triggar två gånger inom samma 5-min-fönster
    blir bara den första lyckosam — vi förlorar inga schemalagda kör­ningar
    men fördubblar inte heller.
    """
    from sqlalchemy import select
    from croniter import croniter
    from api.models.backup_job import BackupJob
    from api.models.backup_run import BackupRun

    redis_client = None
    try:
        import redis as _redis  # type: ignore[import-not-found]
        from api.config import get_settings as _get_settings
        redis_client = _redis.from_url(_get_settings().redis_url, decode_responses=True)
    except Exception as exc:
        logger.warning(f"_check_scheduled: redis unavailable, falling back to DB-only dedup: {exc}")

    async with get_task_session() as db:
        result = await db.execute(select(BackupJob).where(BackupJob.is_active == True))
        jobs = result.scalars().all()

        now = datetime.now(timezone.utc)
        WINDOW_SECONDS = 300  # was 60 — too tight if beat is late

        for job in jobs:
            try:
                cron = croniter(job.schedule_cron, now)
                prev_time = cron.get_prev(datetime)

                if (now - prev_time).total_seconds() >= WINDOW_SECONDS:
                    continue

                # Skip if this job already has a run still in progress.
                running_result = await db.execute(
                    select(BackupRun)
                    .where(BackupRun.job_id == job.id, BackupRun.status == "running")
                )
                already_running = running_result.scalar_one_or_none()
                if already_running:
                    logger.info(f"Skipping {job.name} — previous run still in progress (started {already_running.started_at})")
                    continue

                # DB-side window check — keeps dedup correct even if Redis is down.
                run_result = await db.execute(
                    select(BackupRun)
                    .where(BackupRun.job_id == job.id, BackupRun.created_at >= prev_time)
                )
                existing = run_result.scalar_one_or_none()
                if existing:
                    continue

                # Redis SETNX dedup — keyed on (job_id, prev_time-epoch) so
                # a single cron-bucket only triggers once even if multiple
                # ticks land inside our widened 300s window.
                if redis_client is not None:
                    bucket_key = f"vm:last_scheduled:{job.id}:{int(prev_time.timestamp())}"
                    try:
                        # NX → only set if absent. EX 3600 → 1h TTL keeps redis tidy.
                        acquired = redis_client.set(bucket_key, "1", nx=True, ex=3600)
                    except Exception as exc:
                        logger.warning(f"_check_scheduled: redis SETNX failed for {job.name}: {exc}; allowing trigger")
                        acquired = True
                    if not acquired:
                        logger.debug(f"_check_scheduled: dedup hit for {job.name} bucket {bucket_key}")
                        continue

                logger.info(f"Triggering scheduled backup: {job.name}")
                run_backup_task.apply_async(args=[str(job.id)], kwargs={"triggered_by": "scheduler"})
            except Exception as e:
                logger.error(f"Error checking schedule for job {job.name}: {e}")

    if redis_client is not None:
        try:
            redis_client.close()
        except Exception:
            pass


@celery_app.task(name="api.tasks.backup_tasks.check_server_health")
def check_server_health():
    """Ping all active servers and update their status."""
    _run_async(_check_health())


async def _check_health():
    from sqlalchemy import select
    from api.models.server import Server
    from api.services.ssh_client import test_ssh_connection
    from api.services.notifier import notify_event

    async with get_task_session() as db:
        result = await db.execute(select(Server).where(Server.is_active == True))
        servers = result.scalars().all()

        for server in servers:
            success, message = await test_ssh_connection(server)
            was_online = server.last_seen and (datetime.now(timezone.utc) - server.last_seen).total_seconds() < 600

            if success:
                server.last_seen = datetime.now(timezone.utc)
                server.last_error = None
            else:
                server.last_error = message
                if was_online:
                    await notify_event(db, "server.offline", {"server_name": server.name, "error": message})

        await db.commit()
