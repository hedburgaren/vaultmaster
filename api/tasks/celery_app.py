from celery import Celery

from api.config import get_settings

settings = get_settings()

celery_app = Celery(
    "vaultmaster",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["api.tasks.backup_tasks", "api.tasks.rotation_tasks", "api.tasks.validation_tasks", "api.tasks.credential_tasks", "api.tasks.anomaly_tasks", "api.tasks.security_tasks", "api.tasks.cleanup_tasks", "api.tasks.storage_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "api.tasks.backup_tasks.*": {"queue": "backup"},
        "api.tasks.rotation_tasks.*": {"queue": "rotation"},
        "api.tasks.validation_tasks.*": {"queue": "validation"},
        "api.tasks.security_tasks.*": {"queue": "notification"},
        "api.tasks.anomaly_tasks.*": {"queue": "notification"},
        "api.tasks.credential_tasks.*": {"queue": "notification"},
        "api.tasks.cleanup_tasks.*": {"queue": "rotation"},
        "api.tasks.storage_tasks.*": {"queue": "notification"},
    },
    broker_transport_options={
        "visibility_timeout": 86400,  # 24h — backup-jobb kan ta länge
    },
    task_time_limit=43200,        # hard kill efter 12h
    task_soft_time_limit=39600,   # graceful efter 11h (raises SoftTimeLimitExceeded)
    beat_schedule={
        "check-scheduled-jobs": {
            "task": "api.tasks.backup_tasks.check_scheduled_jobs",
            "schedule": 60.0,  # every minute
        },
        "check-server-health": {
            "task": "api.tasks.backup_tasks.check_server_health",
            "schedule": 300.0,  # every 5 minutes
        },
        "scan-validation-candidates": {
            "task": "api.tasks.validation_tasks.scan_validation_candidates",
            "schedule": 3600.0,  # hourly — picks up jobs not validated in 24h
        },
        "scan-credential-expiry": {
            "task": "api.tasks.credential_tasks.scan_credential_expiry",
            "schedule": 86400.0,  # daily — fires expiring/expired notifications
        },
        "scan-backup-anomalies": {
            "task": "api.tasks.anomaly_tasks.scan_backup_anomalies",
            "schedule": 3600.0,  # hourly — flags size/duration outliers
        },
        "weekly-security-scan": {
            "task": "api.tasks.security_tasks.run_security_scan",
            "schedule": 604800.0,  # weekly — pip-audit + cred-expiry + MCP-orphans
        },
        "scan-orphan-temp-files": {
            "task": "api.tasks.cleanup_tasks.scan_orphan_temp_files",
            "schedule": 21600.0,  # every 6h — sweeps abandoned tar.gz/dump.gz from work_dir
        },
        "refresh-storage-usage": {
            "task": "api.tasks.storage_tasks.refresh_storage_usage",
            "schedule": 900.0,
        },
        # Retention was not scheduled at all until 2026-07-19. Rotation ran
        # only inline after a successful backup, so a job that stopped running
        # never rotated again, and nothing ever deleted a file. The archive
        # reached 138 days of history under a 90-day policy.
        "enforce-retention": {
            "task": "api.tasks.rotation_tasks.enforce_retention",
            "schedule": 86400.0,  # daily: rotate every job, then reclaim space
        },
        # A run orphaned by a dying worker stays 'running' forever and silently
        # blocks its job's schedule. Turn that silence into a visible failure.
        "reap-stale-runs": {
            "task": "api.tasks.backup_tasks.reap_stale_runs",
            "schedule": 900.0,  # every 15 min
        },
    },
)


# Schema guard at worker boot. The 2026-07-19 purged_at incident detonated in
# the WORKER, not the API: a mapped column with no matching migration broke
# retention, purge and validation at the first query, while the API's health
# check stayed green. A worker that cannot work must refuse to start, loudly,
# so the container crash-loops where docker ps shows it, instead of accepting
# tasks and failing them one by one.
from celery.signals import beat_init, celeryd_init


def _assert_schema_or_die(entrypoint: str) -> None:
    import asyncio
    import sys

    from api.services.schema_guard import assert_schema_matches

    loop = asyncio.new_event_loop()
    try:
        n = loop.run_until_complete(assert_schema_matches())
    finally:
        loop.close()
    # stderr, not the logger: celeryd_init fires before celery configures
    # logging, so a logger call here vanishes and the guard becomes
    # unobservable. A check whose execution cannot be seen cannot be told
    # apart from a check that does not run.
    print(f"schema guard ({entrypoint}): {n} tables match their models",
          file=sys.stderr, flush=True)


@celeryd_init.connect
def _schema_guard_worker(**kwargs):
    _assert_schema_or_die("worker")


@beat_init.connect
def _schema_guard_beat(**kwargs):
    _assert_schema_or_die("beat")
