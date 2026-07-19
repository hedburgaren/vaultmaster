"""Periodic storage-usage refresh.

Pollar varje aktiv StorageDestination via rclone/shutil och persisterar
used_bytes, capacity_bytes och last_checked. Dashboard läser kolumnerna
rakt av, så utan denna task fastnar UI:t på "0 B / X TB".

Triggar dessutom storage.warning/storage.critical när användning passerar
80% respektive 95%.
"""

import logging
from datetime import datetime, timezone

from api.tasks.celery_app import celery_app
from api.tasks.backup_tasks import _run_async, get_task_session

logger = logging.getLogger(__name__)

WARN_THRESHOLD = 0.80
CRITICAL_THRESHOLD = 0.95


@celery_app.task(name="api.tasks.storage_tasks.refresh_storage_usage")
def refresh_storage_usage():
    _run_async(_refresh())


async def _refresh() -> None:
    from sqlalchemy import select
    from api.models.storage_destination import StorageDestination
    from api.services.rclone_client import get_storage_usage
    from api.services.notifier import notify_event

    async with get_task_session() as db:
        result = await db.execute(
            select(StorageDestination).where(StorageDestination.is_active == True)
        )
        destinations = result.scalars().all()

        refreshed = 0
        stale: list[str] = []

        for dest in destinations:
            try:
                usage = await get_storage_usage(dest)
            except Exception as exc:
                logger.warning(f"storage usage probe failed for {dest.name}: {exc}")
                stale.append(f"{dest.name} (probe raised: {exc})")
                continue

            if "error" in usage:
                logger.warning(f"storage usage probe error for {dest.name}: {usage['error']}")
                stale.append(f"{dest.name} ({usage['error']})")
                continue

            total = usage.get("total_bytes")
            used = usage.get("used_bytes")
            if used is None:
                logger.warning(f"storage usage probe for {dest.name} returned no used_bytes")
                stale.append(f"{dest.name} (no used_bytes in response)")
                continue

            prev_used = dest.used_bytes or 0
            prev_capacity = dest.capacity_bytes or 0

            dest.used_bytes = used
            # Only set capacity if not already set. Respects a manually
            # configured quota (e.g. user sets 4 TB ceiling on a 20 TB disk).
            if total and not dest.capacity_bytes:
                dest.capacity_bytes = total
            dest.last_checked = datetime.now(timezone.utc)

            if total and total > 0:
                ratio = used / total
                prev_ratio = (prev_used / prev_capacity) if prev_capacity else 0
                event = None
                if ratio >= CRITICAL_THRESHOLD and prev_ratio < CRITICAL_THRESHOLD:
                    event = "storage.critical"
                elif ratio >= WARN_THRESHOLD and prev_ratio < WARN_THRESHOLD:
                    event = "storage.warning"
                if event:
                    await notify_event(db, event, {
                        "name": dest.name,
                        "percent_used": round(ratio * 100, 1),
                    })

            refreshed += 1

        await db.commit()

        # Report what was updated, not what was selected. The old line counted
        # destinations chosen for the loop, so a destination whose probe failed
        # kept its stale used_bytes and stale last_checked while the log claimed
        # it had just been refreshed. A quota reading nobody could tell was old
        # is how you run into a full disk that the dashboard says is at 40%.
        logger.info(
            "refreshed usage for %d of %d destinations", refreshed, len(destinations)
        )
        if stale:
            logger.error(
                "storage usage: %d destination(s) NOT refreshed, their figures are "
                "stale: %s", len(stale), "; ".join(stale[:10]),
            )
