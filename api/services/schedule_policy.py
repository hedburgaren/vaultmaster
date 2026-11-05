"""When a scheduled job is due, late, missed or stale.

Written after 2026-10-29 to 2026-11-01. The worker serves every queue with a
single slot (``-c 1``), and a 65 GB job held that slot from 03:30 to about
05:10. The scheduler tick waited behind it in the same queue, and when it
finally ran, every job whose cron time had fallen in that window was more
than 300 s old. The old rule compared the fire time with *now* and skipped
those jobs without a word. Seventeen jobs went three nights without a backup,
no run was ever created, so nothing failed and nothing alarmed.

Three rules replace that silence, and they are plain functions here so they
can be tested without a database, a broker or a clock:

- ``schedule_action``: whether the latest fire time still needs a run. The
  question is "has this fire time had its run", not "is the fire time near
  now". A late tick catches up instead of skipping, up to a bound, and past
  the bound the miss is reported rather than run in the middle of the day.
- ``cron_interval``: the job's own cadence, from its cron expression.
- ``is_stale``: an active job whose newest run is older than a multiple of
  its cadence. This is the backstop that alarms whatever the cause, also for
  failures these rules do not foresee.
"""

from datetime import datetime, timedelta, timezone

from croniter import croniter

# A tick this close to the fire time is the normal case.
ON_TIME_SECONDS = 300

NONE = "none"          # nothing to do for this fire time
RUN = "run"            # due, on time
CATCH_UP = "catch_up"  # due, late, still within the catch-up bound: run now
MISSED = "missed"      # due, too late to run now: report it


def _aware(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def latest_fire(cron_expr: str, now: datetime) -> datetime:
    """The most recent time the cron expression fired, at or before now."""
    return croniter(cron_expr, _aware(now)).get_prev(datetime)


def cron_interval(cron_expr: str, now: datetime) -> timedelta:
    """The spacing between the two most recent fire times.

    For irregular expressions (weekdays only, several hours a day) this is
    the latest gap, which is what a reader of "1.5 intervals" means: the
    job should have run again by now.
    """
    it = croniter(cron_expr, _aware(now))
    last = it.get_prev(datetime)
    before = it.get_prev(datetime)
    return last - before


def schedule_action(
    fire_time: datetime,
    now: datetime,
    defined_at: datetime | None,
    has_run_since_fire: bool,
    catch_up_hours: float,
) -> str:
    """What the scheduler should do about the latest fire time.

    ``defined_at`` is when the job was created. A fire time before that is
    not owed a run, so a job created at noon with a 03:30 schedule waits for
    03:30. It is deliberately not the time of the last edit: edits (a rename,
    a tag) are frequent, and an edit must not erase a missed run. A moved
    schedule is covered by the run rule itself: a job moved from 03:30 to
    21:00 at noon had its 03:30 run after yesterday's 21:00, so nothing is
    owed; a move to a time that just passed catches up at most
    ``catch_up_hours`` later, which is why that bound is short.
    """
    fire_time = _aware(fire_time)
    now = _aware(now)
    defined_at = _aware(defined_at)

    if has_run_since_fire:
        return NONE
    if defined_at is not None and defined_at > fire_time:
        return NONE
    late = (now - fire_time).total_seconds()
    if late < ON_TIME_SECONDS:
        return RUN
    if late <= catch_up_hours * 3600:
        return CATCH_UP
    return MISSED


def is_stale(
    cron_expr: str,
    last_run_at: datetime | None,
    defined_at: datetime | None,
    now: datetime,
    factor: float,
) -> bool:
    """True when an active job has gone longer than ``factor`` intervals
    without any run at all (success or failure both count as a run: a
    failure alarms on its own, an absence alarms only here).

    A job that never ran is measured from when it was defined, so a job
    created this morning with a nightly schedule is not stale at noon.
    """
    now = _aware(now)
    # The later of the two: a job that never ran is measured from its creation.
    candidates = [t for t in (_aware(last_run_at), _aware(defined_at)) if t is not None]
    reference = max(candidates) if candidates else None
    if reference is None:
        return False
    limit = cron_interval(cron_expr, now) * factor
    return now - reference > limit
