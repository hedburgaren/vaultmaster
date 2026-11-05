"""Regression tests for the night the scheduler skipped seventeen jobs.

Run: python -m tests.test_scheduler_lane

2026-10-29 to 2026-11-01 (card DEV-7, agent-kanban 417): the worker served
every queue with one slot, a 65 GB job held it from 03:30 to about 05:10, and
the per-minute scheduler tick waited behind it in the same queue. When the
tick finally ran, every job due between 03:35 and 04:30 was more than 300 s
old, and the rule "skip a fire time older than 300 s" skipped them all. No
run was created, so nothing failed and nothing alarmed, three nights running.

The first test replays that night with a single-slot queue and fails on the
code as it was: the old rule starts none of the seventeen jobs. The rest pin
the three parts of the fix: the scheduler has its own lane, a late fire time
catches up (or is reported), and an absent job alarms.
"""

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.services import schedule_policy as sp

FAILURES = []
ROOT = Path(__file__).resolve().parent.parent


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


UTC = timezone.utc
NIGHT = datetime(2026, 10, 30, tzinfo=UTC)
# Stockholm is UTC+1 in late October, so 03:35 to 04:30 local is 02:35 to 03:30 UTC.
DUE_JOBS = [f"{m} {h} * * *" for h, m in
            [(2, 35), (2, 40), (2, 45), (2, 49), (2, 50), (2, 55), (3, 0), (3, 5),
             (3, 10), (3, 14), (3, 15), (3, 20), (3, 25), (3, 29), (3, 30), (3, 30), (3, 30)]]
LONG_JOB_START = NIGHT.replace(hour=2, minute=30)   # 03:30 local
LONG_JOB_END = NIGHT.replace(hour=4, minute=10)     # about 05:10 local
DEFINED = NIGHT - timedelta(days=30)
CATCH_UP_HOURS = 2


def old_rule(cron, now):
    """The rule until 2026-11, verbatim in effect: skip a fire time >= 300 s old."""
    prev = sp.latest_fire(cron, now)
    return (now - prev).total_seconds() < 300


def replay_single_slot_night(decide):
    """Beat enqueues a tick every minute; one slot serves ticks and backups in
    FIFO order; the long job holds the slot. Each tick decides with `decide`
    when it finally runs. Returns the set of job indexes started that night."""
    started = set()
    has_run = set()
    t = NIGHT.replace(hour=2, minute=0)
    queue = []
    slot_free_at = t
    while t < NIGHT.replace(hour=6):
        queue.append(t)  # beat: one tick per minute
        if t == LONG_JOB_START:
            # The long backup was queued just before the 03:30 tick.
            queue.insert(len(queue) - 1, "LONG")
        while queue and slot_free_at <= t:
            item = queue.pop(0)
            if item == "LONG":
                slot_free_at = max(t, LONG_JOB_END)
                continue
            # A tick that waited past its expiry is dropped by the broker.
            if decide.expires and (t - item).total_seconds() > decide.expires:
                continue
            for i, cron in enumerate(DUE_JOBS):
                if i in started:
                    continue
                if decide(cron, t, i in has_run):
                    started.add(i)
                    has_run.add(i)
        t += timedelta(minutes=1)
    return started


def test_old_rule_skips_the_whole_window():
    def decide(cron, now, has_run):
        return not has_run and old_rule(cron, now)
    decide.expires = None
    started = replay_single_slot_night(decide)
    check(len(started) == 0,
          f"replay: the old rule starts {len(started)} of {len(DUE_JOBS)} jobs behind a long backup (the bug, expected 0)")


def test_new_rule_catches_up_behind_a_long_backup():
    def decide(cron, now, has_run):
        fire = sp.latest_fire(cron, now)
        action = sp.schedule_action(fire, now, DEFINED, has_run, catch_up_hours=CATCH_UP_HOURS)
        return action in (sp.RUN, sp.CATCH_UP)
    decide.expires = 120
    started = replay_single_slot_night(decide)
    check(len(started) == len(DUE_JOBS),
          f"replay: even on one shared slot the new rule starts all {len(DUE_JOBS)} jobs ({len(started)})")


def test_catch_up_default_covers_the_incident():
    from api.config import Settings
    check(Settings().schedule_catch_up_hours == CATCH_UP_HOURS,
          f"the shipped catch-up bound is the one the replay used ({CATCH_UP_HOURS} h)")


