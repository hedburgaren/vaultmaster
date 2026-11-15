"""The workstation lane, the laptop check-in and schedule-less jobs.

Run: python -m tests.test_workstation_lane

Why this exists: every backup used one queue served by one worker with a
single slot. Jobs against plastdesk and plastop shared that slot with
hedburgaren's own jobs, and an SSH connection to a machine that is off (or has
no network) can hang for its whole timeout, so one unreachable laptop could
hold up every other backup behind it. The fix has three parts, pinned here:

- a pure rule, lanes.lane_for(server): a server tagged "desktop" is served by
  the "workstation" queue, every other server by "backup"; every place that
  enqueues a backup (scheduler, trigger endpoint, check-in) uses it, and the
  health probe of desktop servers runs on the workstation lane too;
- plastop is no longer pulled on fixed crons: it calls POST /servers/checkin
  when it is on and has a network, and the server queues what is due;
- a job without a schedule (cron NULL) is neither started nor reported stale.

The tests need no database and no broker: sessions, Redis and apply_async are
replaced by small fakes, and the code under test is the real code.
"""

import asyncio
import hashlib
import logging
import re
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

FAILURES = []
ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


def guarded(fn):
    """A test that dies on the code as it was is a failure, not a crash."""
    def run():
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001
            check(False, f"{fn.__name__} raised {type(exc).__name__}: {exc}")
    run.__name__ = fn.__name__
    return run


# ── fakes ────────────────────────────────────────────────────────────────────

def make_server(name, tags, **kw):
    return SimpleNamespace(id=uuid.uuid4(), name=name, tags=tags, is_active=True,
                           checkin_token_hash=None, last_seen=None, last_error=None, **kw)


def make_job(name, server, cron="0 * * * *", **kw):
    return SimpleNamespace(id=uuid.uuid4(), name=name, server_id=server.id, is_active=True,
                           schedule_cron=cron, created_at=datetime.now(UTC) - timedelta(days=30),
                           backup_type="files", max_retries=0, **kw)


HEDBURGAREN = make_server("hedburgaren", [])
PLASTDESK = make_server("plastdesk", ["desktop"])
PLASTOP = make_server("plastop", ["desktop", "intermittent"])


class FakeRedis:
    """SET NX with no expiry handling: enough for one-shot dedup."""
    def __init__(self):
        self.keys = set()

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys.add(key)
        return True

    def exists(self, key):
        return key in self.keys

    def delete(self, key):
        self.keys.discard(key)

    def close(self):
        pass


class Recorder:
    """Stands in for run_backup_task.apply_async."""
    def __init__(self):
        self.calls = []

    def __call__(self, args=None, kwargs=None, queue=None, **extra):
        self.calls.append({"job_id": args[0], "triggered_by": (kwargs or {}).get("triggered_by"),
                           "queue": queue, "extra": extra})
        return SimpleNamespace(id="task-" + str(len(self.calls)))

    def queues_for(self, jobs):
        ids = {str(j.id) for j in jobs}
        return [c["queue"] for c in self.calls if c["job_id"] in ids]


class patched:
    """Context manager: set attributes, restore them after."""
    def __init__(self, *triples):
        self.triples = triples
        self.saved = []

    def __enter__(self):
        for obj, name, value in self.triples:
            self.saved.append((obj, name, getattr(obj, name, _MISSING)))
            setattr(obj, name, value)
        return self

    def __exit__(self, *exc):
        for obj, name, old in reversed(self.saved):
            if old is _MISSING:
                delattr(obj, name)
            else:
                setattr(obj, name, old)


_MISSING = object()


@asynccontextmanager
async def fake_session(db=None):
    yield db or SimpleNamespace()


def bt():
    from api.tasks import backup_tasks
    return backup_tasks


def scheduler_patches(jobs_with_servers, recorder, redis, notified=None):
    """Patch everything _check_scheduled touches except its own logic."""
    b = bt()

    async def load(db):
        return list(jobs_with_servers)

    async def no_run(db, job_id, since):
        return False

    async def not_running(db, job_id):
        return None

    async def notify(db, event, payload):
        if notified is not None:
            notified.append((event, payload))

    from api.services import notifier
    return patched(
        (b, "get_task_session", lambda: fake_session()),
        (b, "_redis_or_none", lambda caller: redis),
        (b, "_load_active_jobs", load),
        (b, "_has_run_since", no_run),
        (b, "_running_run", not_running),
        (b.run_backup_task, "apply_async", recorder),
        (notifier, "notify_event", notify),
    )


