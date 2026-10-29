"""Tests for the per-job trust verdict.

Run: python -m tests.test_trust_verdict
"""

import sys
from datetime import datetime, timedelta, timezone

from api.services.trust import trust_verdict

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def hours(n):
    return NOW - timedelta(hours=n)


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: expected {expected!r}, got {actual!r}")


def ok_kwargs(**over):
    base = dict(
        now=NOW, job_active=True,
        last_success_at=hours(2),
        oldest_artifact_at=hours(200),
        artifact_count=30,
        destinations_with_copy=2,
        last_validation_at=hours(20),
        last_validation_status="passed",
    )
    base.update(over)
    return base


def test_healthy_job_is_green():
    v = trust_verdict(**ok_kwargs())
    assert_eq(v, {"level": "green", "reasons": []})


def test_never_succeeded_is_red():
    v = trust_verdict(**ok_kwargs(last_success_at=None))
    assert_eq(v["level"], "red")
    assert "never_succeeded" in v["reasons"]


def test_no_artifacts_is_red_even_after_success():
    v = trust_verdict(**ok_kwargs(artifact_count=0, oldest_artifact_at=None))
    assert_eq(v["level"], "red")
    assert "no_artifacts" in v["reasons"]


def test_failed_validation_is_red():
    v = trust_verdict(**ok_kwargs(last_validation_status="failed"))
    assert_eq(v["level"], "red")
    assert "validation_failed" in v["reasons"]


def test_stale_success_is_yellow_not_red():
    v = trust_verdict(**ok_kwargs(last_success_at=hours(72)))
    assert_eq(v["level"], "yellow")
    assert "stale_success" in v["reasons"]


def test_paused_job_not_punished_for_staleness():
    v = trust_verdict(**ok_kwargs(job_active=False, last_success_at=hours(500)))
    assert_eq(v["level"], "green", "pausade jobb döms inte för ålder")


def test_stale_validation_is_yellow():
    v = trust_verdict(**ok_kwargs(last_validation_at=NOW - timedelta(days=10)))
    assert_eq(v["level"], "yellow")
    assert "validation_stale" in v["reasons"]


def test_no_offsite_copy_is_yellow():
    v = trust_verdict(**ok_kwargs(destinations_with_copy=1))
    assert_eq(v["level"], "yellow")
    assert "no_offsite" in v["reasons"]


def test_no_validator_is_not_a_verdict():
    """Jobs whose type cannot be validated carry None; that is a fact."""
    v = trust_verdict(**ok_kwargs(last_validation_at=None, last_validation_status=None))
    assert_eq(v["level"], "green")


def main():
    tests = [
        test_healthy_job_is_green,
        test_never_succeeded_is_red,
        test_no_artifacts_is_red_even_after_success,
        test_failed_validation_is_red,
        test_stale_success_is_yellow_not_red,
        test_paused_job_not_punished_for_staleness,
        test_stale_validation_is_yellow,
        test_no_offsite_copy_is_yellow,
        test_no_validator_is_not_a_verdict,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
    if failures:
        sys.exit(1)
    print(f"\n{len(tests)} passed.")


if __name__ == "__main__":
    main()
