"""After the backup-flow deploy: plastop stops being pulled on fixed times and
gets a check-in token instead (Chrille 2026-11-15, card DEV-13).

- PUT schedule_cron = null on every active job of the server plastop.
- POST /servers/<plastop>/checkin-token, raw token written once to
  ~/.config/vaultmaster/plastop-checkin.env (mode 600) on plastdesk, for the
  install on plastop (laptop/install-on-plastop.sh), which removes it here.

Credentials from the repository's .env (VM_API, VM_USER, VM_PASSWORD).
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path("/home/chrille/dev/projects/vaultmaster")
ENV = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines()
           if "=" in l and not l.startswith("#"))
API = ENV["VM_API"].rstrip("/")
OUT = Path.home() / ".config/vaultmaster/plastop-checkin.env"


def call(method, path, token=None, body=None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=60) as r:
        return json.loads(r.read() or b"null")


def main():
    tok = call("POST", "/auth/login", body={"username": ENV["VM_USER"], "password": ENV["VM_PASSWORD"]})["access_token"]
    servers = {s["name"]: s for s in call("GET", "/servers", tok)}
    plastop = servers.get("plastop") or sys.exit("STOPP: servern plastop finns inte")
    tags = [t.lower() for t in plastop.get("tags") or []]
    if "intermittent" not in tags:
        sys.exit("STOPP: plastop saknar taggen intermittent")
    jobs = [j for j in call("GET", "/jobs", tok) if j["server_id"] == plastop["id"]]
    for j in jobs:
        if j.get("schedule_cron") is None:
            print(f"redan utan schema: {j['name']}")
            continue
        call("PUT", f"/jobs/{j['id']}", tok, {"schedule_cron": None})
        after = call("GET", f"/jobs/{j['id']}", tok)
        if after.get("schedule_cron") is not None:
            sys.exit(f"STOPP: schemat för {j['name']} finns kvar")
        print(f"schema borttaget: {j['name']} (var {j['schedule_cron']})")
    res = call("POST", f"/servers/{plastop['id']}/checkin-token", tok)
    raw = res.get("token") or res.get("checkin_token")
    if not raw:
        sys.exit("STOPP: inget token i svaret")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(OUT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"VM_API={API}\nVM_CHECKIN_TOKEN={raw}\n")
    print(f"incheckningstoken skapat och sparat i {OUT} (600), visas inte här")


if __name__ == "__main__":
    main()