class ErrorLog(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


# ── 1. the rule ──────────────────────────────────────────────────────────────

@guarded
def test_lane_for_the_three_servers():
    from api.services.lanes import lane_for
    check(lane_for(HEDBURGAREN) == "backup", "hedburgaren (no tags) is served by the backup lane")
    check(lane_for(PLASTDESK) == "workstation", "plastdesk (desktop) is served by the workstation lane")
    check(lane_for(PLASTOP) == "laptop", "plastop (desktop, intermittent) is served by the laptop lane, checked before desktop")
    check(lane_for(make_server("x", ["intermittent"])) == "laptop", "intermittent alone is the laptop lane")
    check(lane_for(make_server("x", [" Intermittent "])) == "laptop", "the intermittent tag ignores case and spaces")
    check(lane_for(make_server("x", None)) == "backup", "a server with tags NULL is on the backup lane")
    check(lane_for(make_server("x", [" Desktop "])) == "workstation", "the desktop tag ignores case and spaces")


# ── 2. every enqueue path ────────────────────────────────────────────────────

@guarded
def test_scheduler_enqueues_on_the_lane_of_the_server():
    rec = Recorder()
    jobs = [(make_job("h-db", HEDBURGAREN), HEDBURGAREN),
            (make_job("d-files", PLASTDESK), PLASTDESK),
            (make_job("p-files", PLASTOP), PLASTOP)]
    with scheduler_patches(jobs, rec, FakeRedis()):
        asyncio.run(bt()._check_scheduled())
    by_job = {c["job_id"]: c["queue"] for c in rec.calls}
    check(len(rec.calls) == 3, f"the scheduler started all three due jobs ({len(rec.calls)})")
    check(by_job.get(str(jobs[0][0].id)) == "backup", "scheduler: a hedburgaren job goes to backup")
    check(by_job.get(str(jobs[1][0].id)) == "workstation", "scheduler: a plastdesk job goes to workstation")
    check(by_job.get(str(jobs[2][0].id)) == "laptop", "scheduler: a plastop job goes to laptop")
    check(all(c["queue"] in ("backup", "workstation", "laptop") for c in rec.calls),
          "scheduler: no enqueue leaves the queue to a routing pattern")


@guarded
def test_trigger_endpoint_enqueues_on_the_lane_of_the_server():
    from api.routers import jobs as jobs_router

    async def fake_log_action(*a, **k):
        return None

    results = {}
    for server in (HEDBURGAREN, PLASTDESK, PLASTOP):
        job = make_job("manual-" + server.name, server)

        class Db:
            async def execute(self, stmt):
                return SimpleNamespace(scalar_one_or_none=lambda: job)

            async def get(self, model, pk):
                return server

        rec = Recorder()
        with patched((bt().run_backup_task, "apply_async", rec), (jobs_router, "log_action", fake_log_action)):
            out = asyncio.run(jobs_router.trigger_job(job.id, db=Db(), current_user=SimpleNamespace(is_admin=True)))
        results[server.name] = (rec.calls, out)
    check([c["queue"] for c in results["hedburgaren"][0]] == ["backup"], "trigger: a hedburgaren job goes to backup")
    check([c["queue"] for c in results["plastdesk"][0]] == ["workstation"], "trigger: a plastdesk job goes to workstation")
    check([c["queue"] for c in results["plastop"][0]] == ["laptop"], "trigger: a plastop job goes to laptop")
    check(results["plastop"][1]["status"] == "queued", "trigger: still answers queued")


@guarded
def test_no_code_path_enqueues_a_backup_around_the_lane_rule():
    offenders = []
    for path in (ROOT / "api").rglob("*.py"):
        if path.name == "lanes.py":
            continue
        text = path.read_text()
        for m in re.finditer(r"run_backup_task\s*\.\s*(apply_async|delay|apply)\b", text):
            offenders.append(f"{path.relative_to(ROOT)}:{text[:m.start()].count(chr(10)) + 1}")
    check(not offenders, f"run_backup_task is enqueued only through lanes.enqueue_backup ({offenders})")
    from api.tasks.celery_app import celery_app
    routes = celery_app.conf.task_routes
    check(routes.get("api.tasks.backup_tasks.check_workstation_health") == {"queue": "workstation"},
          "the desktop health probe is routed to the workstation queue by name")
    check(routes.get("api.tasks.backup_tasks.check_server_health", routes.get("api.tasks.backup_tasks.*")) == {"queue": "backup"},
          "the ordinary health probe stays on the backup queue")
    beat = celery_app.conf.beat_schedule
    tasks = {v["task"] for v in beat.values()}
    check("api.tasks.backup_tasks.check_workstation_health" in tasks, "beat schedules the workstation health probe")
    check(routes.get("api.tasks.backup_tasks.check_laptop_health") == {"queue": "laptop"},
          "the laptop health probe is routed to the laptop queue by name")
    check("api.tasks.backup_tasks.check_laptop_health" in tasks, "beat schedules the laptop health probe")


# ── 3. replay: the workstation lane is blocked ───────────────────────────────

@guarded
def test_replay_laptop_hang_holds_no_other_lane():
    """plastop is unreachable and its run hangs, so the laptop slot never
    frees. Seventeen hedburgaren jobs and the plastdesk jobs due that night
    must be queued on their own lanes and finish in time."""
    rec = Recorder()
    h_jobs = [(make_job(f"h-{i}", HEDBURGAREN), HEDBURGAREN) for i in range(17)]
    d_jobs = [(make_job(f"d-{i}", PLASTDESK), PLASTDESK) for i in range(3)]
    l_jobs = [(make_job("p-hang", PLASTOP), PLASTOP), (make_job("p-away", PLASTOP), PLASTOP)]
    with scheduler_patches(h_jobs + d_jobs + l_jobs, rec, FakeRedis()):
        asyncio.run(bt()._check_scheduled())
    check(rec.queues_for([j for j, _ in h_jobs]) == ["backup"] * 17, "all 17 hedburgaren jobs are queued on backup")
    check(rec.queues_for([j for j, _ in d_jobs]) == ["workstation"] * 3, "the plastdesk jobs are queued on workstation")
    check(rec.queues_for([j for j, _ in l_jobs]) == ["laptop"] * 2, "the plastop jobs wait on laptop, the blocked lane")

    # Three single-slot workers, one minute per job. The laptop worker never
    # frees (hang); the other two must clear their own queues.
    for lane, n in (("backup", 17), ("workstation", 3)):
        done = list(range(1, len([c for c in rec.calls if c["queue"] == lane]) + 1))
        check(len(done) == n and done[-1] <= 60,
              f"the {lane} lane clears its {n} jobs in {done[-1]} min while the laptop slot is stuck")
    on_laptop = {c["job_id"] for c in rec.calls if c["queue"] == "laptop"}
    others = {str(j.id) for j, _ in h_jobs + d_jobs}
    check(not (on_laptop & others), "no hedburgaren or plastdesk job is stuck behind the laptop lane")


@guarded
def test_health_probe_routing_per_lane():
    b = bt()
    probed = []

    async def probe(server):
        probed.append(server.name)
        return True, "ok"

    class Db:
        async def execute(self, stmt):
            servers = [HEDBURGAREN, PLASTDESK, PLASTOP]
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: servers))

        async def commit(self):
            return None

    from api.services import ssh_client
    seen = {}
    with patched((b, "get_task_session", lambda: fake_session(Db())),
                 (ssh_client, "test_ssh_connection", probe)):
        for lane in ("backup", "workstation", "laptop"):
            probed.clear()
            asyncio.run(b._check_health(lane))
            seen[lane] = list(probed)
    check(seen["backup"] == ["hedburgaren"], f"the backup-lane probe touches only hedburgaren ({seen['backup']})")
    check(seen["workstation"] == ["plastdesk"], f"the workstation-lane probe touches only plastdesk ({seen['workstation']})")
    check(seen["laptop"] == ["plastop"], f"the laptop-lane probe touches only plastop ({seen['laptop']})")
    check("plastop" not in seen["backup"] + seen["workstation"],
          "no probe of an intermittent server runs on workstation or backup")
    check(all(hasattr(b, n) for n in ("check_server_health", "check_workstation_health", "check_laptop_health")),
          "all three probe tasks exist")


