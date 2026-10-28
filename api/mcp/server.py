"""MCP-style REST endpoints for AI agents.

Exposes a small Tools API under /api/mcp/v1/. Each "tool" is a
standalone POST endpoint:

  GET  /api/mcp/v1/tools: tool catalog (introspection)
  POST /api/mcp/v1/tools/search_credentials: search items by query/tags within scope
  POST /api/mcp/v1/tools/get_credential: fetch field plaintext by item id

Auth: X-MCP-Key header → MCPClient row. Defense is layered: client must
be active, scope must intersect with the item's mcp_scopes ∪ tags, the
item must have mcp_enabled=true, and every call is audit-logged with
client_id + purpose. Per-client rate limiting is enforced via the
existing SlowAPI Limiter using the client UUID as the rate-key.

Credentials are items with unlimited fields (2026-10-29 rebuild).
Visibility here is deliberately item-grained and coarse: an enabled item
exposes all its fields to an in-scope client. Per-field grants (an agent
reading 2 of 30 keys) are a separate upcoming layer; until it exists this
surface must not pretend to be finer than it is.

Future extension: a FastMCP SSE binding can be added on top of these
primitives without changing the underlying logic.
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
    """Visibility check used by every MCP tool. Item-grained, coarse."""
    if not item.mcp_enabled:
        return False
    client_scopes = set(client.scopes or [])
    if not client_scopes:
        return False  # explicit empty scope = no access
    item_scopes = set(item.mcp_scopes or []) | set(item.tags or [])
    return bool(client_scopes & item_scopes)


# ── Tool catalog (introspection) ──
TOOL_CATALOG = [
    {
        "name": "search_credentials",
        "description": (
            "Search credential items visible to the calling MCP client. Returns metadata only "
            "(id, title, tags, expires_at, field titles). Plaintext is never returned by this "
            "tool; use get_credential to fetch specific values."
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
            "omit it to get every field of the item. Visibility constraints same as "
            "search_credentials. Plaintext is returned in plain JSON; consume immediately."
        ),
        "input_schema": {
            "type": "object",
            "required": ["id", "purpose"],
            "properties": {
                "id": {"type": "string", "description": "UUID of the credential item"},
                "field_title": {"type": "string", "description": "Title of one field, e.g. 'inloggningsnamn'. Optional; omit for all fields."},
                "purpose": {"type": "string", "description": "Why the agent needs this value (audit-logged)"},
            },
        },
    },
]


@router.get("/tools")
async def list_tools(client: MCPClient = Depends(get_mcp_client)):
    """Tool catalog. Authenticated to keep schema names off public surface."""
    return {"tools": TOOL_CATALOG, "client": {"name": client.name, "scopes": client.scopes or []}}


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

    result = await db.execute(
        select(CredentialItem)
        .options(selectinload(CredentialItem.fields))
        .where(CredentialItem.mcp_enabled == True)  # noqa: E712
    )
    rows = result.scalars().all()

    matches = []
    for item in rows:
        if not _credential_visible(item, client):
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
            "fields": [f.field_title for f in sorted(item.fields, key=lambda f: f.sort_order)],
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
    if not item or not _credential_visible(item, client):
        # Treat "not found" and "not visible" the same so we don't leak existence.
        await log_action(
            db,
            action="mcp.credential.get.denied",
            resource_type="credential_item",
            resource_id=str(cid),
            detail=f"client={client.name} scopes={client.scopes or []} purpose={purpose!r}",
            ip_address=_client_ip(request),
        )
        raise HTTPException(status_code=404, detail="Credential not found or not visible to this client")

    fields = sorted(item.fields, key=lambda f: f.sort_order)
    if field_title:
        fields = [f for f in fields if f.field_title == field_title]
        if not fields:
            await log_action(
                db,
                action="mcp.credential.get.denied",
                resource_type="credential_item",
                resource_id=str(item.id),
                detail=f"client={client.name} no field titled {field_title!r} purpose={purpose!r}",
                ip_address=_client_ip(request),
            )
            raise HTTPException(status_code=404, detail=f"No field titled '{field_title}' on this item")

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
