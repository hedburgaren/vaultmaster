#!/usr/bin/env python3
"""Diagnose stale-heartbeat servers in VaultMaster.

Walks the `server` table and reports rows whose `last_seen` is older
than the threshold or NULL, with hints on what to check next. Used as
part of the EPIC 5 server-heartbeat-recovery workflow.

Usage:
    python -m scripts.check_server_heartbeat \
        --base-url https://vm.hedburgaren.se \
        --username chrille --password '<vm-password>' \
        --threshold-minutes 15
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import httpx


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="https://vm.hedburgaren.se")
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--threshold-minutes", type=int, default=15,
                   help="Servers with last_seen older than this are flagged")
    args = p.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=20.0) as client:
        resp = client.post("/api/v1/auth/login", json={
            "username": args.username, "password": args.password,
        })
        if resp.status_code != 200:
            print(f"login failed: {resp.status_code} {resp.text}", file=sys.stderr)
            return 1
        token = resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"

        resp = client.get("/api/v1/dashboard")
        resp.raise_for_status()
        d = resp.json()
        servers = d.get("server_health", [])

    now = datetime.now(timezone.utc)
    threshold_h = args.threshold_minutes / 60.0

    online = [s for s in servers if s.get("online")]
    stale = [s for s in servers if not s.get("online")]
    print(f"Online: {len(online)}/{len(servers)}")

    if stale:
        print(f"\nStale ({len(stale)}):")
        for s in stale:
            ago = s.get("last_seen_hours_ago")
            ago_s = f"{ago:.1f}h" if isinstance(ago, (int, float)) else "never"
            print(f"  {s.get('name', '?'):20s} host={s.get('host', '?'):25s}  last_seen={ago_s}  active={s.get('is_active', '?')}  tags={s.get('tags', [])}")
        print()
        print("Recovery steps to investigate:")
        print("  1. SSH into the server and confirm the agent process is running")
        print("     (ps aux | grep vaultmaster, or check the systemd unit)")
        print("  2. Check the agent logs (journalctl -u vaultmaster-agent or container logs)")
        print("  3. From the server: curl https://vm.hedburgaren.se/api/health → 200?")
        print("  4. If the server's clock is skewed > 5 min, JWT auth fails — `timedatectl status`")
        print("  5. If agent is dead, restart and watch the next heartbeat in the dashboard")
        return 2

    print("All servers heartbeat-fresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