def test_schedule_action_cases():
    fire = NIGHT.replace(hour=3)
    a = sp.schedule_action
    h = CATCH_UP_HOURS
    check(a(fire, fire + timedelta(seconds=30), DEFINED, False, h) == sp.RUN, "on time: run")
    check(a(fire, fire + timedelta(minutes=95), DEFINED, False, h) == sp.CATCH_UP, "95 min late: catch up")
    check(a(fire, fire + timedelta(hours=3), DEFINED, False, h) == sp.MISSED, "3 h late with a 2 h bound: missed, not run")
    check(a(fire, fire + timedelta(minutes=95), DEFINED, True, h) == sp.NONE, "already had its run: nothing")
    check(a(fire, fire + timedelta(minutes=95), fire + timedelta(minutes=1), False, h) == sp.NONE,
          "created after the fire time: not owed")
    # A schedule moved from 03:30 to 21:00 at noon: the 03:30 run today is
    # after yesterday's 21:00, so the run rule alone says nothing is owed.
    moved_fire = NIGHT - timedelta(hours=3)  # yesterday 21:00 local is 20:00 UTC, near enough
    check(a(moved_fire, NIGHT.replace(hour=11), DEFINED, True, h) == sp.NONE,
          "a schedule moved at noon does not start the job at noon")
    naive = fire.replace(tzinfo=None)
    check(a(naive, fire + timedelta(seconds=30), None, False, h) == sp.RUN, "naive datetimes are read as UTC")


def test_is_stale_cases():
    daily = "30 2 * * *"
    now = NIGHT.replace(hour=12)
    check(sp.cron_interval(daily, now) == timedelta(days=1), "a daily cron has a one-day interval")
    check(sp.is_stale(daily, now - timedelta(hours=37), DEFINED, now, 1.5), "daily job, last run 37 h ago: stale")
    check(not sp.is_stale(daily, now - timedelta(hours=30), DEFINED, now, 1.5), "daily job, last run 30 h ago: not stale")
    check(not sp.is_stale(daily, None, now - timedelta(hours=2), now, 1.5), "new job that never ran, created 2 h ago: not stale")
    check(sp.is_stale(daily, None, now - timedelta(days=3), now, 1.5), "job that never ran in 3 days: stale")
    check(sp.is_stale("0 * * * *", now - timedelta(minutes=100), DEFINED, now, 1.5), "hourly job, 100 min without a run: stale")
    # The three nights themselves: daily jobs, last run 10-28 night, checked 10-30 noon.
    check(sp.is_stale(DUE_JOBS[0], NIGHT - timedelta(days=2) + timedelta(hours=3), DEFINED, now, 1.5),
          "the 2026-10-29 case alarms by the second day at the latest")


def test_scheduler_has_its_own_lane():
    from api.tasks.celery_app import celery_app
    routes = celery_app.conf.task_routes
    for name in ("check_scheduled_jobs", "scan_stale_jobs"):
        full = f"api.tasks.backup_tasks.{name}"
        check(routes.get(full, {}).get("queue") == "scheduler", f"{name} is routed to the scheduler queue")
    check(routes.get("api.tasks.backup_tasks.*", {}).get("queue") == "backup", "backups still go to the backup queue")

    # The dict says what we meant; Celery's own router says what happens. The
    # exact names must win over the "backup_tasks.*" pattern.
    import api.tasks.backup_tasks  # noqa: F401  registers the tasks
    router = celery_app.amqp.router
    # reap_stale_runs must stay with the backup worker: its sweep runs docker
    # and reads the archive mount, neither of which the scheduler container has.
    for name, queue in [("check_scheduled_jobs", "scheduler"), ("reap_stale_runs", "backup"),
                        ("scan_stale_jobs", "scheduler"), ("run_backup_task", "backup"),
                        ("check_server_health", "backup")]:
        got = router.route({}, f"api.tasks.backup_tasks.{name}")["queue"].name
        check(got == queue, f"Celery routes {name} to {queue} ({got})")

    compose = (ROOT / "docker-compose.yml").read_text()
    commands = dict(re.findall(r"\n  ([a-z_-]+):\n(?:    .*\n)*?    command: (.*)", compose))
    worker = commands.get("worker", "")
    sched = commands.get("scheduler", "")

    def queues(cmd):
        m = re.search(r"-Q (\S+)", cmd)
        return set(m.group(1).split(",")) if m else set()

    check("scheduler" not in queues(worker), "the backup worker does not serve the scheduler queue")
    check(queues(sched) == {"scheduler"}, f"a separate worker serves only the scheduler queue ({sched!r})")

    beat = celery_app.conf.beat_schedule
    check(any(v["task"].endswith(".scan_stale_jobs") for v in beat.values()), "beat schedules the stale-job scan")
    tick = next(v for v in beat.values() if v["task"].endswith(".check_scheduled_jobs"))
    check((tick.get("options") or {}).get("expires"), "a scheduler tick that waited too long expires instead of piling up")


def test_new_events_reach_someone():
    notifier = (ROOT / "api/services/notifier.py").read_text()
    migration = (ROOT / "migrations/versions/0010_stale_and_missed_triggers.py").read_text()
    ui = (ROOT / "ui/src/app/(app)/notifications/page.tsx").read_text()
    for event in ("schedule.missed", "job.stale"):
        check(f'"{event}"' in notifier, f"{event} has a subject and a message")
        check(f'"{event}"' in migration, f"{event} is added to the channels that hear run.failed")
        check(f"'{event}'" in ui, f"{event} can be chosen for a channel in the panel")


class _FakeRedis:
    def __init__(self, fail=False):
        self.keys = set()
        self.fail = fail

    def set(self, key, value, nx=False, ex=None):
        if self.fail:
            raise RuntimeError("down")
        if nx and key in self.keys:
            return None
        self.keys.add(key)
        return True


