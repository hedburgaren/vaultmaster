#!/usr/bin/env python3
"""Import VaultMaster credentials from a Notion page.

Walks the Notion block tree under a given page id, extracts table rows
of the form (Parameter | Value), and writes them as credential items in
VaultMaster: every heading becomes one item (the overlying title), and
its parameter rows become that item's fields. Idempotent on title;
existing items get their fields matched by field title and updated.

Usage:
    python -m scripts.import_notion_credentials \
        --base-url http://localhost:8000 \
        --vm-username admin \
        --vm-password '<vm-password>' \
        --notion-token '<notion-integration-token>' \
        --page-id '<notion-page-id>'

Default is dry-run. Add --apply to actually write to VM.

Heuristics:
- Tables with header row "Parameter | Värde" or "Parameter | Value"
  are treated as credential tables.
- Each row becomes one field on the heading's item.
  Example: heading "Groq" + row "API-nyckel" gives item "Groq" with a
  field titled "API-nyckel".
- Empty / placeholder values (single dash, "N/A", "TBD") are skipped.
- A `notion-import` provenance is set on every imported item.
- Fields that exist in VM but are absent from the page are NOT deleted;
  the page may be a partial view.

After successful import, the Notion page can optionally be marked with
a [migrerad]-prefix in the title; see README. This script does NOT
modify the Notion page.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from typing import Iterable

import httpx


NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

PARAM_HEADERS = {"parameter", "param", "field", "fält"}
VALUE_HEADERS = {"värde", "value", "data"}

PLACEHOLDER_VALUES = {"", "—", "-", "n/a", "tbd", "todo", "?"}


def fetch_notion_blocks(token: str, page_id: str, depth: int = 0) -> list[dict]:
    """Recursively fetch the children blocks of `page_id`."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }
    blocks: list[dict] = []
    cursor = None
    with httpx.Client(timeout=20.0) as client:
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            resp = client.get(f"{NOTION_API}/blocks/{page_id}/children", headers=headers, params=params)
            resp.raise_for_status()
            j = resp.json()
            for b in j.get("results", []):
                b["_depth"] = depth
                blocks.append(b)
                if b.get("has_children") and b.get("type") in ("table", "toggle", "callout", "synced_block"):
                    blocks.extend(fetch_notion_blocks(token, b["id"], depth + 1))
            if not j.get("has_more"):
                break
            cursor = j.get("next_cursor")
    return blocks


def extract_text(rich_text: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in (rich_text or []))


def walk_credential_pairs(blocks: list[dict]) -> Iterable[tuple[str, str, str]]:
    """Yield (heading_path, parameter, value) tuples extracted from
    Parameter|Value tables."""
    heading_stack: list[tuple[int, str]] = []  # (level, text)

    i = 0
    while i < len(blocks):
        b = blocks[i]
        bt = b.get("type")

        if bt in ("heading_1", "heading_2", "heading_3"):
            level = int(bt.split("_")[1])
            text = extract_text(b.get(bt, {}).get("rich_text", []))
            heading_stack = [(lv, t) for (lv, t) in heading_stack if lv < level]
            heading_stack.append((level, text.strip()))
            i += 1
            continue

        if bt == "table":
            table_id = b["id"]
            # Collect rows that immediately follow this table block in our flat list.
            rows = []
            j = i + 1
            while j < len(blocks) and blocks[j].get("type") == "table_row":
                rows.append(blocks[j])
                j += 1
            i = j
            if not rows:
                continue

            # Detect Parameter|Value header
            header_cells = rows[0].get("table_row", {}).get("cells", [])
            if len(header_cells) < 2:
                continue
            h0 = extract_text(header_cells[0]).strip().lower()
            h1 = extract_text(header_cells[1]).strip().lower()
            if h0 not in PARAM_HEADERS or h1 not in VALUE_HEADERS:
                continue

            heading_path = " / ".join(t for _, t in heading_stack)
            for row in rows[1:]:
                cells = row.get("table_row", {}).get("cells", [])
                if len(cells) < 2:
                    continue
                param = extract_text(cells[0]).strip()
                value = extract_text(cells[1]).strip()
                if not param or value.lower() in PLACEHOLDER_VALUES:
                    continue
                # Strip wrapping backticks (Notion code-style) from values
                if value.startswith("`") and value.endswith("`"):
                    value = value[1:-1]
                yield heading_path, param, value
            continue

        i += 1


