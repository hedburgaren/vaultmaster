from celery import Celery

from api.config import get_settings

settings = get_settings()

celery_app = Celery(
    "vaultmaster",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["api.tasks.backup_tasks", "api.tasks.rotation_tasks"],
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
    },
    beat_schedule={
        "check-scheduled-jobs": {
            "task": "api.tasks.backup_tasks.check_scheduled_jobs",
            "schedule": 60.0,  # every minute
        },
        "check-server-health": {
            "task": "api.tasks.backup_tasks.check_server_health",
            "schedule": 300.0,  # every 5 minutes
        },
    },
)
