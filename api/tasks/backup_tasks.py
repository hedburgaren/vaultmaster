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


def _run_async(coro):
    """Helper to run async code from sync Celery tasks."""
    loop = asyncio.new_event_loop()
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
def run_backup_task(self, job_id: str):
    """Execute a backup job."""
    _run_async(_run_backup(self, job_id))


async def _run_backup(task, job_id: str):
    from sqlalchemy import select
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

        # Create run record
        run = BackupRun(
            job_id=job.id,
            server_id=server.id,
            status="running",
            started_at=datetime.now(timezone.utc),
            triggered_by="manual" if not hasattr(task, '_scheduled') else "scheduler",
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

                        if local_file:
                            ok, msg = await copy_file_to_storage(dest, local_file, sub_path)
                            if ok:
                                stored_path = msg
                                logger.info(f"[{run.id}] Transferred to {dest.name}: {msg}")
                            else:
                                logger.error(f"[{run.id}] Transfer to {dest.name} failed: {msg}")
                        else:
                            logger.warning(f"[{run.id}] No local file available — recording artifact with remote_path only")
                            stored_path = remote_path

                        artifact = BackupArtifact(
                            run_id=run.id,
                            storage_id=dest_id,
                            filename=filename,
                            remote_path=stored_path or remote_path,
                            size_bytes=result_data.get("size_bytes", 0),
                            checksum_sha256=result_data.get("checksum_sha256") or "pending",
                            is_encrypted=job.encrypt,
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

                    # Cleanup: remove temp file from source server work_dir
                    if remote_path:
                        await delete_remote_file(server, remote_path)
                        logger.info(f"[{run.id}] Cleaned up remote temp file: {remote_path}")

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
                            is_encrypted=job.encrypt,
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
            # Don't squash a Retry — let Celery handle it.
            from celery.exceptions import Retry
            if isinstance(e, Retry):
                raise
            run.status = "failed"
            run.error_message = f"{type(e).__name__}: {str(e)}"[:1000]
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error(f"Backup task failed for job {job_id}: {type(e).__name__}: {e}")
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


@celery_app.task(name="api.tasks.backup_tasks.run_restore_task")
def run_restore_task(artifact_id: str, target_server_id: str | None = None, target_db_name: str | None = None):
    """Restore a backup artifact."""
    logger.info(f"Restore task queued for artifact {artifact_id}")
    # TODO: Implement restore logic (download artifact, decrypt, pg_restore/tar extract)


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
    from sqlalchemy import select
    from croniter import croniter
    from api.models.backup_job import BackupJob
    from api.models.backup_run import BackupRun

    async with get_task_session() as db:
        result = await db.execute(select(BackupJob).where(BackupJob.is_active == True))
        jobs = result.scalars().all()

        now = datetime.now(timezone.utc)

        for job in jobs:
            try:
                cron = croniter(job.schedule_cron, now)
                prev_time = cron.get_prev(datetime)

                # Check if we should have run in the last 60 seconds
                if (now - prev_time).total_seconds() < 60:
                    # Skip if this job already has a run still in progress
                    running_result = await db.execute(
                        select(BackupRun)
                        .where(BackupRun.job_id == job.id, BackupRun.status == "running")
                    )
                    already_running = running_result.scalar_one_or_none()
                    if already_running:
                        logger.info(f"Skipping {job.name} — previous run still in progress (started {already_running.started_at})")
                        continue

                    # Check if we already have a run for this window
                    run_result = await db.execute(
                        select(BackupRun)
                        .where(BackupRun.job_id == job.id, BackupRun.created_at >= prev_time)
                    )
                    existing = run_result.scalar_one_or_none()
                    if not existing:
                        logger.info(f"Triggering scheduled backup: {job.name}")
                        run_backup_task.delay(str(job.id))
            except Exception as e:
                logger.error(f"Error checking schedule for job {job.name}: {e}")


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
