"""Tests for restore-order validation (what each artifact type requires).

Run: python -m tests.test_restore_orders
"""

import sys

from api.tasks.backup_tasks import restore_request_error


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: expected {expected!r}, got {actual!r}")


SID = "11111111-1111-1111-1111-111111111111"


def test_no_server_is_always_an_error():
    for bt in ("postgresql", "files", "docker_volumes"):
        err = restore_request_error(bt, None, "db", "/x")
        assert err and "target_server_id" in err, (bt, err)


def test_postgresql_needs_db_name():
    assert_eq(restore_request_error("postgresql", SID, None, None) is None, False)
    assert "target_db_name" in restore_request_error("postgresql", SID, None, None)
    assert_eq(restore_request_error("postgresql", SID, "produktdb", None), None)


def test_files_needs_absolute_path():
    err = restore_request_error("files", SID, None, "relativ/väg")
    assert err and "absolute" in err, err
    assert_eq(restore_request_error("files", SID, None, "/restore/hit"), None)


def test_docker_volumes_staging_needs_nothing_more():
    assert_eq(restore_request_error("docker_volumes", SID, None, None), None)
    assert_eq(restore_request_error("docker_volumes", SID, None, "/var/lib/docker/volumes"), None)


def test_unknown_type_named_in_error():
    err = restore_request_error("frisbee", SID, None, None)
    assert err and "frisbee" in err, err


def test_restic_points_to_its_own_path():
    err = restore_request_error("restic", SID, None, None)
    assert err and "restic repository" in err, err


def main():
    tests = [
        test_no_server_is_always_an_error,
        test_postgresql_needs_db_name,
        test_files_needs_absolute_path,
        test_docker_volumes_staging_needs_nothing_more,
        test_unknown_type_named_in_error,
        test_restic_points_to_its_own_path,
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
