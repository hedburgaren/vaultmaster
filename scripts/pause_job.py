#!/usr/bin/env python3
"""Pause or resume a VaultMaster backup job by ID prefix.

Used to disable jobs that are misbehaving (timeouts, repeated failures)
without going through the UI.

Usage:
    python -m scripts.pause_job \
        --base-url http://localhost:8000 \
        --username admin \
        --password '<pwd>' \
        --id-prefix 8d9a5991 \
        --pause

To resume:
    python -m scripts.pause_job ... --id-prefix 8d9a5991 --resume
"""

from __future__ import annotations

import argparse
import sys

import httpx


def main() -> int:
    p = argparse.ArgumentParser(description="Pause or resume a backup job by ID prefix")
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--id-prefix", required=True, help="UUID prefix that uniquely matches one job")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--pause", action="store_true")
    g.add_argument("--resume", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    target_active = not args.pause  # pause => is_active=False; resume => True

    with httpx.Client(base_url=args.base_url, timeout=20.0) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": args.username, "password": args.password},
        )
        if resp.status_code != 200:
            print(f"login failed: {resp.status_code} {resp.text}", file=sys.stderr)
            return 1
        token = resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"

        resp = client.get("/api/v1/jobs", params={"limit": 200})
        resp.raise_for_status()
        jobs = resp.json()
        matches = [j for j in jobs if str(j["id"]).startswith(args.id_prefix)]
        if not matches:
            print(f"no job matching id-prefix {args.id_prefix}", file=sys.stderr)
            return 2
        if len(matches) > 1:
            print(f"id-prefix {args.id_prefix} matches {len(matches)} jobs:", file=sys.stderr)
            for j in matches:
                print(f"  {j['id']}  {j['name']}", file=sys.stderr)
            print("provide a longer prefix", file=sys.stderr)
            return 3

        job = matches[0]
        action = "pause" if args.pause else "resume"
        print(f"[{action}] {job['id']}  {job['name']}  (currently is_active={job['is_active']})")
        if args.dry_run:
            return 0
        if job["is_active"] == target_active:
            print(f"already in target state (is_active={target_active}), nothing to do")
            return 0

        resp = client.put(f"/api/v1/jobs/{job['id']}", json={"is_active": target_active})
        if resp.status_code >= 300:
            print(f"PUT failed: {resp.status_code} {resp.text}", file=sys.stderr)
            return 4
        print(f"OK, is_active={resp.json()['is_active']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
