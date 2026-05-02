"""Smoke tests for the security-hardening validation in backup_executor.

Run: python -m tests.test_backup_executor_validation
"""

import asyncio
import sys

from api.services.backup_executor import (
    _safe_ident,
    _safe_path,
    execute_postgresql_backup,
    execute_docker_volumes_backup,
    execute_files_backup,
)


class _FakeJob:
    def __init__(self, source_config: dict, name: str = "test"):
        self.source_config = source_config
        self.name = name
        self.backup_type = source_config.get("__type", "postgresql")


class _FakeServer:
    name = "test"


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: expected {expected!r}, got {actual!r}")


def test_safe_ident_accepts_normal():
    _safe_ident("postgres", "x")
    _safe_ident("my_db", "x")
    _safe_ident("a-b.c", "x")


def test_safe_ident_rejects_injection():
    bad = ["foo;rm -rf /", "$(whoami)", "a b", "../etc/passwd", "", "x" * 100, "a`b`"]
    for v in bad:
        try:
            _safe_ident(v, "test")
        except ValueError:
            continue
        raise AssertionError(f"_safe_ident accepted dangerous value {v!r}")


def test_safe_path_rejects_metachars():
    bad = ["/tmp/$(id)", "/tmp/foo;rm -rf /", "/tmp/a&b", "/tmp/`x`"]
    for v in bad:
        try:
            _safe_path(v, "test")
        except ValueError:
            continue
        raise AssertionError(f"_safe_path accepted dangerous value {v!r}")


async def test_pg_backup_rejects_injection():
    job = _FakeJob({
        "db_name": "foo;rm -rf /",
        "pg_user": "postgres",
    })
    result = await execute_postgresql_backup(_FakeServer(), job, "run-1", db=None)
    assert_eq(result["success"], False, "pg backup with malicious db_name")
    assert "Invalid db_name" in result["error"], result["error"]


async def test_pg_backup_rejects_bad_pg_user():
    job = _FakeJob({"db_name": "ok", "pg_user": "$(id)"})
    result = await execute_postgresql_backup(_FakeServer(), job, "run-2", db=None)
    assert_eq(result["success"], False)
    assert "Invalid pg_user" in result["error"], result["error"]


async def test_pg_backup_rejects_bad_compress():
    job = _FakeJob({"db_name": "ok", "pg_user": "ok", "compress_level": "junk"})
    result = await execute_postgresql_backup(_FakeServer(), job, "run-3", db=None)
    assert_eq(result["success"], False)
    assert "compress_level" in result["error"], result["error"]


async def test_docker_volumes_rejects_bad_volume():
    job = _FakeJob({"volumes": ["good", "bad;rm"]})
    result = await execute_docker_volumes_backup(_FakeServer(), job, "run-4", db=None)
    assert_eq(result["success"], False)
    assert "Invalid volume_name" in result["error"], result["error"]


async def test_files_rejects_bad_path():
    job = _FakeJob({"paths": ["/srv/data;rm -rf /"]})
    result = await execute_files_backup(_FakeServer(), job, "run-5", db=None)
    assert_eq(result["success"], False)
    assert "Invalid source path" in result["error"], result["error"]


async def test_files_rejects_bad_exclude():
    job = _FakeJob({"paths": ["/srv/data"], "excludes": ["$(rm)"]})
    result = await execute_files_backup(_FakeServer(), job, "run-6", db=None)
    assert_eq(result["success"], False)
    assert "Invalid exclude" in result["error"], result["error"]


async def main():
    sync_tests = [
        test_safe_ident_accepts_normal,
        test_safe_ident_rejects_injection,
        test_safe_path_rejects_metachars,
    ]
    async_tests = [
        test_pg_backup_rejects_injection,
        test_pg_backup_rejects_bad_pg_user,
        test_pg_backup_rejects_bad_compress,
        test_docker_volumes_rejects_bad_volume,
        test_files_rejects_bad_path,
        test_files_rejects_bad_exclude,
    ]
    failures = 0
    for t in sync_tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {e}")
    for t in async_tests:
        try:
            await t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {e}")
    if failures:
        sys.exit(1)
    print(f"\n{len(sync_tests) + len(async_tests)} passed.")


if __name__ == "__main__":
    asyncio.run(main())
