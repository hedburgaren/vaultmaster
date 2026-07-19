"""Regression tests for the silent-success defect class.

Run: python -m tests.test_silent_success_regressions

Every test here corresponds to a defect where the system reported success for
work it did not perform. That class is the reason this suite exists: none of
these bugs produced an error, a crash, or a red dashboard. They produced green
rows over missing data, which is strictly worse than an outage because nothing
prompts anyone to look.

Each test is written to FAIL against the code as it was before the matching
fix. A test that passes both before and after proves nothing.
"""

import asyncio
import sys

from api.services import backup_executor
from api.tasks import backup_tasks

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


class _FakeJob:
    def __init__(self, source_config, encrypt=False, name="test"):
        self.source_config = source_config
        self.name = name
        self.encrypt = encrypt
        self.backup_type = "custom"
        self.tags = []
        self.domain = None


class _FakeServer:
    name = "test"
    host = "127.0.0.1"
    port = 22
    ssh_user = "test"
    auth_type = "local"
    meta = {}


def _fake_remote(responses):
    """Build a run_remote_command stand-in driven by substring matching.

    `responses` maps a substring of the command to (exit_code, stdout, stderr).
    Anything unmatched succeeds silently, which mirrors how these helpers behave
    for mkdir/touch/rm noise.
    """
    calls = []

    async def run(server, command, timeout=None):
        calls.append(command)
        for needle, resp in responses.items():
            if needle in command:
                return resp
        return (0, "", "")

    run.calls = calls
    return run


# ---------------------------------------------------------------------------
# Defect: custom-script jobs returned remote_path="" so the transfer block in
# _run_backup was skipped entirely by `if filename and remote_path and dests:`.
# 11 databases, 615 runs recorded as successful, nothing ever left the staging
# directory. The artifacts pointed at an empty path, so restore could not have
# found them either.
# ---------------------------------------------------------------------------
async def test_custom_backup_returns_real_path():
    job = _FakeJob({
        "command": "dump-something",
        "output_dir": "/mnt/backup/test",
    })
    orig = backup_executor.run_remote_command
    backup_executor.run_remote_command = _fake_remote({
        "find": (0, "1700000000.0 5242880 dump-20260719.sql.gz\n", ""),
    })
    try:
        res = await backup_executor.execute_custom_backup(_FakeServer(), job, "run-1")
    finally:
        backup_executor.run_remote_command = orig

    check(res.get("success") is True, "custom backup succeeds")
    check(
        bool(res.get("remote_path")),
        f"remote_path is non-empty (got {res.get('remote_path')!r})",
    )
    check(
        res.get("remote_path", "").startswith("/mnt/backup/test/"),
        f"remote_path points into output_dir (got {res.get('remote_path')!r})",
    )
    check(
        res.get("remote_path", "").endswith("dump-20260719.sql.gz"),
        "remote_path names the file the script produced",
    )


# ---------------------------------------------------------------------------
# Defect: a failed rclone/SFTP transfer was only logged. The artifact row was
# created anyway using the SOURCE temp path, the temp file was then deleted
# unconditionally, and the run stayed 'success'. Net effect: the backup existed
# in neither place, and the database claimed it was stored.
# ---------------------------------------------------------------------------
def test_transfer_outcome_decisions():
    d = backup_tasks.summarise_transfers

    all_ok = d([("a", True), ("b", True)])
    check(all_ok["any_ok"] is True, "all transfers ok -> any_ok")
    check(all_ok["all_ok"] is True, "all transfers ok -> all_ok")
    check(all_ok["safe_to_delete_source"] is True, "all ok -> source may be removed")

    partial = d([("a", True), ("b", False)])
    check(partial["any_ok"] is True, "partial -> any_ok")
    check(partial["all_ok"] is False, "partial -> not all_ok")
    check(
        partial["safe_to_delete_source"] is False,
        "partial failure -> source must be KEPT so the failed destination can retry",
    )

    none_ok = d([("a", False), ("b", False)])
    check(none_ok["any_ok"] is False, "total failure -> not any_ok")
    check(
        none_ok["safe_to_delete_source"] is False,
        "total failure -> source must be KEPT (this was the data-loss path)",
    )

    empty = d([])
    check(
        empty["safe_to_delete_source"] is False,
        "no transfers attempted -> source must be KEPT",
    )