@guarded
def test_offline_alarm_keeps_the_intermittent_exception():
    b = bt()
    events = []

    async def probe(server):
        return False, "no route to host"

    async def notify(db, event, payload):
        events.append((event, payload["server_name"]))

    now = datetime.now(UTC)
    desk = make_server("plastdesk", ["desktop"])
    top = make_server("plastop", ["desktop", "intermittent"])
    desk.last_seen = top.last_seen = now - timedelta(minutes=2)

    class Db:
        async def execute(self, stmt):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [desk, top]))

        async def commit(self):
            return None

    from api.services import ssh_client, notifier
    with patched((b, "get_task_session", lambda: fake_session(Db())),
                 (ssh_client, "test_ssh_connection", probe),
                 (notifier, "notify_event", notify)):
        asyncio.run(b._check_health("workstation"))
        asyncio.run(b._check_health("laptop"))
    check(events == [("server.offline", "plastdesk")],
          f"plastdesk going offline alarms, plastop (intermittent) does not ({events})")


# ── 4. jobs without a schedule ───────────────────────────────────────────────

@guarded
def test_null_cron_is_neither_started_nor_reported_stale():
    b = bt()
    errors = ErrorLog()
    logging.getLogger("api.tasks.backup_tasks").addHandler(errors)
    try:
        rec, notified = Recorder(), []
        null_job = make_job("p-nullcron", PLASTOP, cron=None)
        scheduled = make_job("h-daily", HEDBURGAREN, cron="0 * * * *")
        with scheduler_patches([(null_job, PLASTOP), (scheduled, HEDBURGAREN)], rec, FakeRedis(), notified):
            asyncio.run(b._check_scheduled())
        started = [c["job_id"] for c in rec.calls]
        check(str(null_job.id) not in started, "scheduler: a job with cron NULL is not started")
        check(started == [str(scheduled.id)], "scheduler: the scheduled job beside it still starts")
        check(not [n for n in notified if n[0] == "schedule.missed"], "scheduler: no schedule.missed for a null-cron job")
        check(not errors.records, f"scheduler: the null-cron job is skipped cleanly, not through a caught error ({errors.records})")

        # Stale scan: the null job has no run for ever; a daily job without a run is the control.
        stale_events = []

        async def notify(db, event, payload):
            stale_events.append((event, payload))

        daily = make_job("h-never-ran", HEDBURGAREN, cron="30 2 * * *")

        class Db:
            def __init__(self):
                self.n = 0

            async def execute(self, stmt):
                self.n += 1
                if self.n == 1:
                    return SimpleNamespace(all=lambda: [])
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [null_job, daily]))

        from api.services import notifier
        with patched((b, "get_task_session", lambda: fake_session(Db())),
                     (b, "_redis_or_none", lambda caller: FakeRedis()),
                     (notifier, "notify_event", notify)):
            out = asyncio.run(b._do_scan_stale_jobs())
        check(out["stale"] == ["h-never-ran"], f"stale scan: only the scheduled job is stale ({out['stale']})")
        check(not any("p-nullcron" in str(p) for _, p in stale_events), "stale scan: no job.stale for the null-cron job")
        check(not errors.records, f"stale scan: skipped cleanly, no caught error ({errors.records})")
    finally:
        logging.getLogger("api.tasks.backup_tasks").removeHandler(errors)


