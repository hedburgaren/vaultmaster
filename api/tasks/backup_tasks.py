import asyncio
import logging
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

        try:
            # Execute based on backup type
            executors = {
                "postgresql": execute_postgresql_backup,
                "docker_volumes": execute_docker_volumes_backup,
                "files": execute_files_backup,
                "custom": execute_custom_backup,
            }

            executor = executors.get(job.backup_type)
            if not executor:
                raise Exception(f"Unknown backup type: {job.backup_type}")

            result_data = await executor(server, job, str(run.id))

            if result_data["success"]:
                run.status = "success"
                run.size_bytes = result_data.get("size_bytes", 0)
                run.log_lines = result_data.get("logs", [])
                run.finished_at = datetime.now(timezone.utc)

                # Create artifact record for each destination
                if result_data.get("filename") and result_data.get("checksum_sha256"):
                    for dest_id in (job.destination_ids or []):
                        artifact = BackupArtifact(
                            run_id=run.id,
                            storage_id=dest_id,
                            filename=result_data["filename"],
                            remote_path=result_data.get("remote_path", ""),
                            size_bytes=result_data.get("size_bytes", 0),
                            checksum_sha256=result_data["checksum_sha256"],
                            is_encrypted=job.encrypt,
                            backup_type=job.backup_type,
                            tags=job.tags,
                            domain=job.domain,
                            db_name=job.source_config.get("db_name"),
                            server_name=server.name,
                        )
                        db.add(artifact)

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
                run.status = "failed"
                run.error_message = result_data.get("error", "Unknown error")
                run.log_lines = result_data.get("logs", [])
                run.finished_at = datetime.now(timezone.utc)

                # Retry if configured
                if run.retry_count < job.max_retries:
                    run.retry_count += 1
                    task.retry(countdown=60 * run.retry_count)

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
            run.status = "failed"
            run.error_message = str(e)
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error(f"Backup task failed for job {job_id}: {e}")
            raise


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
