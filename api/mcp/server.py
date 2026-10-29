"""MCP-style REST endpoints for AI agents.

Exposes a small Tools API under /api/mcp/v1/. Each "tool" is a
standalone POST endpoint:

  GET  /api/mcp/v1/tools: tool catalog (introspection)
  POST /api/mcp/v1/tools/search_credentials: search items within what this client may read
  POST /api/mcp/v1/tools/get_credential: fetch field plaintext by item id
  POST /api/mcp/v1/tools/list_backup_status: per-job backup status (needs backup.read)

Auth: X-MCP-Key header -> MCPClient row. Defense is layered: client must
be active and unexpired; credential visibility is granted either coarsely
(item.mcp_enabled plus scope/tag intersection) or granularly (explicit
mcp_grant rows naming exact items, fields, or api scopes for this client
alone); non-credential surfaces require their api scope grant explicitly.
Every call is audit-logged with client_id + purpose. Per-client rate
limiting is enforced via the existing SlowAPI Limiter using the client
UUID as the rate-key.

The point of the granular layer: "this agent may read 2 of 30 keys and
see backup status but write nothing" is one PUT to /mcp-clients/{id}/grants,
and what a client can read is computed here from the grant rows, never
guessed from names or tags.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.mcp.auth import get_mcp_client
from api.models.credential import CredentialItem
from api.models.mcp_client import MCPClient
from api.routers.audit import log_action
from api.schemas import MCPToolCallRequest
from api.services.credentials_crypto import get_crypto

router = APIRouter(prefix="/mcp/v1", tags=["mcp"])


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _credential_visible(item: CredentialItem, client: MCPClient) -> bool:
    """Coarse layer: item opt-in plus scope/tag intersection. Item-grained."""
    if not item.mcp_enabled:
        return False
    client_scopes = set(client.scopes or [])
    if not client_scopes:
        return False  # explicit empty scope = no access
    item_scopes = set(item.mcp_scopes or []) | set(item.tags or [])
    return bool(client_scopes & item_scopes)


# ── Granular grant math (pure, unit-tested) ──

def client_api_scopes(client) -> set[str]:
    """Api scopes granted to this client by name (e.g. 'backup.read')."""
    return {
        g.resource_id
        for g in (client.grants or [])
        if g.resource_type == "api"
    }


def granted_item_ids(client) -> set[str]:
    return {
        g.resource_id
        for g in (client.grants or [])
        if g.resource_type == "credential_item"
    }


def granted_field_ids(client) -> set[str]:
    return {
        g.resource_id
        for g in (client.grants or [])
        if g.resource_type == "credential_field"
    }


def fields_visible_to(item, client) -> list:
    """The fields of `item` this exact client may read, in sort order.

    All fields when the coarse layer exposes the item or the client holds a
    grant on the item; otherwise exactly the individually granted fields.
    An explicit grant deliberately overrides mcp_enabled for this client
    alone: the grant is the opt-in.
    """
    ordered = sorted(item.fields, key=lambda f: f.sort_order)
    if _credential_visible(item, client) or str(item.id) in granted_item_ids(client):
        return list(ordered)
    field_grants = granted_field_ids(client)
    return [f for f in ordered if str(f.id) in field_grants]


def item_visible_to(item, client) -> bool:
    """True when at least one field of the item is readable."""
    return bool(fields_visible_to(item, client))


def client_may(client, scope: str) -> bool:
    """Non-credential surfaces are granted by explicit api scope only."""
    return scope in client_api_scopes(client)


# ── Tool catalog (introspection) ──
TOOL_CATALOG = [
    {
        "name": "search_credentials",
        "description": (
            "Search credential items readable by the calling MCP client: either "
            "tag-visibility or an explicit grant. Returns metadata only (id, title, "
            "tags, expires_at, and the field titles this client may read). Plaintext "
            "is never returned by this tool; use get_credential to fetch values."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring filter on title / description"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Restrict to items tagged with ANY of these tags"},
                "limit": {"type": "integer", "default": 20, "maximum": 100},
            },
        },
    },
    {
        "name": "get_credential",
        "description": (
            "Fetch plaintext values of a credential item by id. Requires a 'purpose' string "
            "which is recorded in the audit log. Pass field_title to get exactly one field; "
            "omit it to get every field this client may read (individually granted fields "
            "only, when that is the grant). Fields outside the grant answer 404."
        ),
        "input_schema": {
            "type": "object",
            "required": ["id", "purpose"],
            "properties": {
                "id": {"type": "string", "description": "UUID of the credential item"},
                "field_title": {"type": "string", "description": "Title of one field, e.g. 'inloggningsnamn'. Optional; omit for all readable fields."},
                "purpose": {"type": "string", "description": "Why the agent needs this value (audit-logged)"},
            },
        },
    },
    {
        "name": "list_backup_status",
        "description": (
            "Per-job backup status: schedule, last run outcome, last success, last "
            "failure with its error, and size of the latest artifact. Requires the "
            "backup.read grant; read-only, no triggering, no writing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "include_inactive": {"type": "boolean", "default": False, "description": "Include paused jobs"},
            },
        },
    },
]


@router.get("/tools")
async def list_tools(client: MCPClient = Depends(get_mcp_client)):
    """Tool catalog. Authenticated to keep schema names off public surface."""
    return {
        "tools": TOOL_CATALOG,
        "client": {
            "name": client.name,
            "scopes": client.scopes or [],
            "grants": {
                "credential_items": sorted(granted_item_ids(client)),
                "credential_fields": sorted(granted_field_ids(client)),
                "api_scopes": sorted(client_api_scopes(client)),
            },
        },
    }


@router.post("/tools/search_credentials")
async def tool_search_credentials(
    body: MCPToolCallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    client: MCPClient = Depends(get_mcp_client),
):
    args = body.arguments or {}
    query = (args.get("query") or "").strip().lower()
    tags = args.get("tags") or []
    try:
        limit = int(args.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))

    result = await db.execute(select(CredentialItem).options(selectinload(CredentialItem.fields)))
    rows = result.scalars().all()

    matches = []
    for item in rows:
        visible = fields_visible_to(item, client)
        if not visible:
            continue
        if tags:
            if not (set(item.tags or []) & set(tags)):
                continue
        if query:
            hay = (item.title or "").lower() + " " + (item.description or "").lower()
            if query not in hay:
                continue
        matches.append({
            "id": str(item.id),
            "title": item.title,
            "tags": item.tags or [],
            "expires_at": item.expires_at.isoformat() if item.expires_at else None,
            "description": item.description,
            "fields": [f.field_title for f in visible],
        })
        if len(matches) >= limit:
            break

    await log_action(
        db,
        action="mcp.credential.search",
        resource_type="mcp_client",
        resource_id=str(client.id),
        detail=f"q={query!r} tags={tags} hits={len(matches)}",
        meta={"client_name": client.name, "scopes": client.scopes or []},
        ip_address=_client_ip(request),
    )

    return {"tool": "search_credentials", "results": matches, "count": len(matches)}


@router.post("/tools/get_credential")
async def tool_get_credential(
    body: MCPToolCallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    client: MCPClient = Depends(get_mcp_client),
):
    args = body.arguments or {}
    raw_id = args.get("id")
    field_title = (args.get("field_title") or "").strip()
    purpose = (args.get("purpose") or "").strip()
    if not raw_id or not purpose:
        raise HTTPException(status_code=400, detail="'id' and 'purpose' are required")
    try:
        cid = uuid.UUID(str(raw_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="'id' is not a valid UUID")

    result = await db.execute(
        select(CredentialItem)
        .options(selectinload(CredentialItem.fields))
        .where(CredentialItem.id == cid)
    )
    item = result.scalar_one_or_none()
    visible = fields_visible_to(item, client) if item else []
    if not visible:
        # Not found, not tag-visible and not granted are the same answer,
        # so existence itself does not leak.
        await log_action(
            db,
            action="mcp.credential.get.denied",
            resource_type="credential_item",
            resource_id=str(cid),
            detail=f"client={client.name} not granted purpose={purpose!r}",
            ip_address=_client_ip(request),
        )
        await db.commit()  # denial must survive the 404 (see backup_status twin)
        raise HTTPException(status_code=404, detail="Credential not found or not visible to this client")

    fields = visible
    if field_title:
        fields = [f for f in fields if f.field_title == field_title]
        if not fields:
            await log_action(
                db,
                action="mcp.credential.get.denied",
                resource_type="credential_item",
                resource_id=str(item.id),
                detail=f"client={client.name} field {field_title!r} not granted purpose={purpose!r}",
                ip_address=_client_ip(request),
            )
            await db.commit()  # denial must survive the 404 (see backup_status twin)
            raise HTTPException(status_code=404, detail=f"No field titled '{field_title}' readable on this item")

    crypto = get_crypto()
    values = {}
    now = datetime.now(timezone.utc)
    for f in fields:
        values[f.field_title] = crypto.decrypt(f.encrypted_value)
        f.reveal_count = (f.reveal_count or 0) + 1
        f.last_revealed_at = now
    item.reveal_count = (item.reveal_count or 0) + 1
    item.last_revealed_at = now
    await db.flush()

    await log_action(
        db,
        action="mcp.credential.get",
        resource_type="credential_item",
        resource_id=str(item.id),
        detail=f"client={client.name} fields={sorted(values.keys())} purpose={purpose!r}",
        meta={"client_id": str(client.id), "client_name": client.name},
        ip_address=_client_ip(request),
    )

    return {
        "tool": "get_credential",
        "id": str(item.id),
        "title": item.title,
        "fields": values,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
    }


@router.post("/tools/list_backup_status")
async def tool_list_backup_status(
    body: MCPToolCallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    client: MCPClient = Depends(get_mcp_client),
):
    """Read-only job status for agents holding the backup.read grant.

    Answers what an operator would ask first: did the last run of each job
    succeed, when did it last succeed, and what went wrong when it did not.
    There is deliberately no trigger/modify counterpart: an agent that can
    read status cannot write anything.
    """
    if not client_may(client, "backup.read"):
        await log_action(
            db,
            action="mcp.backup_status.denied",
            resource_type="mcp_client",
            resource_id=str(client.id),
            detail=f"client={client.name} lacks backup.read",
            ip_address=_client_ip(request),
        )
        # Commit before raising: the dependency teardown rolls back on any
        # exception leaving the endpoint, and a denial must leave its trail.
        await db.commit()
        raise HTTPException(status_code=403, detail="This client does not hold the backup.read grant")

    args = body.arguments or {}
    include_inactive = bool(args.get("include_inactive"))

    from api.models.backup_job import BackupJob
    from api.models.backup_run import BackupRun

    jobs = (await db.execute(
        select(BackupJob).options(selectinload(BackupJob.runs))
    )).scalars().all()

    out = []
    for job in sorted(jobs, key=lambda j: j.name.lower()):
        if not job.is_active and not include_inactive:
            continue
        runs = sorted(job.runs or [], key=lambda r: r.started_at or r.created_at, reverse=True)
        last = runs[0] if runs else None
        last_ok = next((r for r in runs if r.status == "success"), None)
        last_failed = next((r for r in runs if r.status in ("failed", "partial")), None)
        out.append({
            "job_id": str(job.id),
            "name": job.name,
            "backup_type": job.backup_type,
            "is_active": job.is_active,
            "schedule_cron": job.schedule_cron,
            "last_run": ({
                "status": last.status,
                "started_at": last.started_at.isoformat() if last.started_at else None,
                "finished_at": last.finished_at.isoformat() if last.finished_at else None,
                "triggered_by": last.triggered_by,
                "size_bytes": last.size_bytes,
            } if last else None),
            "last_success_at": (last_ok.started_at or last_ok.created_at).isoformat() if last_ok else None,
            "last_failure": ({
                "at": (last_failed.started_at or last_failed.created_at).isoformat(),
                "status": last_failed.status,
                "error": (last_failed.error_message or "")[:300] or None,
            } if last_failed else None),
        })

    await log_action(
        db,
        action="mcp.backup_status",
        resource_type="mcp_client",
        resource_id=str(client.id),
        detail=f"client={client.name} jobs={len(out)}",
        meta={"client_name": client.name},
        ip_address=_client_ip(request),
    )

    return {"tool": "list_backup_status", "jobs": out, "count": len(out)}
