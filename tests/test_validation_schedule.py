"""Regression tests for the validation scan's cooldown.

Defect, visible in production for weeks and never reported by anything: the
scan ran hourly and re-queued a job whose last real validation was older than
24 hours. A job validated at 23:47:23 was not eligible again until 23:47:23
the next day, so the 23:47:00 tick missed it by twenty-three seconds and it
fired at 00:47 instead. Then 01:47. One job's actual history across eight
days: 14:40, 15:40, 16:40, 17:40, 18:40, 19:40, 20:40, 21:47.

Nothing was lost to this. It just meant nobody could say when a validation
was due, and a job could quietly slide into the middle of a backup window.

The cooldown is the only thing holding the schedule still, and it is correct
only in relation to the scan interval. Both bounds are real failures rather
than style preferences, so both are checked here.

Run: python -m tests.test_validation_schedule
"""

import sys

from api.tasks import validation_tasks

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


def test_validation_schedule_does_not_drift():
    scan = validation_tasks.SCAN_INTERVAL_HOURS
    cooldown = validation_tasks.VALIDATION_COOLDOWN_HOURS

    # Upper bound. At exactly 24 the tick lands a few seconds before the
    # boundary and misses, which is the original bug. Anything above 24 - scan
    # leaves less than a full tick of slack and can miss the same way.
    check(cooldown <= 24 - scan,
          f"cooldown {cooldown}h leaves a full scan interval of slack, so the tick cannot miss the boundary")

    # Lower bound. Drop too far and the job is already eligible at the
    # PREVIOUS tick, so the schedule walks earlier by an hour a day instead of
    # later. Same defect, opposite sign.
    check(cooldown > 24 - 2 * scan,
          f"cooldown {cooldown}h is not so short that the previous tick claims the job")

    # And it must still be a daily cadence, not a second job per day.
    check(cooldown > 12,
          f"cooldown {cooldown}h keeps validation daily rather than twice a day")


def test_cooldown_matches_the_beat_schedule():
    """SCAN_INTERVAL_HOURS is an assumption about a value that lives in another
    module. If beat is retuned and this is not, the bounds above are checked
    against a scan interval that no longer exists and prove nothing.
    """
    from api.tasks.celery_app import celery_app

    entry = celery_app.conf.beat_schedule.get("scan-validation-candidates")
    check(entry is not None, "the scan is actually on the beat schedule")
    if entry:
        check(entry["schedule"] == validation_tasks.SCAN_INTERVAL_HOURS * 3600,
              f"beat runs the scan every {entry['schedule']}s, matching SCAN_INTERVAL_HOURS")


def test_scan_uses_the_named_cooldown():
    """The constant is only worth having if the query reads it."""
    import inspect
    import re

    src = inspect.getsource(validation_tasks._scan_candidates)
    check("VALIDATION_COOLDOWN_HOURS" in src,
          "the cutoff is computed from VALIDATION_COOLDOWN_HOURS")
    check(not re.search(r"timedelta\(hours=\d+\)", src),
          "no bare hour literal left in the cutoff to drift away from the constant")


def main():
    print("test_validation_schedule_does_not_drift")
    test_validation_schedule_does_not_drift()
    print("test_cooldown_matches_the_beat_schedule")
    test_cooldown_matches_the_beat_schedule()
    print("test_scan_uses_the_named_cooldown")
    test_scan_uses_the_named_cooldown()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All validation-schedule checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
