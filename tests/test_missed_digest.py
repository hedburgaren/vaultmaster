"""Missed-run alarms are batched: one message per window, not one per job.

Run: python -m tests.test_missed_digest

2026-11-12: one scheduler fault made every nightly job miss its run, and
VaultMaster sent 36 separate alarms in about four hours, one per job. The
tests drive the real _check_scheduled and read what reaches the notifier.
"""

import sys
from datetime import timedelta

from api.services import notifier
from tests.test_scheduler_lane import (
    NIGHT, _ClosableRedis, _FakeDB, _Job, _drive_check_scheduled, check, FAILURES)


class _HashRedis(_ClosableRedis):
    """The fake from the scheduler tests plus the hash calls the digest uses.
    close_window() stands in for the window key's TTL running out."""

    def __init__(self):
        super().__init__()
        self.hashes = {}

    def hsetnx(self, key, field, value):
        self.hashes.setdefault(key, {}).setdefault(field, value)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def delete(self, key):
        self.hashes.pop(key, None)
        self.keys.discard(key)

    def expire(self, key, ttl):
        pass

    def exists(self, key):
        return 1 if key in self.keys or self.hashes.get(key) else 0

    def close_window(self):
        self.keys.discard("vm:missed_window")


FIRE = NIGHT.replace(hour=2, minute=35)


def _jobs(n, minute_offset=0):
    return [_Job(f"job-{i}", f"{(35 + minute_offset) % 60} 2 * * *") for i in range(n)]


def test_single_missed_job_is_unchanged():
    job = _Job("job-a", "35 2 * * *")
    _, note = _drive_check_scheduled(_FakeDB([job]), FIRE + timedelta(hours=3), _HashRedis())
    check(len(note) == 1 and note[0][0] == "schedule.missed" and "jobs" not in note[0][1],
          f"one missed job: one message, single format ({len(note)})")
    text = notifier._format_event_message(note[0][0], note[0][1])
    check(text.startswith("⏰ Scheduled backup did not start\nJob: job-a\nDue: ")
          and "so it was not started now" in text, "the text is the one used before")


def test_many_missed_in_one_pass_give_one_digest():
    jobs = _jobs(36)
    _, note = _drive_check_scheduled(_FakeDB(jobs), FIRE + timedelta(hours=3), _HashRedis())
    check(len(note) == 1, f"36 missed in one pass: one message ({len(note)})")
    data = note[0][1]
    check(len(data.get("jobs", [])) == 36, "the digest lists all 36 jobs")
    text = notifier._format_event_message("schedule.missed", data)
    check(all(f"job-{i}" in text for i in range(36)), "every job name is in the text")
    check(text.count("more than 2.0 h late") + text.count("more than 2 h late") == 1
          or text.count("h late") == 1, "the explanation appears once")


def test_misses_inside_a_window_wait_for_the_next_one():
    r = _HashRedis()
    first = _jobs(3)
    _, note = _drive_check_scheduled(_FakeDB(first), FIRE + timedelta(hours=3), r)
    check(len(note) == 1, "first pass opens the window and sends")
    # Later: more jobs turn up missed, 10 minutes on, window still open.
    later = [_Job(f"late-{i}", "45 2 * * *") for i in range(5)]
    _, note = _drive_check_scheduled(_FakeDB(first + later), FIRE + timedelta(hours=3, minutes=10), r)
    check(note == [], f"window open: nothing more is sent ({len(note)})")
    _, note = _drive_check_scheduled(_FakeDB(first + later), FIRE + timedelta(hours=3, minutes=11), r)
    check(note == [], "still open, still nothing, and no repeats of the first three")
    r.close_window()
    _, note = _drive_check_scheduled(_FakeDB(first + later), FIRE + timedelta(hours=3, minutes=50), r)
    names = sorted(j["job_name"] for j in note[0][1]["jobs"]) if len(note) == 1 and "jobs" in note[0][1] else None
    check(names == sorted(f"late-{i}" for i in range(5)),
          f"window closed: one digest with exactly the five that waited ({names})")


def test_two_windows_give_two_messages():
    r = _HashRedis()
    jobs = _jobs(4)
    _, a = _drive_check_scheduled(_FakeDB(jobs), FIRE + timedelta(hours=3), r)
    r.close_window()
    next_day = FIRE + timedelta(days=1, hours=3)
    _, b = _drive_check_scheduled(_FakeDB(jobs), next_day, r)
    check(len(a) == 1 and len(b) == 1, f"two windows, two messages ({len(a)}, {len(b)})")


def test_same_job_is_not_resent_in_a_window():
    r = _HashRedis()
    job = _Job("job-a", "35 2 * * *")
    _, a = _drive_check_scheduled(_FakeDB([job]), FIRE + timedelta(hours=3), r)
    sent = len(a)
    for m in (1, 2, 30):
        _, n = _drive_check_scheduled(_FakeDB([job]), FIRE + timedelta(hours=3, minutes=m), r)
        sent += len(n)
    check(sent == 1, f"the same missed job over several passes: sent once ({sent})")
    r.close_window()
    _, n = _drive_check_scheduled(_FakeDB([job]), FIRE + timedelta(hours=4), r)
    check(n == [], "and not after the window closes either")


def test_without_redis_nothing_is_lost():
    # Unchanged from before: the per-fire-time claim needs Redis, so with Redis
    # down no miss is reported at all (job.stale is the backstop). The digest
    # step itself never holds anything back when it has no Redis.
    _, note = _drive_check_scheduled(_FakeDB(_jobs(3)), FIRE + timedelta(hours=3), None)
    check(note == [], "no Redis: missed runs are not reported, as before this change")
    from api.tasks.backup_tasks import _missed_items_to_send
    items = [{"job_id": "a", "job_name": "a", "fire_time": "t"},
             {"job_id": "a", "job_name": "a", "fire_time": "t"},
             {"job_id": "b", "job_name": "b", "fire_time": "t"}]
    check(len(_missed_items_to_send(None, items)) == 2, "no Redis: the step sends all, one entry per job")


def test_other_events_untouched():
    text = notifier._format_event_message("run.failed", {"job_name": "x", "server_name": "s", "error": "e"})
    check(text.startswith("❌ Backup failed"), "run.failed text is unchanged")
    jobs = [{"job_name": "j", "last_run": "never", "schedule": "* * * * *"}]
    check("have stopped running" in notifier._format_event_message("job.stale", {"jobs": jobs}),
          "job.stale text is unchanged")


if __name__ == "__main__":
    for fn in [test_single_missed_job_is_unchanged, test_many_missed_in_one_pass_give_one_digest,
               test_misses_inside_a_window_wait_for_the_next_one, test_two_windows_give_two_messages,
               test_same_job_is_not_resent_in_a_window, test_without_redis_nothing_is_lost,
               test_other_events_untouched]:
        print(fn.__name__)
        fn()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED")
        sys.exit(1)
    print("all passed")
