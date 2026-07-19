"""Adversarial audit for the failure class this codebase keeps producing.

Three separate bugs found on 2026-07-19 shared one shape: code reported success
for work it never performed. Not crashes, not wrong answers. Silence dressed as
success, which is worse than an outage because nothing prompts anyone to look.

  1. `is_encrypted=job.encrypt` recorded the operator's intent as the outcome.
     29 jobs asked for encryption, 5336 artifacts claimed to have it, every one
     was plain gzip, and all of it replicated to Google Drive.

  2. Rotation set `is_deleted` and nothing ever deleted a file. Retention was
     enforced on paper for 138 days under a 90-day policy.

  3. `if filename and remote_path and destinations:` silently skipped the entire
     transfer for custom jobs, which always return `remote_path=""`. 11
     databases, 615 runs marked successful, nothing ever left the staging
     directory.

Each was invisible from the outside: green dashboards, success rows, no errors.

This script sends the codebase to an independent model in focused chunks and
asks it to hunt that specific shape. Independent matters: the same author who
wrote a bug tends to re-read their intent rather than the code, and two of the
three above were found only because an unrelated task tripped over them.

Usage:
    python3 scripts/audit_silent_success.py                 # full audit
    python3 scripts/audit_silent_success.py --chunk 3       # single chunk
    python3 scripts/audit_silent_success.py --list          # show chunks
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROXY = "http://127.0.0.1:4000/v1/chat/completions"
MODEL = "kimi"

# Moonshot rejects anything other than 1 for this model family (HTTP 400).
TEMPERATURE = 1

# Kimi reasons and answers out of the same budget, and it will happily reason
# until it hits the cap and emit nothing at all. A 120-token cap produced 119
# reasoning tokens and empty content. So did 8000 on a real audit chunk: all
# seven chunks returned reasoning_tokens=7999 and no answer, which the first
# version of this script cheerfully reported as "0 findings".
#
# That is the exact defect class this script exists to find, reproduced in the
# tool itself. Hence both the larger budget and the starvation check in
# call_kimi(): an empty answer must be a loud failure, never a clean result.
MAX_TOKENS = 125000

# Chunks are grouped by concern rather than by directory, so related code is
# reviewed together. A bug like #3 is only visible when the producer
# (backup_executor) and the consumer (backup_tasks) are read side by side.
CHUNKS = [
    # --- already covered in the first pass, kept so a full run is a full run ---
    ("backup-executor", ["api/services/backup_executor.py"]),
    ("ssh-transport", ["api/services/ssh_client.py"]),
    ("backup-orchestration", ["api/tasks/backup_tasks.py"]),
    ("scheduling", ["api/tasks/celery_app.py", "api/tasks/rotation_tasks.py"]),
    ("retention-logic", ["api/services/rotation.py", "api/services/purge.py"]),
    ("cleanup", ["api/tasks/cleanup_tasks.py"]),
    ("storage-transfer", ["api/services/rclone_client.py", "api/tasks/storage_tasks.py"]),
    ("restore-validation", ["api/services/restore_validator.py", "api/tasks/validation_tasks.py"]),
    ("crypto", [
        "api/services/age_crypto.py",
        "api/services/encryption.py",
        "api/services/credentials_crypto.py",
    ]),
    ("alerting", ["api/services/notifier.py", "api/tasks/anomaly_tasks.py"]),

    # --- never audited until 2026-07-19 ---
    ("core-app", [
        "api/main.py",
        "api/config.py",
        "api/database.py",
        "api/rate_limiter.py",
    ]),
    ("auth-and-access", [
        "api/auth.py",
        "api/routers/auth.py",
        "api/routers/users.py",
        "api/middleware/audit.py",
    ]),
    ("mcp-surface", [
        "api/mcp/server.py",
        "api/mcp/auth.py",
        "api/routers/mcp_clients.py",
    ]),
    ("router-jobs-runs", [
        "api/routers/jobs.py",
        "api/routers/runs.py",
    ]),
    ("router-artifacts-storage", [
        "api/routers/artifacts.py",
        "api/routers/storage.py",
    ]),
    ("router-servers-retention", [
        "api/routers/servers.py",
        "api/routers/retention.py",
    ]),
    ("router-secrets", [
        "api/routers/credentials.py",
        "api/routers/notifications.py",
        "api/services/oauth_storage.py",
    ]),
    ("router-observability", [
        "api/routers/dashboard.py",
        "api/routers/metrics.py",
        "api/routers/audit.py",
        "api/routers/validations.py",
    ]),
    ("router-misc", [
        "api/routers/webhooks.py",
        "api/routers/system_settings.py",
    ]),
    ("schemas-and-models", [
        "api/schemas.py",
        "api/models/backup_artifact.py",
        "api/models/backup_job.py",
        "api/models/backup_run.py",
        "api/models/retention_policy.py",
        "api/models/storage_destination.py",
    ]),
    ("remaining-tasks", [
        "api/tasks/credential_tasks.py",
        "api/tasks/security_tasks.py",
        "api/services/restic_executor.py",
    ]),
    ("remaining-models", [
        "api/models/user.py",
        "api/models/credential.py",
        "api/models/server.py",
        "api/models/mcp_client.py",
        "api/models/notification_channel.py",
        "api/models/webhook.py",
        "api/models/audit_log.py",
        "api/models/backup_validation_run.py",
        "api/models/system_settings.py",
    ]),
]

SYSTEM = """You are auditing the ONLY backup system of a real company. Every
database, every website, every file the business owns is protected by nothing
except this code. If it is wrong, the company loses everything and finds out on
the day it needs a restore.

