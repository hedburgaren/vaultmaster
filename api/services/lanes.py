"""Which Celery lane a backup run goes to.

All backups end up on hedburgaren and go encrypted to Google Drive, but the
machines that are backed up are not equally reachable. A desktop (plastdesk)
or a laptop (plastop) can be off, asleep or without a network, and an SSH
connection to it can hang for its whole timeout. With one single-slot backup
queue, that hang held every other backup behind it.

The rule is one pure function, used by every place that enqueues a backup
(the scheduler, the trigger endpoint and the laptop check-in): a server tagged
``desktop`` is served by its own worker on the ``workstation`` queue, every
other server by the ``backup`` queue. Nothing may enqueue run_backup_task
without going through ``enqueue_backup`` here, and no task_routes pattern may
be relied on for it.
"""

BACKUP_LANE = "backup"
WORKSTATION_LANE = "workstation"
DESKTOP_TAG = "desktop"


def is_desktop(server) -> bool:
    tags = getattr(server, "tags", None) or []
    return any(str(t).strip().lower() == DESKTOP_TAG for t in tags)


def lane_for(server) -> str:
    """The queue name a backup run (or a health probe) of this server uses."""
    return WORKSTATION_LANE if is_desktop(server) else BACKUP_LANE


def enqueue_backup(job, server, triggered_by: str):
    """Queue run_backup_task for the job on the lane of its server."""
    from api.tasks.backup_tasks import run_backup_task

    return run_backup_task.apply_async(
        args=[str(job.id)],
        kwargs={"triggered_by": triggered_by},
        queue=lane_for(server),
    )
