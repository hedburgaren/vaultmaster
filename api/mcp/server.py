"""MCP-style REST endpoints for AI agents.

Exposes a small Tools API under /api/mcp/v1/. Each "tool" is a
standalone POST endpoint:

  GET  /api/mcp/v1/tools                    — list catalog (introspection)
  POST /api/mcp/v1/tools/search_credentials — search by query/tags within scope
  POST /api/mcp/v1/tools/get_credential     — fetch plaintext for a single id

Auth: X-MCP-Key header → MCPClient row. Decision (per Kimi's recommendation
in the codereview): get_credential returns plaintext directly. Defense
is layered: client must be active, scope must intersect with the
credential's mcp_scopes ∪ tags, the credential must have mcp_enabled=true,
and every call is audit-logged with client_id + purpose. Per-client
rate limiting is enforced via the existing SlowAPI Limiter using the
client UUID as the rate-key.

Future extension: a FastMCP SSE binding can be added on top of these
primitives without changing the underlying logic.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.mcp.auth import get_mcp_client
from api.models.credential import Credential
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


def _credential_visible(c: Credential, client: MCPClient) -> bool:
    """Visibility check used by every MCP tool."""
    if not c.mcp_enabled:
        return False
    client_scopes = set(client.scopes or [])
    if not client_scopes:
        return False  # explicit empty scope = no access
    cred_scopes = set(c.mcp_scopes or []) | set(c.tags or [])
    return bool(client_scopes & cred_scopes)


# ── Tool catalog (introspection) ──
TOOL_CATALOG = [
    {
        "name": "search_credentials",
        "description": (
            "Search credentials visible to the calling MCP client. Returns metadata only "
            "(id, name, type, tags, expires_at). Plaintext is never returned by this tool — "
            "use get_credential to fetch a specific value."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring filter on name / description"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Restrict to credentials tagged with ANY of these tags"},
                "credential_type": {"type": "string", "description": "Optional type filter (api_key, password, ...)"},
                "limit": {"type": "integer", "default": 20, "maximum": 100},
            },
        },
    },
    {
        "name": "get_credential",
        "description": (
            "Fetch the plaintext value of a single credential by id. Requires a 'purpose' "
            "string which is recorded in the audit log. Visibility constraints same as "
            "search_credentials. Plaintext is returned in plain JSON; consume immediately."
        ),
        "input_schema": {
            "type": "object",
            "required": ["id", "purpose"],
            "properties": {
                "id": {"type": "string", "description": "UUID of the credential"},
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
    credential_type = args.get("credential_type")
    try:
        limit = int(args.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))

    q = select(Credential).where(Credential.mcp_enabled == True)
    if credential_type:
        q = q.where(Credential.credential_type == str(credential_type))
    result = await db.execute(q)
    rows = result.scalars().all()

    matches = []
    for c in rows:
        if not _credential_visible(c, client):
            continue
        if tags:
            if not (set(c.tags or []) & set(tags)):
                continue
        if query:
            hay = (c.name or "").lower() + " " + (c.description or "").lower()
            if query not in hay:
                continue
        matches.append({
            "id": str(c.id),
            "name": c.name,
            "type": c.credential_type,
            "tags": c.tags or [],
            "expires_at": c.expires_at.isoformat() if c.expires_at else None,
            "description": c.description,
        })
        if len(matches) >= limit:
            break

    await log_action(
        db,
        action="mcp.credential.search",
        resource_type="mcp_client",
        resource_id=str(client.id),
        detail=f"q={query!r} tags={tags} type={credential_type} hits={len(matches)}",
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
    purpose = (args.get("purpose") or "").strip()
    if not raw_id or not purpose:
        raise HTTPException(status_code=400, detail="'id' and 'purpose' are required")
    try:
        cid = uuid.UUID(str(raw_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="'id' is not a valid UUID")

    result = await db.execute(select(Credential).where(Credential.id == cid))
    cred = result.scalar_one_or_none()
    if not cred or not _credential_visible(cred, client):
        # Treat "not found" and "not visible" the same so we don't leak existence.
        await log_action(
            db,
            action="mcp.credential.get.denied",
            resource_type="credential",
            resource_id=str(cid),
            detail=f"client={client.name} scopes={client.scopes or []} purpose={purpose!r}",
            ip_address=_client_ip(request),
        )
        raise HTTPException(status_code=404, detail="Credential not found or not visible to this client")

    crypto = get_crypto()
    plaintext = crypto.decrypt(cred.encrypted_value)

    cred.reveal_count = (cred.reveal_count or 0) + 1
    await db.flush()

    await log_action(
        db,
        action="mcp.credential.get",
        resource_type="credential",
        resource_id=str(cred.id),
        detail=f"client={client.name} purpose={purpose!r}",
        meta={"client_id": str(client.id), "client_name": client.name},
        ip_address=_client_ip(request),
    )

    return {
        "tool": "get_credential",
        "id": str(cred.id),
        "name": cred.name,
        "type": cred.credential_type,
        "value": plaintext,
        "expires_at": cred.expires_at.isoformat() if cred.expires_at else None,
    }