# ── 5. the check-in ──────────────────────────────────────────────────────────

class CheckinWorld:
    """A small world for the check-in service: servers by token hash, jobs,
    newest successes, running runs. Everything the service asks the database."""
    def __init__(self, servers, jobs, successes=None, running=None):
        self.servers, self.jobs = servers, jobs
        self.successes = successes or {}
        self.running = set(running or [])

    def patches(self, recorder):
        from api.services import checkin as svc
        by_hash = {s.checkin_token_hash: s for s in self.servers if s.checkin_token_hash}

        async def find(db, token_hash):
            return by_hash.get(token_hash)

        async def jobs_of(db, server_id):
            # Deliberately returns EVERY job: the service must not trust the
            # query alone to keep another server's jobs out.
            return list(self.jobs)

        async def newest(db, job_id):
            return self.successes.get(job_id)

        async def running(db, job_id):
            return SimpleNamespace(id="run") if job_id in self.running else None

        return patched((svc, "find_server_by_token_hash", find), (svc, "active_jobs_of_server", jobs_of),
                       (svc, "newest_success", newest), (svc, "running_run", running),
                       (bt().run_backup_task, "apply_async", recorder))


def give_token(server):
    from api.services.checkin import generate_token, hash_token
    raw = generate_token()
    server.checkin_token_hash = hash_token(raw)
    return raw


def claim_once(redis, key, ttl):
    if redis is None:
        return None
    return bool(redis.set(key, "1", nx=True, ex=ttl))


