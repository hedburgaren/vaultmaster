"""Regression tests for work-directory failures being reported as themselves.

Run: python -m tests.test_work_dir_errors

Background: every executor fired `mkdir -p` at the work directory and
discarded the exit code. When the directory could not be created the run
continued, and the failure surfaced two steps later as a redirect error on
the output file. On encrypted jobs that filename ends in .age, so the
operator (rightfully) read the error as an encryption problem. Reported by
Klådan 2026-10-29.
"""

import asyncio
import sys

from api.services.backup_executor import ensure_remote_dir


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: expected {expected!r}, got {actual!r}")


class _Server:
    host = "kallas-virtualhost"


def _run_maker(results):
    """Fake run_remote_command yielding canned (exit, stdout, stderr)."""
    calls = []

    async def run(server, cmd, timeout=300):
        calls.append(cmd)
        return results.pop(0)

    return run, calls


def test_mkdir_failure_names_the_directory():
    run, _ = _run_maker([
        (1, "", "mkdir: cannot create directory '/srv/backup': Permission denied"),
    ])
    try:
        asyncio.run(ensure_remote_dir(_Server(), run, "/srv/backup"))
        raise AssertionError("ensure_remote_dir must raise on mkdir failure")
    except AssertionError:
        raise
    except Exception as e:
        msg = str(e)
        assert "/srv/backup" in msg, msg
        assert "kallas-virtualhost" in msg, msg
        assert "Permission denied" in msg, msg
        assert "Could not create work directory" in msg, msg
        # The old failure mode blamed the pipeline; the new message must not
        # point anywhere near encryption.
        assert "age" not in msg.lower(), msg
        assert "encrypt" not in msg.lower(), msg


def test_mkdir_failure_keeps_the_actual_stderr():
    run, _ = _run_maker([
        (1, "", "mkdir: cannot create directory '/mnt/ro': Read-only file system"),
    ])
    try:
        asyncio.run(ensure_remote_dir(_Server(), run, "/mnt/ro"))
        raise AssertionError("must raise")
    except AssertionError:
        raise
    except Exception as e:
        assert "Read-only file system" in str(e), str(e)


def test_mkdir_success_is_silent():
    run, calls = _run_maker([(0, "", "")])
    asyncio.run(ensure_remote_dir(_Server(), run, "/tmp/vaultmaster"))
    assert calls and "mkdir -p" in calls[0] and "/tmp/vaultmaster" in calls[0], calls


def test_command_quotes_the_path():
    run, calls = _run_maker([(0, "", "")])
    asyncio.run(ensure_remote_dir(_Server(), run, "/tmp/evil path;rm -rf"))
    cmd = calls[0]
    assert "mkdir -p " in cmd
    assert "evil path;rm -rf" in cmd  # one quoted argument, not two commands
    assert cmd.count("'") >= 2, cmd


def main():
    tests = [
        test_mkdir_failure_names_the_directory,
        test_mkdir_failure_keeps_the_actual_stderr,
        test_mkdir_success_is_silent,
        test_command_quotes_the_path,
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
