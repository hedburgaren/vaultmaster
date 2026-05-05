from celery import Celery

from api.config import get_settings

settings = get_settings()

celery_app = Celery(
    "vaultmaster",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["api.tasks.backup_tasks", "api.tasks.rotation_tasks", "api.tasks.validation_tasks", "api.tasks.credential_tasks", "api.tasks.anomaly_tasks", "api.tasks.security_tasks", "api.tasks.cleanup_tasks"],
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
    },
)