@guarded
def test_checkin_queues_only_what_is_old_enough_and_free():
    from api.services import checkin as svc
    now = datetime.now(UTC)
    top = make_server("plastop", ["desktop", "intermittent"])
    raw = give_token(top)
    old = make_job("old-success", top)
    fresh = make_job("fresh-success", top)
    never = make_job("never-ran", top)
    busy = make_job("running-now", top)
    world = CheckinWorld([top], [old, fresh, never, busy],
                         successes={old.id: now - timedelta(hours=14), fresh.id: now - timedelta(hours=3),
                                    busy.id: now - timedelta(hours=20)},
                         running=[busy.id])
    rec, redis = Recorder(), FakeRedis()
    with world.patches(rec):
        server = asyncio.run(svc.authenticate(None, raw))
        result = asyncio.run(svc.process_checkin(None, server, redis, 10, now=now, claim=claim_once))
    queued = sorted(q["job"] for q in result["queued"])
    skipped = {s["job"]: s["reason"] for s in result["skipped"]}
    check(queued == ["never-ran", "old-success"], f"check-in queues the 14 h old and the never-run job ({queued})")
    check(skipped.get("fresh-success") == "recent_success", "check-in skips a job with a success 3 h ago")
    check(skipped.get("running-now") == "already_running", "check-in skips a job that is running")
    check(all(c["queue"] == "laptop" for c in rec.calls) and len(rec.calls) == 2,
          "check-in runs go to the laptop lane")
    check(all(c["triggered_by"] == "checkin" for c in rec.calls), "check-in runs are marked triggered_by=checkin")
    check(top.last_seen == now, "check-in stamps last_seen")

    # The laptop calls again 15 minutes later, the two runs are still queued.
    rec2 = Recorder()
    with world.patches(rec2):
        again = asyncio.run(svc.process_checkin(None, top, redis, 10, now=now + timedelta(minutes=15), claim=claim_once))
    reasons2 = {s["job"]: s["reason"] for s in again["skipped"]}
    check(not rec2.calls and reasons2.get("old-success") == "already_queued" and reasons2.get("never-ran") == "already_queued",
          f"a second check-in does not queue what is already queued ({reasons2})")

    # Without Redis nothing can be deduplicated: wait for the next check-in.
    rec3 = Recorder()
    with world.patches(rec3):
        no_redis = asyncio.run(svc.process_checkin(None, top, None, 10, now=now, claim=claim_once))
    check(not rec3.calls and {s["reason"] for s in no_redis["skipped"]} >= {"redis_unavailable"},
          "no Redis: nothing is queued twice, the jobs wait for the next check-in")


@guarded
def test_checkin_interval_boundary():
    from api.services.checkin import is_due
    now = datetime.now(UTC)
    check(is_due(now - timedelta(hours=10), 10, now), "exactly the interval old: due")
    check(not is_due(now - timedelta(hours=9, minutes=59), 10, now), "a minute under the interval: not due")
    check(is_due(None, 10, now), "never succeeded: due")
    check(is_due((now - timedelta(hours=11)).replace(tzinfo=None), 10, now), "a naive timestamp is read as UTC")
    from api.config import Settings
    check(Settings.model_fields["checkin_min_interval_hours"].default == 10, "the default interval is 10 hours")


@guarded
def test_checkin_rejects_wrong_token_and_confines_the_token_to_its_server():
    from api.services import checkin as svc
    now = datetime.now(UTC)
    top = make_server("plastop", ["desktop", "intermittent"])
    desk = make_server("plastdesk", ["desktop"])
    host = make_server("hedburgaren", [])
    raw_top = give_token(top)
    give_token(desk)
    j_top, j_desk, j_host = make_job("top-job", top), make_job("desk-job", desk), make_job("host-job", host)
    world = CheckinWorld([top, desk, host], [j_top, j_desk, j_host])
    rec = Recorder()

    def rejected(token):
        try:
            asyncio.run(svc.authenticate(None, token))
        except svc.CheckinRejected:
            return True
        return False

    with world.patches(rec):
        check(rejected("vmc_not-a-real-token"), "a wrong token is rejected")
        check(rejected(None) and rejected("") and rejected("   "), "a missing or empty token is rejected")
        check(rejected(top.checkin_token_hash), "the stored hash itself is not a valid token")
        server = asyncio.run(svc.authenticate(None, raw_top))
        result = asyncio.run(svc.process_checkin(None, server, FakeRedis(), 10, now=now, claim=claim_once))
    check(server is top, "a valid token finds its own server")
    check([q["job"] for q in result["queued"]] == ["top-job"],
          f"a valid token queues only its own server's jobs ({[q['job'] for q in result['queued']]})")
    check({c["job_id"] for c in rec.calls} == {str(j_top.id)}, "no run was enqueued for another server's job")
    check(not top.checkin_token_hash == raw_top and top.checkin_token_hash == hashlib.sha256(raw_top.encode()).hexdigest(),
          "only the SHA-256 of the token is stored, never the token")


