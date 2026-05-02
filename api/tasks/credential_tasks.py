"""Periodic credential maintenance tasks.

scan_credential_expiry — emits credential.expiring / credential.expired
notification events. Runs daily via Celery beat.
"""

import logging
from datetime import datetime, timedelta, timezone

from api.tasks.celery_app import celery_app
from api.tasks.backup_tasks import _run_async, get_task_session

logger = logging.getLogger(__name__)


@celery_app.task(name="api.tasks.credential_tasks.scan_credential_expiry")
def scan_credential_expiry():
    """Scan all credentials with non-null expires_at; fire one
    notification event per soon-to-expire / already-expired entry."""
    _run_async(_scan_expiry())


async def _scan_expiry() -> None:
    from sqlalchemy import select
    from api.models.credential import Credential
    from api.services.notifier import notify_event

    now = datetime.now(timezone.utc)
    warn_after = now + timedelta(days=7)

    async with get_task_session() as db:
        result = await db.execute(
            select(Credential).where(Credential.expires_at.is_not(None))
        )
        creds = result.scalars().all()

        n_warn = 0
        n_expired = 0
        for c in creds:
            exp = c.expires_at
            if not exp:
                continue
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            days_left = (exp - now).days
            payload = {
                "name": c.name,
                "credential_type": c.credential_type,
                "expires_at": exp.isoformat(),
                "days_left": days_left,
                "credential_id": str(c.id),
            }
            if exp < now:
                await notify_event(db, "credential.expired", payload)
                n_expired += 1
            elif exp < warn_after:
                await notify_event(db, "credential.expiring", payload)
                n_warn += 1
        await db.commit()
        logger.info(
            "credential expiry scan: %d expiring within 7d, %d already expired",
            n_warn, n_expired,
        )
