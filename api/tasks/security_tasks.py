"""Weekly automated security scan.

Walks three angles and emits a single security.report-event with the
combined findings:

  1. Python dependency CVEs via pip-audit (against the api container's
     installed packages).
  2. Credential lifecycle: how many credentials expire within 30 days,
     are already expired, or have NULL expires_at (= unbounded).
  3. MCP-client lifecycle: any client with no last_used_at in 90+ days
     (probably-orphaned), or expired.

Runs weekly via Celery beat. Output goes to whatever
NotificationChannel listens for "security.report"-trigger (currently
only the Email channel by default — add Discord if desired).
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timedelta, timezone

from api.tasks.celery_app import celery_app
from api.tasks.backup_tasks import _run_async, get_task_session

logger = logging.getLogger(__name__)


@celery_app.task(name="api.tasks.security_tasks.run_security_scan")
def run_security_scan():
    _run_async(_run_scan())


async def _run_scan() -> None:
    findings: dict = {
        "python_vulns": [],
        "credential_expiry": {"expired": 0, "expiring_30d": 0, "unbounded": 0, "total": 0},
        "mcp_orphans": [],
        "mcp_expired": [],
        "python_scan_error": None,
        "scan_started_at": datetime.now(timezone.utc).isoformat(),
    }

    findings["python_vulns"], findings["python_scan_error"] = await _pip_audit()

    from sqlalchemy import select
    from api.models.credential import Credential
    from api.models.mcp_client import MCPClient

    async with get_task_session() as db:
        creds = (await db.execute(select(Credential))).scalars().all()
        cutoff_30 = datetime.now(timezone.utc) + timedelta(days=30)
        for c in creds:
            findings["credential_expiry"]["total"] += 1
            if c.expires_at is None:
                findings["credential_expiry"]["unbounded"] += 1
                continue
            exp = c.expires_at if c.expires_at.tzinfo else c.expires_at.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                findings["credential_expiry"]["expired"] += 1
            elif exp < cutoff_30:
                findings["credential_expiry"]["expiring_30d"] += 1

        clients = (await db.execute(select(MCPClient))).scalars().all()
        cutoff_90 = datetime.now(timezone.utc) - timedelta(days=90)
        for cl in clients:
            if not cl.is_active:
                continue
            last = cl.last_used_at if (cl.last_used_at and cl.last_used_at.tzinfo) else (
                cl.last_used_at.replace(tzinfo=timezone.utc) if cl.last_used_at else None
            )
            if cl.expires_at:
                exp = cl.expires_at if cl.expires_at.tzinfo else cl.expires_at.replace(tzinfo=timezone.utc)
                if exp < datetime.now(timezone.utc):
                    findings["mcp_expired"].append({
                        "id": str(cl.id), "name": cl.name,
                        "expired_at": exp.isoformat(),
                    })
            if last is None or last < cutoff_90:
                findings["mcp_orphans"].append({
                    "id": str(cl.id), "name": cl.name,
                    "last_used_at": last.isoformat() if last else None,
                })

        from api.services.notifier import notify_event
        await notify_event(db, "security.report", findings)
        await db.commit()

    n_vulns = len(findings["python_vulns"])
    n_orphans = len(findings["mcp_orphans"])
    n_expired_mcp = len(findings["mcp_expired"])
    if findings["python_scan_error"]:
        logger.error(
            "security scan: Python CVE scan DID NOT RUN (%s). The report says so "
            "explicitly rather than implying an all-clear.",
            findings["python_scan_error"],
        )
    logger.info(
        "security scan: %d Python vulns, %d expired creds, %d MCP orphans, %d MCP expired",
        n_vulns,
        findings["credential_expiry"]["expired"],
        n_orphans,
        n_expired_mcp,
    )


async def _pip_audit() -> tuple[list[dict], str | None]:
    """Run pip-audit and parse JSON output.

    Returns (vulnerabilities, error). `error` is None only when the scan
    actually ran to completion. An empty list with error=None means "scanned,
    found nothing". An empty list with an error string means "did not scan".

    This used to return a bare [] on every failure path, and the notifier
    rendered any empty list as "Python CVEs: none detected". A network failure
    against PyPI, the 180s timeout, or malformed JSON therefore produced a
    weekly email that actively asserted the absence of CVEs nobody had looked
    for. Silence and an all-clear are not the same message.

    Bug #16 (deferred, too large for this batch): pip-audit currently runs
    inside the api container as the celery worker user (often root) and
    contacts the public PyPI / OSV indexes. A poisoned PyPI mirror or a CVE
    in pip-audit itself would have full network/FS reach inside the api
    container. Long-term mitigation is to invoke pip-audit inside a
    short-lived, network-restricted container (e.g. ``docker run --rm
    --network none --read-only``), tracked separately.
    """
    if not shutil.which("pip-audit"):
        logger.warning("pip-audit not on PATH; skipping Python CVE scan")
        return [], "pip-audit not installed"
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "pip-audit", "--format=json", "--progress-spinner=off",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError:
        # Without the kill the subprocess outlives the task and keeps holding
        # its pipes, so repeated weekly timeouts leak one process each.
        logger.error("pip-audit timed out after 3 min")
        if proc is not None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
        return [], "pip-audit timed out after 180s"
    except OSError as exc:
        logger.error("pip-audit could not be started: %s", exc)
        return [], f"pip-audit could not be started: {exc}"

    if proc.returncode not in (0, 1):
        # pip-audit exits 1 when it FINDS vulnerabilities, which is a
        # successful scan. Anything else means it did not complete.
        err = (stderr or b"").decode(errors="replace").strip()[:200]
        logger.error("pip-audit exited %s: %s", proc.returncode, err)
        return [], f"pip-audit exited {proc.returncode}: {err or 'no stderr'}"
    if not stdout:
        detail = (stderr or b"").decode(errors="replace")[:200]
        logger.warning("pip-audit produced no output: %s", detail)
        return [], f"pip-audit produced no output: {detail or 'no stderr'}"
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        logger.error("pip-audit output was not valid JSON: %s", exc)
        return [], f"pip-audit output was not valid JSON: {exc}"
    out: list[dict] = []
    deps = data.get("dependencies") if isinstance(data, dict) else data
    if deps is None:
        # Valid JSON in a shape we do not recognise. Not the same as an
        # audit of zero packages.
        return [], "pip-audit returned JSON without a dependencies list"
    if not deps:
        # An audit that inspected zero packages has not cleared anything.
        return [], "pip-audit reported zero packages, nothing was audited"
    for dep in deps:
        for vuln in dep.get("vulns", []):
            out.append({
                "package": dep.get("name"),
                "version": dep.get("version"),
                "id": vuln.get("id"),
                "fix_versions": vuln.get("fix_versions", []),
                "description": (vuln.get("description") or "")[:300],
            })
    return out, None
