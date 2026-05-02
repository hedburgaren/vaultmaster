"""Backup anomaly detection.

Looks at recent successful runs per active job and fires a
`backup.anomaly`-event when the latest run looks suspicious — typical
red flags from the 2026-05-01 incident class:

  - "size halved suddenly" (corrupted DB, missing files)
  - "size doubled suddenly" (something unintended got captured)
  - "duration tripled" (lock contention, slow disk)
  - "size dropped to zero" (silent failure)

Heuristic: rolling z-score on size_bytes over the last 7 successful
runs, plus an absolute "size dropped >50%" check that fires regardless
of stddev (because a single bad run barely moves stddev).
"""

import logging
import math
from datetime import datetime, timezone

from api.tasks.celery_app import celery_app
from api.tasks.backup_tasks import _run_async, get_task_session

logger = logging.getLogger(__name__)


WINDOW = 7              # how many recent runs to baseline against
Z_THRESHOLD = 2.0       # how many σ counts as anomalous
ABS_DROP_PCT = 50.0     # absolute size-drop % that always fires (even with low σ)


@celery_app.task(name="api.tasks.anomaly_tasks.scan_backup_anomalies")
def scan_backup_anomalies():
    _run_async(_scan())


async def _scan() -> None:
    from sqlalchemy import select, desc
    from api.models.backup_job import BackupJob
    from api.models.backup_run import BackupRun
    from api.models.server import Server
    from api.services.notifier import notify_event

    async with get_task_session() as db:
        result = await db.execute(select(BackupJob).where(BackupJob.is_active == True))
        jobs = result.scalars().all()

        anomalies = 0
        for job in jobs:
            result = await db.execute(
                select(BackupRun)
                .where(BackupRun.job_id == job.id, BackupRun.status == "success")
                .order_by(desc(BackupRun.created_at))
                .limit(WINDOW + 1)
            )
            runs = list(result.scalars())
            if len(runs) < 4:
                # Need at least a few data points before we can call anything anomalous.
                continue

            latest = runs[0]
            window = runs[1:]
            sizes = [r.size_bytes or 0 for r in window]
            mean = sum(sizes) / len(sizes)
            variance = sum((s - mean) ** 2 for s in sizes) / len(sizes)
            stddev = math.sqrt(variance)

            latest_size = latest.size_bytes or 0
            delta_pct = ((latest_size - mean) / mean * 100) if mean > 0 else 0.0
            z_score = ((latest_size - mean) / stddev) if stddev > 0 else 0.0

            triggered = False
            anomaly_type = ""
            hypothesis = ""

            if latest_size == 0 and mean > 0:
                triggered = True
                anomaly_type = "size_zero"
                hypothesis = "backup may have failed silently (0 bytes written)"
            elif mean > 0 and abs(delta_pct) >= ABS_DROP_PCT:
                triggered = True
                anomaly_type = "size_drop_large" if delta_pct < 0 else "size_grow_large"
                if delta_pct < 0:
                    hypothesis = "data may be missing or DB partially dropped — verify before relying on this artifact"
                else:
                    hypothesis = "unexpected dataset growth — check for include-globs widening or runaway logs"
            elif abs(z_score) >= Z_THRESHOLD:
                triggered = True
                anomaly_type = f"z_score_{'high' if z_score > 0 else 'low'}"
                hypothesis = "deviation from recent norm — verify run logs"

            if not triggered:
                continue

            server_result = await db.execute(select(Server).where(Server.id == job.server_id))
            server = server_result.scalar_one_or_none()

            anomalies += 1
            await notify_event(db, "backup.anomaly", {
                "job_name": job.name,
                "server_name": server.name if server else "",
                "anomaly": anomaly_type,
                "latest_size": latest_size,
                "mean_size": mean,
                "delta_pct": delta_pct,
                "z_score": z_score,
                "window": len(window),
                "hypothesis": hypothesis,
                "run_id": str(latest.id),
            })
            logger.info(f"anomaly: {job.name} ({anomaly_type}) Δ={delta_pct:+.1f}% z={z_score:+.2f}")

        await db.commit()
        logger.info(f"backup-anomaly scan: {anomalies} anomalies fired across {len(jobs)} jobs")
