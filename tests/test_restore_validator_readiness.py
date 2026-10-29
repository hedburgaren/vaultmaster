"""Regression tests for the temp-postgres readiness gate.

The restore validator starts a throwaway postgres container and then has to
decide when it may begin restoring into it. Getting that decision wrong does
not corrupt anything: it just fails the validation. That is worse than it
sounds. A backup validator that flaps teaches everyone to ignore it, and the
one genuine failure then arrives on a red row nobody reads any more.

Defect, seen in production between 2026-07-19 and 2026-08-04: the gate was
`pg_isready`. The postgres image entrypoint runs initdb, then starts a
TEMPORARY server listening on the unix socket only (listen_addresses='') to
create POSTGRES_DB and run the init scripts, then stops it and starts the
real one. `pg_isready` answers 0 against that temporary server, so the gate
opened early and the restore was released into the window where the
temporary server was on its way out. One cause wearing three faces, all
observed for real:

    FATAL:  database "vmverify" does not exist     temp server, DB not created yet
    FATAL:  the database system is shutting down   temp server stopping
    No such file or directory (on the socket)      temp server gone, real one not up

Six validations failed this way across five jobs, and every one of those
backups was in fact restorable.

`pg_isready` cannot be repaired by retrying it. It reports that *a* server
accepts connections, never that the target database exists on the *real*
one. The discriminator is TCP: the temporary server does not listen on TCP
at all, so a successful TCP query against TEMP_DB proves both facts at once.

Run: python -m tests.test_restore_validator_readiness
"""

import asyncio
import inspect
import sys

from api.services import restore_validator

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


def _log(level, msg):
    """The validator's logger, silenced."""


def _fake_run(script):
    """Stand in for restore_validator._run.

    `script` is a list of (exit_code, stdout) handed back in order. The last
    entry repeats once the list is exhausted, so a one-entry script means
    "this is the answer forever".
    """
    calls = []

    async def run(cmd, timeout=None):
        calls.append(cmd)
        code, out = script[min(len(calls) - 1, len(script) - 1)]
        return code, out, ""

    run.calls = calls
    return run


async def _wait(script, **kwargs):
    """Run the readiness gate against a scripted _run, restoring the real one."""
    fake = _fake_run(script)
    original = restore_validator._run
    restore_validator._run = fake
    try:
        kwargs.setdefault("attempts", 5)
        kwargs.setdefault("delay", 0)
        ok = await restore_validator._wait_for_postgres("ctr", _log, **kwargs)
    finally:
        restore_validator._run = original
    return ok, fake.calls


# ---------------------------------------------------------------------------
# The window itself: the server answers, but the target database is not on it
# yet. The gate must stay shut until the real server is serving TEMP_DB.
# ---------------------------------------------------------------------------
async def test_gate_stays_shut_during_the_temp_server_window():
    ok, calls = await _wait([
        (2, ""),      # temp server phase: nothing usable over TCP
        (2, ""),
        (2, ""),
        (0, "1\n"),   # real server up, TEMP_DB queryable
    ])
    check(ok is True, "gate opens once the real server serves the target DB")
    check(len(calls) == 4, f"gate kept probing through the window (4 probes, got {len(calls)})")


async def test_gate_never_opens_if_the_real_server_never_arrives():
    ok, calls = await _wait([(2, "")], attempts=3)
    check(ok is False, "gate reports failure rather than releasing the restore")
    check(len(calls) == 3, f"gate honoured its attempt budget (3, got {len(calls)})")


# ---------------------------------------------------------------------------
# The heart of the defect. `pg_isready` exits 0 and prints no result row. Any
# gate that accepts "exit 0" without looking at what came back has reinvented
# the bug, whichever binary it happens to call.
# ---------------------------------------------------------------------------
async def test_exit_zero_without_a_result_row_is_not_readiness():
    ok, _ = await _wait([(0, "")], attempts=3)
    check(ok is False, "exit 0 with no result row is not readiness (that is pg_isready's answer)")

    ok, _ = await _wait([(0, "\n")], attempts=3)
    check(ok is False, "exit 0 with blank output is not readiness either")


# ---------------------------------------------------------------------------
# The probe has to be one the temporary server cannot possibly satisfy. Over
# the unix socket it could; over TCP it cannot, because it is not listening.
# ---------------------------------------------------------------------------
async def test_probe_goes_over_tcp_against_the_target_database():
    _, calls = await _wait([(0, "1\n")])
    check(bool(calls), "gate issued a probe")
    cmd = calls[0]
    check("-h" in cmd and "127.0.0.1" in cmd,
          "probe connects over TCP, which the temporary init server does not serve")
    check(restore_validator.TEMP_DB in cmd,
          "probe names the target database, so its mere absence fails the probe")


def test_gate_does_not_rely_on_pg_isready():
    """The name is allowed to appear in prose, which is where this module
    explains why it must not be trusted. What must never appear is pg_isready
    as an argument the validator actually executes. So the check reads string
    literals from the AST and skips docstrings, rather than grepping the file
    and tripping over its own documentation.
    """
    import ast

    tree = ast.parse(inspect.getsource(restore_validator))
    prose = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                prose.add(doc)

    executed = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value not in prose
    ]
    check(not any("pg_isready" in s for s in executed),
          "pg_isready appears only in prose, never as a command the validator runs")


async def main():
    print("test_gate_stays_shut_during_the_temp_server_window")
    await test_gate_stays_shut_during_the_temp_server_window()
    print("test_gate_never_opens_if_the_real_server_never_arrives")
    await test_gate_never_opens_if_the_real_server_never_arrives()
    print("test_exit_zero_without_a_result_row_is_not_readiness")
    await test_exit_zero_without_a_result_row_is_not_readiness()
    print("test_probe_goes_over_tcp_against_the_target_database")
    await test_probe_goes_over_tcp_against_the_target_database()
    print("test_gate_does_not_rely_on_pg_isready")
    test_gate_does_not_rely_on_pg_isready()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All readiness-gate regression checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