@guarded
def test_checkin_inactive_server_and_the_real_query_is_scoped():
    from api.services import checkin as svc
    gone = make_server("plastop", ["desktop"])
    gone.is_active = False
    raw = give_token(gone)
    world = CheckinWorld([gone], [])
    with world.patches(Recorder()):
        try:
            asyncio.run(svc.authenticate(None, raw))
            ok = False
        except svc.CheckinRejected:
            ok = True
    check(ok, "a token of a deactivated server is rejected")

    # The real query helper filters on the server, not only the service loop.
    seen = []

    class Db:
        async def execute(self, stmt):
            seen.append(stmt)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []),
                                   scalar_one_or_none=lambda: None)

    sid = uuid.uuid4()
    asyncio.run(svc.active_jobs_of_server(Db(), sid))
    compiled = seen[0].compile()
    check("backup_job.server_id" in str(compiled) and sid in compiled.params.values(),
          "the job query is filtered on the token's server id")

    seen.clear()
    asyncio.run(svc.find_server_by_token_hash(Db(), "ab" * 32))
    compiled = seen[0].compile()
    check("server.checkin_token_hash" in str(compiled) and "ab" * 32 in compiled.params.values(),
          "the token lookup is by hash")


@guarded
def test_checkin_endpoint_over_http():
    """The real route: no header, a wrong token, and the route being public."""
    from fastapi.testclient import TestClient
    from api.main import app
    from api.database import get_db

    async def fake_db():
        yield SimpleNamespace(add=lambda x: None)

    from api.services import checkin as svc

    async def find(db, token_hash):
        return None

    app.dependency_overrides[get_db] = fake_db
    try:
        with patched((svc, "find_server_by_token_hash", find)):
            client = TestClient(app, raise_server_exceptions=False)
            r1 = client.post("/api/v1/servers/checkin")
            r2 = client.post("/api/v1/servers/checkin", headers={"X-Checkin-Token": "vmc_wrong"})
    finally:
        app.dependency_overrides.pop(get_db, None)
    check(r1.status_code == 401, f"POST /servers/checkin without a token answers 401 ({r1.status_code})")
    check(r2.status_code == 401, f"POST /servers/checkin with a wrong token answers 401 ({r2.status_code})")
    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/v1/servers/checkin")
    deps = [d.call.__name__ for d in route.dependant.dependencies]
    check("get_current_user" not in deps, "the check-in route does not need a user login")
    src = (ROOT / "api" / "routers" / "checkin.py").read_text()
    check("@limiter.limit(" in src, "the check-in route is rate limited")


# ── 6. failure notifications ─────────────────────────────────────────────────

def run_failing_backup(server, last_success, max_retries=0, retry_calls=None):
    """Drive the real _run_backup to a failed run and return the notifications."""
    b = bt()
    job = make_job("nightly-" + server.name, server)
    job.max_retries = max_retries
    events = []

    async def notify(db, event, payload):
        events.append((event, payload))

    async def failing_executor(srv, jb, run_id, db=None):
        return {"success": False, "error": "ssh: connect timed out", "logs": []}

    async def last_ok(db, job_id):
        return last_success

    class Db:
        def __init__(self):
            self.step = 0

        async def execute(self, stmt):
            self.step += 1
            if self.step == 1:
                return SimpleNamespace(scalar=lambda: True)
            if self.step == 2:
                return SimpleNamespace(scalar_one_or_none=lambda: job)
            return SimpleNamespace(scalar_one_or_none=lambda: server)

        def add(self, obj):
            obj.id = uuid.uuid4()
            obj.retry_count = 0
            obj.log_lines = None
            obj.size_bytes = None

        async def commit(self):
            return None

        async def refresh(self, obj):
            return None

    from api.services import notifier, quiet_hosts, backup_executor
    class Retried(Exception):
        pass

    def retry(**kwargs):
        if retry_calls is not None:
            retry_calls.append(kwargs)
        return Retried("retry")

    task = SimpleNamespace(request=SimpleNamespace(id="t-1"), retry=retry)
    with patched((b, "get_task_session", lambda: fake_session(Db())),
                 (notifier, "notify_event", notify),
                 (quiet_hosts, "last_success_at", last_ok),
                 (backup_executor, "execute_files_backup", failing_executor)):
        try:
            asyncio.run(b._run_backup(task, str(job.id), "scheduler"))
        except Retried:
            pass
    return job, events


