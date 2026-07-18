"""Regression tests for retention rotation.

Run: python -m tests.test_rotation_retention

Guards the bug found 2026-07-19: rotation treated "no GFS bucket claimed this
artifact" as "delete this artifact". Every one of the 47 configured jobs uses a
pure-max-age policy (all keep_* = 0), so keep_ids was always empty and every
artifact was marked deleted seconds after it was written. 8305 of 8311 rows
were flagged deleted while the files were still on disk, which hid real backups
from the restore path.
"""

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

from api.services.rotation import apply_rotation, preview_rotation, _gfs_configured


class _FakePolicy:
    def __init__(self, keep_hourly=0, keep_daily=0, keep_weekly=0,
                 keep_monthly=0, keep_yearly=0, max_age_days=0):
        self.keep_hourly = keep_hourly
        self.keep_daily = keep_daily
        self.keep_weekly = keep_weekly
        self.keep_monthly = keep_monthly
        self.keep_yearly = keep_yearly
        self.max_age_days = max_age_days


class _FakeArtifact:
    def __init__(self, created_at, filename="a.gz", size_bytes=100):
        self.id = uuid.uuid4()
        self.created_at = created_at
        self.filename = filename
        self.size_bytes = size_bytes
        self.is_deleted = False
        self.deleted_at = None


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeSession:
    """Minimal stand-in: apply_rotation only needs execute() and flush()."""

    def __init__(self, artifacts):
        self._artifacts = artifacts

    async def execute(self, _query):
        return _FakeResult(list(self._artifacts))

    async def flush(self):
        return None


FAILURES = []


def check(condition, msg):
    if condition:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


async def test_pure_max_age_keeps_fresh_artifacts():
    """The actual production config: all keep_* = 0, max_age_days = 90."""
    now = datetime.now(timezone.utc)
    fresh = _FakeArtifact(now)
    yesterday = _FakeArtifact(now - timedelta(days=1))
    recent = _FakeArtifact(now - timedelta(days=45))
    artifacts = [fresh, yesterday, recent]

    policy = _FakePolicy(max_age_days=90)
    db = _FakeSession(artifacts)
    result = await apply_rotation(db, policy)

    check(not fresh.is_deleted, "freshly created artifact survives rotation")
    check(not yesterday.is_deleted, "1-day-old artifact survives")
    check(not recent.is_deleted, "45-day-old artifact survives (inside 90d window)")
    check(result["deleted"] == 0, f"nothing deleted, got {result['deleted']}")


async def test_pure_max_age_deletes_beyond_window():
    """max_age must still be enforced, otherwise storage grows forever."""
    now = datetime.now(timezone.utc)
    fresh = _FakeArtifact(now)
    stale = _FakeArtifact(now - timedelta(days=120))
    artifacts = [fresh, stale]

    policy = _FakePolicy(max_age_days=90)
    db = _FakeSession(artifacts)
    result = await apply_rotation(db, policy)

    check(not fresh.is_deleted, "fresh artifact kept")
    check(stale.is_deleted, "120-day-old artifact deleted (past 90d max_age)")
    check(stale.deleted_at is not None, "deleted_at stamped on deletion")
    check(result["deleted"] == 1, f"exactly one deleted, got {result['deleted']}")


async def test_gfs_thinning_still_applies():
    """A policy that does ask for GFS must still thin out."""
    now = datetime.now(timezone.utc)
    # Four artifacts on the same day. keep_daily=1 keeps only the newest.
    a = _FakeArtifact(now)
    b = _FakeArtifact(now - timedelta(hours=6))
    c = _FakeArtifact(now - timedelta(hours=12))
    d = _FakeArtifact(now - timedelta(hours=18))
    artifacts = [a, b, c, d]

    policy = _FakePolicy(keep_daily=1, max_age_days=90)
    db = _FakeSession(artifacts)
    result = await apply_rotation(db, policy)

    check(not a.is_deleted, "newest of the day is kept by the daily bucket")
    check(result["deleted"] == 3, f"other three thinned, got {result['deleted']}")


async def test_policy_with_no_criteria_deletes_nothing():
    """All keep_* = 0 and max_age_days = 0 means no retention rule at all.

    Failing safe here matters: a half-filled policy must not become an
    instruction to delete everything.
    """
    now = datetime.now(timezone.utc)
    artifacts = [_FakeArtifact(now - timedelta(days=d)) for d in (0, 30, 365, 3650)]

    policy = _FakePolicy()
    db = _FakeSession(artifacts)
    result = await apply_rotation(db, policy)

    check(result["deleted"] == 0, f"empty policy deletes nothing, got {result['deleted']}")
    check(all(not a.is_deleted for a in artifacts), "no artifact flagged")


async def test_preview_matches_apply():
    """preview_rotation is used to sanity-check policy changes before they run."""
    now = datetime.now(timezone.utc)

    def build():
        return [
            _FakeArtifact(now),
            _FakeArtifact(now - timedelta(days=100)),
            _FakeArtifact(now - timedelta(days=200)),
        ]

    policy = _FakePolicy(max_age_days=90)

    preview_rows = build()
    preview = await preview_rotation(_FakeSession(preview_rows), policy)

    apply_rows = build()
    applied = await apply_rotation(_FakeSession(apply_rows), policy)

    check(
        preview["would_delete"] == applied["deleted"],
        f"preview {preview['would_delete']} == apply {applied['deleted']}",
    )
    check(preview["would_delete"] == 2, f"two stale rows, got {preview['would_delete']}")


def test_gfs_detection():
    check(_gfs_configured(_FakePolicy()) is False, "all-zero policy is not GFS")
    check(_gfs_configured(_FakePolicy(max_age_days=90)) is False, "max-age-only is not GFS")
    check(_gfs_configured(_FakePolicy(keep_weekly=12)) is True, "keep_weekly makes it GFS")
    check(_gfs_configured(_FakePolicy(keep_hourly=1)) is True, "keep_hourly makes it GFS")


async def main():
    print("test_gfs_detection")
    test_gfs_detection()
    for fn in (
        test_pure_max_age_keeps_fresh_artifacts,
        test_pure_max_age_deletes_beyond_window,
        test_gfs_thinning_still_applies,
        test_policy_with_no_criteria_deletes_nothing,
        test_preview_matches_apply,
    ):
        print(fn.__name__)
        await fn()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All rotation checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