# ---------------------------------------------------------------------------
# Defect: `pg_restore ... || psql ...` reports only the fallback's exit code, so
# a failing pg_restore is swallowed. Observed for real on 2026-07-19: an empty
# bind mount made pg_restore find nothing, psql succeeded doing nothing, and the
# validation reported success with 0 tables.
# ---------------------------------------------------------------------------
def test_no_masked_restore_fallback():
    import inspect
    import re

    from api.services import restore_validator

    # Comment lines are stripped first. The comments in both modules describe
    # the old bug on purpose, and matching those would make this test fail
    # forever on its own documentation.
    dangerous = re.compile(r"pg_restore[^\n]*\|\|")

    for mod, label in ((restore_validator, "restore_validator"), (backup_tasks, "backup_tasks")):
        code_lines = [
            ln for ln in inspect.getsource(mod).splitlines()
            if not ln.lstrip().startswith("#")
        ]
        code = "\n".join(code_lines)
        check(
            not dangerous.search(code),
            f"{label}: no `pg_restore ... ||` whose failure would be swallowed",
        )
        check(
            "set -o pipefail" in code,
            f"{label}: restore pipeline runs under pipefail so a failing gunzip is not masked",
        )


# ---------------------------------------------------------------------------
# Defect: `fuser -s` returns non-zero for "not in use" AND for "command not
# found", "permission denied", and every other error. Treating all of them as
# "free to delete" means a missing fuser silently disarms the safety check
# guarding in-flight backup files.
# ---------------------------------------------------------------------------
def test_fuser_only_trusted_when_it_ran():
    f = backup_tasks.file_is_free

    check(f(0) is False, "rc=0 (in use) -> not free")
    check(f(1) is True, "rc=1 (genuinely not in use) -> free")
    check(f(127) is False, "rc=127 (fuser missing) -> NOT free, check is unreliable")
    check(f(126) is False, "rc=126 (permission denied) -> NOT free")
    check(f(None) is False, "no result at all -> NOT free")


# ---------------------------------------------------------------------------
# Defect (found by the adversarial audit, in code written the same day): the
# purge safety floor took the newest N rows from the FULL artifact list,
# including rows already flagged is_deleted whose files are gone. When the
# newest rows are deleted ghosts, the floor is satisfied by nothing at all and
# the oldest LIVE backup becomes a deletion candidate.
#
# Reachable in production at the time: ten job/destination pairs had all three
# newest artifacts flagged deleted.
# ---------------------------------------------------------------------------
def test_safety_floor_counts_only_live_artifacts():
    import uuid
    from datetime import datetime, timedelta, timezone

    from api.services.purge import select_floor

    now = datetime.now(timezone.utc)

    class A:
        def __init__(self, age_days, is_deleted):
            self.id = uuid.uuid4()
            self.created_at = now - timedelta(days=age_days)
            self.is_deleted = is_deleted

    # Three newest are ghosts, three older ones are live.
    ghosts = [A(0, True), A(1, True), A(2, True)]
    live = [A(3, False), A(4, False), A(5, False)]
    artifacts = ghosts + live

    floor = select_floor(artifacts, 3)
    floor_ids = {a.id for a in floor}

    check(len(floor) == 3, f"floor holds 3 artifacts, got {len(floor)}")
    check(
        all(not a.is_deleted for a in floor),
        "floor contains only live artifacts, never already-deleted ghosts",
    )
    check(
        floor_ids == {a.id for a in live},
        "floor protects the three newest LIVE backups, not the ghosts above them",
    )

    # Fewer live artifacts than the floor: protect all of them.
    only_two = [A(0, True), A(1, False), A(2, False)]
    check(
        len(select_floor(only_two, 3)) == 2,
        "with fewer live artifacts than the floor, all live ones are protected",
    )


# ---------------------------------------------------------------------------
# Defect (same audit, same day, same module): the artifact lookup in
# execute_purge compared a UUID column against a str. rotation.py already
# documents this as "Bug #13": str equality silently returns no rows on some
# dialects. Here the consequence is that the file gets deleted, the row is
# never flagged, and the counters report the deletion anyway.
# ---------------------------------------------------------------------------
def test_purge_looks_up_artifacts_by_uuid():
    import inspect

    from api.services import purge

    src = inspect.getsource(purge.execute_purge)
    check(
        "uuid.UUID(" in src or "_uuid.UUID(" in src,
        "execute_purge casts the artifact id to UUID before comparing "
        "(str == UUID silently matches nothing, see rotation.py bug #13)",
    )


async def main():
    print("test_safety_floor_counts_only_live_artifacts")
    test_safety_floor_counts_only_live_artifacts()
    print("test_purge_looks_up_artifacts_by_uuid")
    test_purge_looks_up_artifacts_by_uuid()
    print("test_custom_backup_returns_real_path")
    await test_custom_backup_returns_real_path()
    print("test_transfer_outcome_decisions")
    test_transfer_outcome_decisions()
    print("test_no_masked_restore_fallback")
    test_no_masked_restore_fallback()
    print("test_fuser_only_trusted_when_it_ran")
    test_fuser_only_trusted_when_it_ran()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All silent-success regression checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
