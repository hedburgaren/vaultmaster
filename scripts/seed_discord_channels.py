#!/usr/bin/env python3
"""Seed Discord notification channels in VaultMaster.

Creates (or updates) NotificationChannel rows for the four hedburgaren
Discord channels routed via the arc-discord-bridge sidecar. Idempotent —
existing rows with the same `name` are updated in place.

Usage:
    python -m scripts.seed_discord_channels \
        --base-url https://vm.hedburgaren.se \
        --username chrille \
        --password '<password>' \
        --bridge-url 'http://host.docker.internal:8600' \
        --bridge-token '<arc-bridge-token>'

After seeding, the script POSTs /test on every Discord channel and prints
the result so you can verify Discord receives a real message.

Notes:
- The bridge URL must be reachable from the VaultMaster API container.
  Default `http://host.docker.internal:8600` works because
  docker-compose.yml maps `host.docker.internal:host-gateway` and the
  arc-discord-bridge listens on 127.0.0.1:8600 on the host.
- All four channels currently fire on the same triggers — per-domain
  routing (job_name pattern → channel) is a separate task.
"""

from __future__ import annotations

import argparse
import sys

import httpx


CHANNELS = [
    {"name": "Discord #allmänt", "channel": "allmänt"},
    {"name": "Discord #plastshop", "channel": "plastshop"},
    {"name": "Discord #arcgruppen", "channel": "arcgruppen"},
    {"name": "Discord #heartpro", "channel": "heartpro"},
]

DEFAULT_TRIGGERS = [
    "run.failed",
    "run.partial",
    "storage.warning",
    "storage.critical",
    "server.offline",
]


def main() -> int:
    p = argparse.ArgumentParser(description="Seed Discord channels into VaultMaster")
    p.add_argument("--base-url", default="https://vm.hedburgaren.se")
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--bridge-url", default="http://host.docker.internal:8600")
    p.add_argument("--bridge-token", required=True)
    p.add_argument("--triggers", default=",".join(DEFAULT_TRIGGERS))
    p.add_argument("--no-test", action="store_true", help="Skip /test calls after seeding")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    triggers = [t.strip() for t in args.triggers.split(",") if t.strip()]

    with httpx.Client(base_url=args.base_url, timeout=20.0, verify=True) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": args.username, "password": args.password},
        )
        if resp.status_code != 200:
            print(f"login failed: {resp.status_code} {resp.text}", file=sys.stderr)
            return 1
        token = resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"

        resp = client.get("/api/v1/notifications/channels")
        resp.raise_for_status()
        existing = {c["name"]: c for c in resp.json()}

        for ch in CHANNELS:
            payload = {
                "name": ch["name"],
                "channel_type": "discord",
                "config": {
                    "bridge_url": args.bridge_url,
                    "bridge_token": args.bridge_token,
                    "channel": ch["channel"],
                    "embeds_enabled": True,
                },
                "triggers": triggers,
            }
            if args.dry_run:
                print(f"[dry-run] upsert {ch['name']} -> {payload['triggers']}")
                continue

            if ch["name"] in existing:
                cid = existing[ch["name"]]["id"]
                resp = client.put(f"/api/v1/notifications/channels/{cid}", json=payload)
                if resp.status_code >= 300:
                    print(f"[update] FAILED {ch['name']}: {resp.status_code} {resp.text}", file=sys.stderr)
                    continue
                print(f"[update] {ch['name']} (id={cid})")
            else:
                resp = client.post("/api/v1/notifications/channels", json=payload)
                if resp.status_code >= 300:
                    print(f"[create] FAILED {ch['name']}: {resp.status_code} {resp.text}", file=sys.stderr)
                    continue
                print(f"[create] {ch['name']} (id={resp.json()['id']})")

        if args.no_test or args.dry_run:
            return 0

        resp = client.get("/api/v1/notifications/channels")
        for c in resp.json():
            if c["channel_type"] != "discord":
                continue
            t = client.post(f"/api/v1/notifications/channels/{c['id']}/test")
            try:
                payload = t.json()
            except Exception:
                payload = {"raw": t.text}
            ok = payload.get("success")
            mark = "OK " if ok else "FAIL"
            print(f"[{mark}] {c['name']}: {payload.get('message')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
