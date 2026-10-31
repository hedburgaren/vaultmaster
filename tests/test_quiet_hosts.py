"""Quiet failures for intermittent servers (laptops).

Run: python -m tests.test_quiet_hosts
"""

import sys
from datetime import datetime, timedelta, timezone

from api.services.quiet_hosts import failure_stays_quiet, is_intermittent

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


class _Server:
    def __init__(self, tags):
        self.tags = tags


NOW = datetime(2026, 10, 31, 20, 30, tzinfo=timezone.utc)


def main():
    laptop = _Server(["intermittent"])
    server = _Server(["prod"])

    check(is_intermittent(laptop), "tag intermittent marks a server intermittent")
    check(is_intermittent(_Server([" Intermittent "])), "tag match ignores case and spaces")
    check(not is_intermittent(server), "other tags do not")
    check(not is_intermittent(_Server(None)), "no tags at all do not")

    recent = NOW - timedelta(hours=8)
    check(failure_stays_quiet(laptop, recent, 96, NOW),
          "laptop with a success 8 h ago: evening failure stays quiet")
    check(not failure_stays_quiet(server, recent, 96, NOW),
          "an ordinary server always alarms")
    check(not failure_stays_quiet(laptop, NOW - timedelta(hours=97), 96, NOW),
          "laptop without a success for 97 h alarms again")
    check(not failure_stays_quiet(laptop, None, 96, NOW),
          "laptop job that never succeeded alarms")
    naive = (NOW - timedelta(hours=1)).replace(tzinfo=None)
    check(failure_stays_quiet(laptop, naive, 96, NOW),
          "a naive timestamp is read as UTC")

    if FAILURES:
        print(f"{len(FAILURES)} failure(s)")
        sys.exit(1)
    print("all ok")


if __name__ == "__main__":
    main()