def test_claim_once():
    from api.tasks.backup_tasks import _claim_once
    r = _FakeRedis()
    check(_claim_once(r, "k", 10) is True, "first claim of a key succeeds")
    check(_claim_once(r, "k", 10) is False, "second claim of the same key is refused")
    check(_claim_once(None, "k", 10) is None, "no Redis: unknown, not a claim")
    check(_claim_once(_FakeRedis(fail=True), "k", 10) is None, "Redis error: unknown, not a claim")


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class _FakeDB:
    """Answers the three queries _check_scheduled makes, by table and column."""

    def __init__(self, jobs, runs_since_fire=(), running=()):
        self.jobs = jobs
        self.runs_since_fire = set(runs_since_fire)
        self.running = set(running)

    async def execute(self, stmt):
        sql = str(stmt)
        job_id = None
        for p in stmt.compile().params.values():
            if isinstance(p, str) and p.startswith("job-"):
                job_id = p
        if "FROM backup_job" in sql:
            return _Result(self.jobs)
        if "backup_run.status" in sql:
            class _Run:
                started_at = NIGHT
            return _Result([_Run()] if job_id in self.running else [])
        return _Result(["id"] if job_id in self.runs_since_fire else [])

    async def commit(self):
        pass


class _Job:
    def __init__(self, ident, cron):
        self.id = ident
        self.name = ident
        self.schedule_cron = cron
        self.created_at = DEFINED
        self.updated_at = DEFINED


def _drive_check_scheduled(db, now, redis):
    """Run the real _check_scheduled once with the database, Redis, broker,
    notifier and clock replaced. Returns (triggered, notified)."""
    import asyncio
    from contextlib import asynccontextmanager
    from api.tasks import backup_tasks as bt
    from api.services import notifier

    triggered, notified = [], []

    @asynccontextmanager
    async def session():
        yield db

    async def fake_notify(_db, event, data):
        notified.append((event, data))

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    saved = (bt.get_task_session, bt._redis_or_none, bt.run_backup_task.apply_async,
             notifier.notify_event, bt.datetime)
    bt.get_task_session = session
    bt._redis_or_none = lambda caller: redis
    bt.run_backup_task.apply_async = lambda args, kwargs: triggered.append((args[0], kwargs["triggered_by"]))
    notifier.notify_event = fake_notify
    bt.datetime = _Clock
    try:
        asyncio.run(bt._check_scheduled())
    finally:
        (bt.get_task_session, bt._redis_or_none, bt.run_backup_task.apply_async,
         notifier.notify_event, bt.datetime) = saved
    return triggered, notified


class _ClosableRedis(_FakeRedis):
    def close(self):
        pass


def test_check_scheduled_end_to_end():
    fire = NIGHT.replace(hour=2, minute=35)
    late = fire + timedelta(minutes=95)
    job = _Job("job-a", "35 2 * * *")

    r = _ClosableRedis()
    trig, _ = _drive_check_scheduled(_FakeDB([job]), late, r)
    check(trig == [("job-a", "scheduler-catch-up")], f"95 min late, no run yet: started once as a catch-up ({trig})")
    trig, _ = _drive_check_scheduled(_FakeDB([job]), late + timedelta(minutes=1), r)
    check(trig == [], "next tick, run row not created yet (task still queued): not started again")

    trig, _ = _drive_check_scheduled(_FakeDB([job], runs_since_fire={"job-a"}), late, _ClosableRedis())
    check(trig == [], "already had its run: not started")

    trig, _ = _drive_check_scheduled(_FakeDB([job]), late, None)
    check(trig == [], "Redis down: a catch-up is not started, since it cannot be deduplicated")

    trig, _ = _drive_check_scheduled(_FakeDB([job]), fire + timedelta(seconds=40), None)
    check(trig == [("job-a", "scheduler")], "Redis down, on time: started as before the fix")

    r = _ClosableRedis()
    trig, note = _drive_check_scheduled(_FakeDB([job]), fire + timedelta(hours=3), r)
    check(trig == [] and [e for e, _ in note] == ["schedule.missed"],
          f"3 h late: not started, schedule.missed sent ({trig}, {[e for e, _ in note]})")
    trig, note = _drive_check_scheduled(_FakeDB([job]), fire + timedelta(hours=3, minutes=1), r)
    check(note == [], "the same missed fire time is reported once")

    trig, _ = _drive_check_scheduled(_FakeDB([job], running={"job-a"}), late, _ClosableRedis())
    check(trig == [], "a run still in progress: not started")


if __name__ == "__main__":
    for fn in [test_old_rule_skips_the_whole_window, test_new_rule_catches_up_behind_a_long_backup,
               test_catch_up_default_covers_the_incident, test_schedule_action_cases, test_is_stale_cases, test_scheduler_has_its_own_lane,
               test_new_events_reach_someone, test_claim_once, test_check_scheduled_end_to_end]:
        print(fn.__name__)
        fn()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED")
        sys.exit(1)
    print("all passed")
