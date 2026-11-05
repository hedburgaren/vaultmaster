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
        action = sp.schedule_action(fire, now, DEFINED, has_run, catch_up_hours=6)
        return action in (sp.RUN, sp.CATCH_UP)
    decide.expires = 120
    started = replay_single_slot_night(decide)
    check(len(started) == len(DUE_JOBS),
          f"replay: even on one shared slot the new rule starts all {len(DUE_JOBS)} jobs ({len(started)})")


def test_schedule_action_cases():
    fire = NIGHT.replace(hour=3)
    a = sp.schedule_action
    check(a(fire, fire + timedelta(seconds=30), DEFINED, False, 6) == sp.RUN, "on time: run")
    check(a(fire, fire + timedelta(minutes=95), DEFINED, False, 6) == sp.CATCH_UP, "95 min late: catch up")
    check(a(fire, fire + timedelta(hours=7), DEFINED, False, 6) == sp.MISSED, "7 h late with a 6 h bound: missed, not run")
    check(a(fire, fire + timedelta(minutes=95), DEFINED, True, 6) == sp.NONE, "already had its run: nothing")
    check(a(fire, fire + timedelta(minutes=95), fire + timedelta(minutes=1), False, 6) == sp.NONE,
          "created or edited after the fire time: not owed (moving 03:30 to 21:00 at noon does not start it at noon)")
    naive = fire.replace(tzinfo=None)
    check(a(naive, fire + timedelta(seconds=30), None, False, 6) == sp.RUN, "naive datetimes are read as UTC")


def test_is_stale_cases():
    daily = "30 2 * * *"
    now = NIGHT.replace(hour=12)
    check(sp.cron_interval(daily, now) == timedelta(days=1), "a daily cron has a one-day interval")
    check(sp.is_stale(daily, now - timedelta(hours=37), DEFINED, now, 1.5), "daily job, last run 37 h ago: stale")
    check(not sp.is_stale(daily, now - timedelta(hours=30), DEFINED, now, 1.5), "daily job, last run 30 h ago: not stale")
    check(not sp.is_stale(daily, None, now - timedelta(hours=2), now, 1.5), "new job that never ran, created 2 h ago: not stale")
    check(sp.is_stale(daily, None, now - timedelta(days=3), now, 1.5), "job that never ran in 3 days: stale")
    check(not sp.is_stale(daily, now - timedelta(days=5), now - timedelta(hours=3), now, 1.5),
          "edited 3 h ago: measured from the edit")
    check(sp.is_stale("0 * * * *", now - timedelta(minutes=100), DEFINED, now, 1.5), "hourly job, 100 min without a run: stale")
    # The three nights themselves: daily jobs, last run 10-28 night, checked 10-30 noon.
    check(sp.is_stale(DUE_JOBS[0], NIGHT - timedelta(days=2) + timedelta(hours=3), DEFINED, now, 1.5),
          "the 2026-10-29 case alarms by the second day at the latest")


def test_scheduler_has_its_own_lane():
    from api.tasks.celery_app import celery_app
    routes = celery_app.conf.task_routes
    for name in ("check_scheduled_jobs", "reap_stale_runs", "scan_stale_jobs"):
        full = f"api.tasks.backup_tasks.{name}"
        check(routes.get(full, {}).get("queue") == "scheduler", f"{name} is routed to the scheduler queue")
    check(routes.get("api.tasks.backup_tasks.*", {}).get("queue") == "backup", "backups still go to the backup queue")

    # The dict says what we meant; Celery's own router says what happens. The
    # exact names must win over the "backup_tasks.*" pattern.
    import api.tasks.backup_tasks  # noqa: F401  registers the tasks
    router = celery_app.amqp.router
    for name, queue in [("check_scheduled_jobs", "scheduler"), ("reap_stale_runs", "scheduler"),
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


if __name__ == "__main__":
    for fn in [test_old_rule_skips_the_whole_window, test_new_rule_catches_up_behind_a_long_backup,
               test_schedule_action_cases, test_is_stale_cases, test_scheduler_has_its_own_lane,
               test_new_events_reach_someone, test_claim_once]:
        print(fn.__name__)
        fn()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED")
        sys.exit(1)
    print("all passed")
