import asyncio
import logging

from api.tasks.celery_app import celery_app
from api.tasks.backup_tasks import get_task_session

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="api.tasks.rotation_tasks.run_rotation")
def run_rotation(policy_id: str, job_id: str | None = None):
    """Run GFS rotation for a specific retention policy."""
    _run_async(_do_rotation(policy_id, job_id))


async def _do_rotation(policy_id: str, job_id: str | None):
    import uuid
    from sqlalchemy import select
    from api.models.retention_policy import RetentionPolicy
    from api.services.rotation import apply_rotation
    from api.services.notifier import notify_event

    async with get_task_session() as db:
        result = await db.execute(select(RetentionPolicy).where(RetentionPolicy.id == uuid.UUID(policy_id)))
        policy = result.scalar_one_or_none()
        if not policy:
            logger.error(f"Retention policy {policy_id} not found")
            return

        rotation_result = await apply_rotation(db, policy, job_id)
        await db.commit()

        if rotation_result["deleted"] > 0:
            await notify_event(db, "rotation.completed", {
                "policy_name": policy.name,
                "kept": rotation_result["kept"],
                "deleted": rotation_result["deleted"],
            })

        logger.info(f"Rotation complete: kept={rotation_result['kept']}, deleted={rotation_result['deleted']}")