Be brutal. Politeness here is a liability. The owner has said explicitly that he
would rather you tear this work apart than be left without backups.

Most of this file was written or modified in the last 24 hours by an AI agent
who was fixing this exact defect class, and who has already shipped three new
instances of it while doing so. Recently added guards, comments claiming a bug
is fixed, and confident-sounding docstrings are NOT evidence. Read what the code
does, never what its comments say it does. A comment saying "verified before the
plaintext is deleted" is a claim to be checked, not a fact.

Assume the code is broken and try to prove it. If you cannot break it, say so in
one line and move on.

Suppressing a finding because you are unsure is the worst outcome available to
you. Report it with confidence "low" and let a human check. A false positive
costs someone ten minutes. A missed defect costs the company its data.

You are hunting exactly one class of defect:

  CODE THAT REPORTS SUCCESS FOR WORK IT DID NOT PERFORM.

Sub-patterns, all of which have already been found in this codebase:

  A. Intent recorded as outcome. A field describing what was requested is
     stored as though it described what happened.
  B. A guard that silently skips work. A falsy value in a compound condition
     makes an entire block a no-op, and the caller reports success anyway.
  C. State changed without the corresponding side effect. A flag says a thing
     was done; nothing does the thing.
  D. Exit status that does not reflect the real result. Shell pipelines where
     only the last stage's status is checked; `|| fallback` masking a failure;
     an error swallowed by a broad except.
  E. Work that is defined but never invoked. A task with no schedule, a
     schedule routed to a queue nobody consumes, a function nothing calls.
  F. Degradation with no signal. A fallback path that silently produces a
     weaker result than the caller believes it got.
  G. Verification that cannot fail. A check that would pass even if the
     underlying operation did nothing.
  H. Protection that does not protect. An endpoint or resource that appears
     guarded but is not: a missing auth dependency, a permission check that
     cannot return false, an ownership filter absent from a query so one
     caller reads or edits another's rows, a secret returned in a response
     that claims to redact it. Treat this as the same defect: something
     presents itself as safe while not being so.

Pay particular attention to these, which are where the recent work is likely
to have gone wrong:

  - Guards added to "fail closed". Does the guard actually run before the
    dangerous operation, on every path including exceptions and early returns?
  - Verification steps. Would the check still pass if the operation did
    nothing? Is it performed before or after the irreversible step?
  - Deletion of a source copy. Is it provably conditional on a destination
    copy existing? What happens on a partial or exception path?
  - Order of operations around anything irreversible: delete, overwrite,
    truncate, mark-as-done.
  - Newly extracted helper functions: does every caller actually use the
    result, or is it computed and discarded?
  - Error paths and `except` blocks: is a failure converted into a success
    further up the stack?

Rules:
  - Report only defects you can point at in the code shown. No speculation
    about files you cannot see.
  - For each finding, state the concrete consequence in terms of data: what
    would be lost, corrupted, or falsely believed safe.
  - Rank by blast radius, worst first.
  - If a chunk is genuinely clean, say so in one line. Do not pad with style
    notes to look thorough.
  - Ignore formatting, naming, and typing issues entirely. They are not what
    loses data.