def login(client: httpx.Client, base_url: str, username: str, password: str) -> str:
    resp = client.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    if resp.status_code != 200:
        raise SystemExit(f"login failed: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


def auth_with_api_key(client: httpx.Client, api_key: str) -> None:
    client.headers["X-API-Key"] = api_key
    resp = client.get("/api/v1/auth/me")
    if resp.status_code != 200:
        raise SystemExit(f"api-key check failed: {resp.status_code} {resp.text}")


def list_existing(client: httpx.Client) -> dict[str, dict]:
    """Map item title -> item payload (fields metadata included, never values)."""
    resp = client.get("/api/v1/credentials")
    resp.raise_for_status()
    return {c["title"]: c for c in resp.json()}


def upsert_item(
    client: httpx.Client,
    existing: dict[str, dict],
    title: str,
    fields: list[tuple[str, str]],
    tags: list[str],
    provenance: str,
) -> str:
    """Create or update one item so that it holds exactly these fields.

    Existing fields are matched by title and PATCHed (value updated);
    new fields are added. Fields already in the item but absent from the
    import are left alone: the Notion page may legitimately be a partial
    view, and deleting a field the page does not mention would destroy a
    secret nobody asked us to destroy.
    """
    if title in existing:
        item = existing[title]
        cid = item["id"]
        current = {f["field_title"]: f["id"] for f in item.get("fields", [])}
        notes = []
        for field_title, value in fields:
            if field_title in current:
                resp = client.patch(
                    f"/api/v1/credentials/fields/{current[field_title]}",
                    json={"value": value},
                )
                if resp.status_code >= 300:
                    notes.append(f"PATCH field {field_title}: FAILED {resp.status_code} {resp.text[:120]}")
            else:
                resp = client.post(
                    f"/api/v1/credentials/items/{cid}/fields",
                    json={"field_title": field_title, "value": value},
                )
                if resp.status_code >= 300:
                    notes.append(f"POST field {field_title}: FAILED {resp.status_code} {resp.text[:120]}")
        resp = client.patch(f"/api/v1/credentials/items/{cid}", json={"tags": tags, "provenance": provenance})
        if resp.status_code >= 300:
            notes.append(f"PATCH item: FAILED {resp.status_code} {resp.text[:120]}")
        return "; ".join(notes) if notes else f"PATCH {title} (id={cid}, {len(fields)} field(s))"

    payload = {
        "title": title,
        "tags": tags,
        "provenance": provenance,
        "fields": [{"field_title": ft, "value": v} for ft, v in fields],
    }
    resp = client.post("/api/v1/credentials", json=payload)
    if resp.status_code >= 300:
        return f"POST  {title}: FAILED {resp.status_code} {resp.text[:120]}"
    return f"POST  {title} (id={resp.json()['id']}, {len(fields)} field(s))"


def main() -> int:
    p = argparse.ArgumentParser(description="Import credentials from a Notion page into VaultMaster")
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--vm-username")
    p.add_argument("--vm-password")
    p.add_argument("--vm-api-key", help="Alternative to --vm-username/--vm-password: an X-API-Key value")
    p.add_argument("--notion-token", required=True)
    p.add_argument("--page-id", required=True, help="Notion page id (32 hex chars, with or without dashes)")
    p.add_argument("--apply", action="store_true", help="Actually write to VaultMaster (default: dry-run)")
    p.add_argument("--limit", type=int, default=0, help="Limit imports for testing")
    args = p.parse_args()
    if not args.vm_api_key and not (args.vm_username and args.vm_password):
        p.error("provide either --vm-api-key OR --vm-username + --vm-password")

    page_id = re.sub(r"-", "", args.page_id)
    print(f"[notion] fetching blocks for page {page_id}")
    blocks = fetch_notion_blocks(args.notion_token, page_id)
    print(f"[notion] {len(blocks)} blocks total")

    pairs = list(walk_credential_pairs(blocks))
    print(f"[parse]  extracted {len(pairs)} (heading, parameter, value) triples")
    if not pairs:
        print("[parse]  nothing to import; verify the page contains 'Parameter | Värde'-style tables", file=sys.stderr)
        return 1

    # One heading becomes ONE item; its parameters become that item's fields.
    grouped: dict[str, list[tuple[str, str]]] = {}
    for heading, param, value in pairs:
        grouped.setdefault(heading or param, []).append((param, value))

    heading_dash = re.compile(r"[\u2014\-]+")
    if not args.apply:
        for heading, fields in list(grouped.items())[: args.limit or len(grouped)]:
            tags = [t.strip().lower() for t in heading_dash.split(heading) if t.strip()] or []
            preview = ", ".join(f"{ft}={v[:6]}…" if len(v) > 6 else f"{ft}={v}" for ft, v in fields)
            print(f"[dry]    {heading}  fields={len(fields)}  tags={tags}  {preview}")
        print(f"\nRe-run with --apply to write {min(len(grouped), args.limit or len(grouped))} credential items to {args.base_url}.")
        return 0

    with httpx.Client(base_url=args.base_url, timeout=20.0) as client:
        if args.vm_api_key:
            auth_with_api_key(client, args.vm_api_key)
        else:
            token = login(client, args.base_url, args.vm_username, args.vm_password)
            client.headers["Authorization"] = f"Bearer {token}"

        existing = list_existing(client)
        print(f"[vm]     {len(existing)} existing credential items in VM")

        provenance = f"notion-import:{page_id}"
        n = 0
        for heading, fields in list(grouped.items())[: args.limit or len(grouped)]:
            tags = [t.strip().lower() for t in heading_dash.split(heading) if t.strip()] or []
            print("  " + upsert_item(client, existing, heading, fields, tags, provenance))
            n += 1
            time.sleep(0.05)

        print(f"\nimport complete: {n} credential items processed ({len(pairs)} fields total)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