@guarded
def test_failures_still_notify_except_plastop_inside_its_grace():
    for server in (HEDBURGAREN, PLASTDESK):
        recent = datetime.now(UTC) - timedelta(hours=8)
        job, events = run_failing_backup(server, recent)
        failed = [p for e, p in events if e == "run.failed"]
        check(len(failed) == 1 and failed[0]["job_name"] == job.name and "timed out" in (failed[0]["error"] or ""),
              f"a failed run on {server.name} notifies run.failed with the job name and the error")
    job, events = run_failing_backup(PLASTOP, datetime.now(UTC) - timedelta(hours=8))
    check(not [e for e, _ in events if e == "run.failed"],
          "plastop with a success 8 h ago stays quiet inside its grace")
    job, events = run_failing_backup(PLASTOP, datetime.now(UTC) - timedelta(hours=120))
    check(len([e for e, _ in events if e == "run.failed"]) == 1,
          "plastop with no success for 120 h alarms again")


@guarded
def test_retry_stays_on_the_lane_of_the_server():
    for server, lane in ((PLASTOP, "laptop"), (PLASTDESK, "workstation"), (HEDBURGAREN, "backup")):
        calls = []
        run_failing_backup(server, None, max_retries=2, retry_calls=calls)
        check(len(calls) == 1 and calls[0].get("queue") == lane,
              f"a failing {server.name} run retries on {lane} ({[c.get('queue') for c in calls]})")
        check(calls and calls[0].get("countdown") == 60, f"the {server.name} retry keeps its countdown")


# ── 7. every task that opens SSH runs on the lane of its server ──────────────

def ssh_world():
    """Patch the SSH entry points so that plastop and plastdesk are 'unreachable'
    and record which servers each task tried to reach."""
    from api.services import ssh_client
    reached = []

    async def run_cmd(server, command, timeout=300):
        reached.append(server.name)
        return 1, "", "connect timed out"

    return reached, patched((ssh_client, "run_remote_command", run_cmd))


def orphan_scan(lane, servers):
    from api.services import backup_executor
    from api.tasks import cleanup_tasks, backup_tasks as b

    class Db:
        def __init__(self):
            self.n = 0

        async def execute(self, stmt):
            self.n += 1
            if self.n == 1:
                return SimpleNamespace(all=lambda: [])
            if self.n == 2:
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: servers))
            return SimpleNamespace(all=lambda: [])

    async def work_dir(db):
        return "/tmp/vm"

    reached, ssh = ssh_world()
    with ssh, patched((b, "get_task_session", lambda: fake_session(Db())),
                      (backup_executor, "get_work_dir", work_dir)):
        asyncio.run(cleanup_tasks._scan_orphans(lane))
    return reached


@guarded
def test_orphan_scan_fans_out_per_lane():
    servers = [HEDBURGAREN, PLASTDESK, PLASTOP]
    check(orphan_scan("backup", servers) == ["hedburgaren"], "orphan scan, backup lane: SSHes only to hedburgaren")
    check(orphan_scan("workstation", servers) == ["plastdesk"], "orphan scan, workstation lane: only plastdesk")
    check(orphan_scan("laptop", servers) == ["plastop"], "orphan scan, laptop lane: only plastop")
    from api.tasks.celery_app import celery_app
    routes, beat = celery_app.conf.task_routes, celery_app.conf.beat_schedule
    base = "api.tasks.cleanup_tasks.scan_orphan_temp_files"
    check(routes.get(base + "_workstation") == {"queue": "workstation"} and routes.get(base + "_laptop") == {"queue": "laptop"},
          "the per-lane orphan scans are routed to their own queues by name")
    tasks = {v["task"] for v in beat.values()}
    check({base, base + "_workstation", base + "_laptop"} <= tasks, "beat schedules all three orphan scans")


