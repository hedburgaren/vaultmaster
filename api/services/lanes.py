"""Which Celery lane a backup run goes to.

All backups end up on hedburgaren and go encrypted to Google Drive, but the
machines that are backed up are not equally reachable. A desktop (plastdesk)
or a laptop (plastop) can be off, asleep or without a network, and an SSH
connection to it can hang for its whole timeout. With one single-slot backup
queue, that hang held every other backup behind it.

A server tagged ``intermittent`` (plastop) has a lane of its own, ``laptop``,
so that a laptop with no network cannot hold plastdesk either.

The rule is one pure function, used by every place that enqueues a backup
(the scheduler, the trigger endpoint and the laptop check-in): a server tagged
``desktop`` is served by its own worker on the ``workstation`` queue, every
other server by the ``backup`` queue. Nothing may enqueue run_backup_task
without going through ``enqueue_backup`` here, and no task_routes pattern may
be relied on for it.
"""

BACKUP_LANE = "backup"
WORKSTATION_LANE = "workstation"
LAPTOP_LANE = "laptop"
DESKTOP_TAG = "desktop"
INTERMITTENT_TAG = "intermittent"


def is_desktop(server) -> bool:
    tags = getattr(server, "tags", None) or []
    return any(str(t).strip().lower() == DESKTOP_TAG for t in tags)


def is_laptop(server) -> bool:
    tags = getattr(server, "tags", None) or []
    return any(str(t).strip().lower() == INTERMITTENT_TAG for t in tags)


def lane_for(server) -> str:
    """The queue name a backup run (or a health probe) of this server uses.

    An intermittent server (plastop) has a lane of its own, checked before
    desktop: a laptop with no network hangs its SSH connection, and that must
    not hold plastdesk either."""
    if is_laptop(server):
        return LAPTOP_LANE
    return WORKSTATION_LANE if is_desktop(server) else BACKUP_LANE


def enqueue_backup(job, server, triggered_by: str):
    """Queue run_backup_task for the job on the lane of its server."""
    from api.tasks.backup_tasks import run_backup_task

    return run_backup_task.apply_async(
        args=[str(job.id)],
        kwargs={"triggered_by": triggered_by},
        queue=lane_for(server),
    )


def validation_queue_for(server) -> str:
    """Validations of servers on the backup lane stay on the validation queue;
    those of desktops and laptops run on the lane of their server, since a
    restic check SSHes to the server and an unreachable one would otherwise
    hold the shared slot."""
    lane = lane_for(server)
    return "validation" if lane == BACKUP_LANE else lane


def enqueue_validation(job_id, server, artifact_id, triggered_by: str):
    from api.tasks.validation_tasks import validate_backup_job_task

    return validate_backup_job_task.apply_async(
        args=[str(job_id), artifact_id, triggered_by],
        queue=validation_queue_for(server),
    )


def enqueue_restore(server, artifact_id, target_server_id, target_db_name, target_path, confirm_overwrite):
    """A restore SSHes to its target server, so it runs on that server's lane."""
    from api.tasks.backup_tasks import run_restore_task

    return run_restore_task.apply_async(
        args=[str(artifact_id), str(target_server_id) if target_server_id else None,
              target_db_name, target_path, confirm_overwrite],
        queue=lane_for(server) if server is not None else BACKUP_LANE,
    )
