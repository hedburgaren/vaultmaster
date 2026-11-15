"""The laptop check-in: a machine that is not always online asks for its backup.

plastop is a laptop. The server used to pull from it on fixed crons, and a
laptop that was shut at 11:30 simply missed its slot. Now the laptop calls in
when it is switched on and has a network that is not mobile
(laptop/vaultmaster-checkin.sh), and the server queues whatever is due.

A check-in token belongs to one server and grants one thing: "queue the due
jobs of this server". It is stored only as a SHA-256 hash, and the raw token
is shown once, when an admin generates it.

The decisions are plain functions plus a few small query helpers, so the
rules can be tested without a database or a broker.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "vmc_"
# Holds a job out of the next check-in while a run queued by this one is
# still waiting for its worker. Without it, a check-in every 15 minutes would
# queue the same job again and again behind a long run.
CHECKIN_CLAIM_TTL = 2 * 3600

QUEUED = "queued"
SKIP_RECENT = "recent_success"
SKIP_RUNNING = "already_running"
SKIP_QUEUED = "already_queued"
SKIP_NO_REDIS = "redis_unavailable"


class CheckinRejected(Exception):
    """The token is missing, unknown, or belongs to an inactive server."""


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _aware(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def is_due(last_success_at, min_interval_hours: float, now: datetime) -> bool:
    """True when the job has no success yet or its newest one is old enough."""
    if last_success_at is None:
        return True
    return now - _aware(last_success_at) >= timedelta(hours=min_interval_hours)


# ── query helpers (patched in tests) ─────────────────────────────────────────

async def find_server_by_token_hash(db, token_hash: str):
    from sqlalchemy import select
    from api.models.server import Server

    result = await db.execute(select(Server).where(Server.checkin_token_hash == token_hash))
    return result.scalar_one_or_none()


async def active_jobs_of_server(db, server_id):
    """Only the jobs of this server: the token cannot reach any other."""
    from sqlalchemy import select
    from api.models.backup_job import BackupJob

    result = await db.execute(
        select(BackupJob).where(BackupJob.server_id == server_id, BackupJob.is_active == True)
    )
    return list(result.scalars().all())


async def newest_success(db, job_id):
    from api.services.quiet_hosts import last_success_at
    return await last_success_at(db, job_id)


async def running_run(db, job_id):
    from api.tasks.backup_tasks import _running_run
    return await _running_run(db, job_id)


# ── the check-in itself ──────────────────────────────────────────────────────

async def authenticate(db, raw_token):
    """The active server this token belongs to, or CheckinRejected."""
    if not raw_token or not raw_token.strip():
        raise CheckinRejected("missing token")
    token_hash = hash_token(raw_token.strip())
    server = await find_server_by_token_hash(db, token_hash)
    if server is None or not server.checkin_token_hash:
        raise CheckinRejected("unknown token")
    # The lookup above is by hash; this is the constant-time confirmation.
    if not hmac.compare_digest(server.checkin_token_hash, token_hash):
        raise CheckinRejected("unknown token")
    if not server.is_active:
        raise CheckinRejected("server is not active")
    return server


def release(redis_client, key: str) -> None:
    """Drop a claim after a failed enqueue. Best effort: a Redis that fails
    here just means the claim expires on its TTL."""
    if redis_client is None:
        return
    try:
        redis_client.delete(key)
    except Exception as exc:
        logger.warning(f"checkin: could not release claim {key}: {exc}")


async def process_checkin(db, server, redis_client, min_interval_hours: float, now=None, claim=None):
    """Stamp last_seen and queue every due job of this server.

    Returns {"server", "queued": [...], "skipped": [{"job", "reason"}]}.
    `claim` is backup_tasks._claim_once (injectable for tests).
    """
    from api.services.lanes import enqueue_backup, lane_for

    if claim is None:
        from api.tasks.backup_tasks import _claim_once as claim

    now = now or datetime.now(timezone.utc)
    server.last_seen = now
    server.last_error = None

    queued, skipped = [], []
    for job in await active_jobs_of_server(db, server.id):
        if job.server_id != server.id:  # belt and braces: never another server's job
            continue
        last_ok = await newest_success(db, job.id)
        if not is_due(last_ok, min_interval_hours, now):
            skipped.append({"job": job.name, "reason": SKIP_RECENT})
            continue
        if await running_run(db, job.id):
            skipped.append({"job": job.name, "reason": SKIP_RUNNING})
            continue
        claimed = claim(redis_client, f"vm:checkin:{job.id}", CHECKIN_CLAIM_TTL)
        if claimed is False:
            skipped.append({"job": job.name, "reason": SKIP_QUEUED})
            continue
        if claimed is None:
            # Cannot tell whether it is already queued; a double backup is
            # worse than waiting for the next check-in 15 minutes later.
            skipped.append({"job": job.name, "reason": SKIP_NO_REDIS})
            continue
        try:
            enqueue_backup(job, server, "checkin")
        except Exception:
            # Nothing was queued, so the claim must not hold the job out of
            # the next check-in for two hours.
            release(redis_client, f"vm:checkin:{job.id}")
            raise
        queued.append({"job": job.name, "queue": lane_for(server)})
    return {"server": server.name, "queued": queued, "skipped": skipped}