@guarded
def test_validations_and_restores_follow_the_lane_of_their_server():
    from api.services import lanes
    from api.tasks import validation_tasks, backup_tasks as b
    rec_v, rec_r = Recorder(), Recorder()
    with patched((validation_tasks.validate_backup_job_task, "apply_async", rec_v),
                 (b.run_restore_task, "apply_async", rec_r)):
        for srv in (HEDBURGAREN, PLASTDESK, PLASTOP):
            lanes.enqueue_validation(uuid.uuid4(), srv, None, "scheduler")
            lanes.enqueue_restore(srv, uuid.uuid4(), srv.id, "db", None, False)
    check([c["queue"] for c in rec_v.calls] == ["validation", "workstation", "laptop"],
          f"validations: hedburgaren stays on validation, plastdesk on workstation, plastop on laptop ({[c['queue'] for c in rec_v.calls]})")
    check([c["queue"] for c in rec_r.calls] == ["backup", "workstation", "laptop"],
          f"restores follow their target server ({[c['queue'] for c in rec_r.calls]})")

    # The hourly scan and the manual endpoint use the same helper.
    jobs = [make_job("v-h", HEDBURGAREN), make_job("v-d", PLASTDESK), make_job("v-p", PLASTOP)]
    servers = [HEDBURGAREN, PLASTDESK, PLASTOP]

    class Db:
        def __init__(self):
            self.n = 0

        async def execute(self, stmt):
            self.n += 1
            if self.n == 1:
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: jobs))
            if self.n == 2:
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: servers))
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    rec_s = Recorder()
    with patched((validation_tasks, "get_task_session", lambda: fake_session(Db())),
                 (validation_tasks.validate_backup_job_task, "apply_async", rec_s)):
        asyncio.run(validation_tasks._scan_candidates())
    check([c["queue"] for c in rec_s.calls] == ["validation", "workstation", "laptop"],
          f"the hourly validation scan routes per lane ({[c['queue'] for c in rec_s.calls]})")
    offenders = []
    for path in (ROOT / "api").rglob("*.py"):
        if path.name == "lanes.py":
            continue
        text = path.read_text()
        for m in re.finditer(r"(validate_backup_job_task|run_restore_task)\s*\.\s*(delay|apply_async|apply)\b", text):
            offenders.append(f"{path.relative_to(ROOT)}:{text[:m.start()].count(chr(10)) + 1}")
    check(not offenders, f"validations and restores are enqueued only through lanes ({offenders})")


@guarded
def test_replay_unreachable_laptop_with_orphan_scan_and_validation_due():
    """plastop is unreachable. The orphan scan and a plastop validation are due,
    and hedburgaren's jobs are due too. Nothing that SSHes to plastop may sit
    on a queue the backup worker serves."""
    rec = Recorder()
    h_jobs = [(make_job(f"h-{i}", HEDBURGAREN), HEDBURGAREN) for i in range(17)]
    with scheduler_patches(h_jobs, rec, FakeRedis()):
        asyncio.run(bt()._check_scheduled())
    check(rec.queues_for([j for j, _ in h_jobs]) == ["backup"] * 17, "all 17 hedburgaren jobs are queued on backup")

    from api.tasks import validation_tasks
    from api.services import lanes
    rec_v = Recorder()
    with patched((validation_tasks.validate_backup_job_task, "apply_async", rec_v)):
        lanes.enqueue_validation(uuid.uuid4(), PLASTOP, None, "scheduler")
    served_by_backup_worker = {"backup", "rotation", "notification", "validation"}
    check(rec_v.calls[0]["queue"] not in served_by_backup_worker, "the plastop validation is not on a queue the backup worker serves")

    # The shared-lane orphan scan, run with plastop unreachable, never touches it.
    reached = orphan_scan("backup", [HEDBURGAREN, PLASTDESK, PLASTOP])
    check("plastop" not in reached and "plastdesk" not in reached,
          f"the shared orphan scan does not SSH to plastop or plastdesk ({reached})")
    check(len([c for c in rec.calls if c["queue"] == "backup"]) == 17, "the backup lane still has exactly its 17 jobs to clear")


@guarded
def test_checkin_releases_its_claim_when_enqueue_fails():
    from api.services import checkin as svc
    now = datetime.now(UTC)
    top = make_server("plastop", ["desktop", "intermittent"])
    job = make_job("p-job", top)
    world = CheckinWorld([top], [job])
    redis = FakeRedis()

    def boom(*a, **k):
        raise RuntimeError("broker down")

    with world.patches(Recorder()), patched((bt().run_backup_task, "apply_async", boom)):
        try:
            asyncio.run(svc.process_checkin(None, top, redis, 10, now=now, claim=claim_once))
            raised = False
        except RuntimeError:
            raised = True
    check(raised, "a failing enqueue is not swallowed")
    check(f"vm:checkin:{job.id}" not in redis.keys, "the claim is released, so the next check-in can queue the job")
    rec = Recorder()
    with world.patches(rec):
        asyncio.run(svc.process_checkin(None, top, redis, 10, now=now, claim=claim_once))
    check(len(rec.calls) == 1, "the next check-in queues the job")


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s)")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    main()
