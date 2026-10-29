"""Regression tests for the storage budget (task 157).

Run: python -m tests.test_storage_budget

Guards BKP-14: Google Drive showed 110 percent of VaultMaster's 2 TB budget
because "used" came from rclone about (the whole account, trash included),
while the alarm measured against the probed account total, so the budget
alarm could never fire. Decision 2026-10-17: measure VaultMaster's own folder,
notify at 75 percent of the budget, and notify again on a later crossing.
"""

import asyncio
import json
import sys
from contextlib import asynccontextmanager

import api.services.rclone_client as rc
import api.services.notifier as notifier
import api.tasks.storage_tasks as st

TB = 1024 ** 4


class _Dest:
    def __init__(self, capacity, used):
        self.name, self.backend, self.config = "Google Drive", "gdrive", {}
        self.is_active = True
        self.capacity_bytes, self.used_bytes, self.last_checked = capacity, used, None


class _Result:
    def __init__(self, rows): self._rows = rows
    def scalars(self): return self
    def all(self): return self._rows


class _Session:
    def __init__(self, rows): self.rows = rows
    async def execute(self, *_a, **_k): return _Result(self.rows)
    async def commit(self): pass


def _fake_rclone(size_bytes, about):
    async def run(args, timeout=60):
        if args[0] == "size":
            return 0, json.dumps({"count": 3, "bytes": size_bytes}), ""
        if args[0] == "about":
            return 0, json.dumps(about), ""
        return 1, "", "unexpected"
    return run


def test_used_is_own_folder_not_account():
    rc._run_rclone = _fake_rclone(int(0.4 * TB), {"total": 5 * TB, "used": int(2.18 * TB), "trashed": int(1.75 * TB)})
    usage = asyncio.run(rc.get_storage_usage(_Dest(2 * TB, 0)))
    assert usage["used_bytes"] == int(0.4 * TB), usage
    assert usage["total_bytes"] == 5 * TB


def test_size_failure_is_an_error_not_a_number():
    async def run(args, timeout=60):
        return (1, "", "boom") if args[0] == "size" else (0, json.dumps({"total": 5 * TB}), "")
    rc._run_rclone = run
    assert "error" in asyncio.run(rc.get_storage_usage(_Dest(2 * TB, 0)))


def _refresh_with(dest, used_now):
    sent = []

    async def fake_usage(_d):
        return {"total_bytes": 5 * TB, "used_bytes": used_now}

    async def fake_notify(_db, event, payload):
        sent.append((event, payload["percent_used"]))

    @asynccontextmanager
    async def fake_session():
        yield _Session([dest])

    rc.get_storage_usage = fake_usage
    notifier.notify_event = fake_notify
    st.get_task_session = fake_session
    asyncio.run(st._refresh())
    return sent


def test_budget_alarm_fires_at_75_percent_of_budget_and_rearms():
    dest = _Dest(2 * TB, int(1.4 * TB))                 # 70 percent of budget
    assert _refresh_with(dest, int(1.6 * TB)) == [("storage.warning", 80.0)]
    assert dest.capacity_bytes == 2 * TB                # budget is not overwritten
    assert _refresh_with(dest, int(1.7 * TB)) == []     # still above: no repeat
    assert _refresh_with(dest, int(1.2 * TB)) == []     # drops under: re-arms
    assert _refresh_with(dest, int(1.55 * TB)) == [("storage.warning", 77.5)]


def test_no_budget_alarm_against_probed_total():
    dest = _Dest(None, 0)
    assert _refresh_with(dest, int(4.0 * TB)) == [("storage.warning", 80.0)]
    assert dest.capacity_bytes == 5 * TB


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print(f"PASS {name}")
            except AssertionError as e:
                failed += 1; print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