Respond as JSON only, no prose outside it:
{"findings":[{"severity":"critical|high|medium","pattern":"A".."G",
"location":"file.py:line or function","claim":"what the code claims",
"reality":"what actually happens","consequence":"data-level impact",
"confidence":"high|medium|low"}],"clean":true|false,"note":"one line"}"""


def master_key() -> str:
    key = subprocess.run(
        ["docker", "exec", "litellm", "printenv", "LITELLM_MASTER_KEY"],
        capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    if not key:
        raise SystemExit("Kunde inte hamta LITELLM_MASTER_KEY fran litellm-containern.")
    return key


def build_payload(name: str, files: list[str]) -> str:
    parts = [f"# Audit chunk: {name}\n"]
    for rel in files:
        p = REPO / rel
        if not p.is_file():
            continue
        body = p.read_text(errors="replace")
        numbered = "\n".join(
            f"{i:5} {line}" for i, line in enumerate(body.splitlines(), 1)
        )
        parts.append(f"\n===== FILE: {rel} =====\n{numbered}\n")
    return "".join(parts)


def call_kimi(key: str, content: str, attempt: int = 0) -> dict:
    req = urllib.request.Request(
        PROXY,
        data=json.dumps({
            "model": MODEL,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": content},
            ],
        }).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            data = json.load(r)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        if attempt < 2:
            return call_kimi(key, content, attempt + 1)
        return {"_error": f"{type(e).__name__}: {e}"}

    if "error" in data:
        return {"_error": str(data["error"])[:300]}

    text = (data["choices"][0]["message"].get("content") or "").strip()
    usage = data.get("usage", {})
    reasoning = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)

    # Reasoning starvation: the model thought until it hit the cap and never
    # answered. Empty content here means "we learned nothing", NOT "the code is
    # clean", and conflating those is how a silent failure becomes a green
    # report. Escalate rather than return an empty finding list.
    if not text:
        if reasoning >= MAX_TOKENS - 50:
            if attempt < 2:
                return call_kimi(key, content, attempt + 1)
            return {"_error": (
                f"Reasoning starvation: {reasoning}/{MAX_TOKENS} tokens spent "
                f"thinking, no answer emitted. Raise MAX_TOKENS or split this "
                f"chunk. NOT a clean result."
            )}
        return {"_error": f"Empty response (reasoning={reasoning}), no answer emitted."}

    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {"_unparsed": text[:4000]}
    parsed["_usage"] = usage
    return parsed


def run_chunk(key, idx, name, files):
    content = build_payload(name, files)
    print(f"  [{idx}] {name:26} {len(content) // 1024:4} KB -> Kimi...", flush=True)
    res = call_kimi(key, content)
    res["_chunk"] = name
    res["_files"] = files
    n = len(res.get("findings", []))
    if "_error" in res:
        print(f"  [{idx}] {name:26} FEL: {res['_error'][:80]}", flush=True)
    else:
        print(f"  [{idx}] {name:26} klar, {n} fynd", flush=True)
    return res


def main() -> int:
    if "--list" in sys.argv:
        for i, (name, files) in enumerate(CHUNKS):
            size = len(build_payload(name, files)) // 1024
            print(f"  {i}  {name:26} {size:4} KB  {len(files)} filer")
        return 0

    key = master_key()
    chunks = list(enumerate(CHUNKS))
    if "--chunk" in sys.argv:
        i = int(sys.argv[sys.argv.index("--chunk") + 1])
        chunks = [(i, CHUNKS[i])]

    print(f"Granskar {len(chunks)} chunk(ar) med {MODEL}, temperature {TEMPERATURE}\n")

    # Two at a time: a heavy reasoning model on a paid API, and rate limits hurt
    # more than the wall-clock saved by going wider.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(run_chunk, key, i, name, files)
            for i, (name, files) in chunks
        ]
        results = [f.result() for f in futures]

    out = REPO / "docs" / "audit-silent-success.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    all_findings = []
    for r in results:
        for f in r.get("findings", []):
            f["_chunk"] = r["_chunk"]
            all_findings.append(f)

    order = {"critical": 0, "high": 1, "medium": 2}
    all_findings.sort(key=lambda f: order.get(f.get("severity", "medium"), 3))

    failed = [r for r in results if "_error" in r or "_unparsed" in r]

    print(f"\n{'='*70}")
    if failed:
        # Say this before the findings, not after. A partial audit read as a
        # complete one is worse than no audit.
        print(f"VARNING: {len(failed)} av {len(results)} chunkar gav INGET svar.")
        print("Resultatet nedan ar ofullstandigt och sager ingenting om de chunkarna.")
        print(f"{'='*70}")
    print(f"{len(all_findings)} fynd fran {len(results) - len(failed)} lyckade chunkar. Rapport: {out}")
    print(f"{'='*70}\n")
    for f in all_findings:
        print(f"[{f.get('severity','?').upper()}] ({f.get('pattern','?')}) {f.get('location','?')}")
        print(f"  pastar   : {f.get('claim','')}")
        print(f"  verklighet: {f.get('reality','')}")
        print(f"  foljd    : {f.get('consequence','')}")
        print(f"  tilltro  : {f.get('confidence','?')}  [{f.get('_chunk')}]")
        print()

    for r in results:
        if "_error" in r:
            print(f"CHUNK-FEL {r['_chunk']}: {r['_error'][:200]}")
        if "_unparsed" in r:
            print(f"OPARSAT SVAR {r['_chunk']}: {r['_unparsed'][:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
