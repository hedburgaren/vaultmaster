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

# Kimi spends a large share of its budget on hidden reasoning tokens before it
# emits anything. A 120-token cap produced 119 reasoning tokens and an empty
# answer. Keep this generous or findings get truncated mid-sentence.
MAX_TOKENS = 8000

# Chunks are grouped by concern rather than by directory, so related code is
# reviewed together. A bug like #3 is only visible when the producer
# (backup_executor) and the consumer (backup_tasks) are read side by side.
CHUNKS = [
    ("backup-execution", [
        "api/services/backup_executor.py",
        "api/services/ssh_client.py",
    ]),
    ("task-orchestration", [
        "api/tasks/backup_tasks.py",
        "api/tasks/celery_app.py",
    ]),
    ("retention", [
        "api/services/rotation.py",
        "api/services/purge.py",
        "api/tasks/rotation_tasks.py",
        "api/tasks/cleanup_tasks.py",
    ]),
    ("storage-transfer", [
        "api/services/rclone_client.py",
        "api/tasks/storage_tasks.py",
    ]),
    ("restore-and-validation", [
        "api/services/restore_validator.py",
        "api/tasks/validation_tasks.py",
    ]),
    ("crypto", [
        "api/services/age_crypto.py",
        "api/services/encryption.py",
        "api/services/credentials_crypto.py",
    ]),
    ("notification-and-alerting", [
        "api/services/notifier.py",
        "api/tasks/anomaly_tasks.py",
    ]),
]

SYSTEM = """You are auditing a backup system. Backup software has an unusual
property: when it fails silently, nobody finds out until they need a restore,
and by then the data is gone. A crash is survivable. A green checkmark over
work that never happened is not.

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

Rules:
  - Report only defects you can point at in the code shown. No speculation
    about files you cannot see.
  - For each finding, state the concrete consequence in terms of data: what
    would be lost, corrupted, or falsely believed safe.
  - Rank by blast radius, worst first.
  - If a chunk is clean for this class, say so plainly rather than padding
    with style notes. A short honest answer beats a long hedged one.
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

    print(f"\n{'='*70}")
    print(f"{len(all_findings)} fynd totalt. Rapport: {out}")
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
