"""Admin endpoints for managing MCP clients (AI agents).

The plaintext key is generated server-side and returned ONCE on
create — never persisted. Subsequent GET/PATCH/DELETE work by id only.
"""

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.database import get_db
from api.mcp.auth import hash_mcp_key
from api.models.mcp_client import MCPClient
from api.models.user import User
from api.routers.audit import log_action
from api.schemas import MCPClientCreate, MCPClientCreated, MCPClientOut, MCPClientUpdate

router = APIRouter(
    prefix="/mcp-clients",
    tags=["mcp-clients"],
    dependencies=[Depends(get_current_user)],
)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.get("", response_model=list[MCPClientOut])
async def list_mcp_clients(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MCPClient).where(MCPClient.owner_id == user.id).order_by(MCPClient.name)
    )
    return result.scalars().all()


@router.post("", response_model=MCPClientCreated, status_code=status.HTTP_201_CREATED)
async def create_mcp_client(
    body: MCPClientCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Generate key
    raw = "mcp_" + secrets.token_urlsafe(40)
    client = MCPClient(
        owner_id=user.id,
        name=body.name,
        description=body.description,
        key_hash=hash_mcp_key(raw),
        key_prefix=raw[:11] + "…",
        scopes=body.scopes,
        rate_limit_per_minute=body.rate_limit_per_minute,
        expires_at=body.expires_at,
    )
    db.add(client)
    await db.flush()
    await db.refresh(client)
    await log_action(
        db,
        action="mcp_client.create",
        user=user,
        resource_type="mcp_client",
        resource_id=str(client.id),
        detail=f"Created MCP client '{client.name}' with scopes {client.scopes or []}",
        ip_address=_client_ip(request),
    )

    out = MCPClientCreated.model_validate(client, from_attributes=True)
    out_dict = out.model_dump()
    out_dict["raw_key"] = raw
    return out_dict


@router.patch("/{client_id}", response_model=MCPClientOut)
async def update_mcp_client(
    client_id: uuid.UUID,
    body: MCPClientUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MCPClient).where(MCPClient.id == client_id, MCPClient.owner_id == user.id)
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="MCP client not found")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(client, k, v)
    await db.flush()
    await db.refresh(client)
    await log_action(
        db,
        action="mcp_client.update",
        user=user,
        resource_type="mcp_client",
        resource_id=str(client.id),
        detail=f"Updated MCP client '{client.name}' fields={list(changes.keys())}",
        ip_address=_client_ip(request),
    )
    return client


@router.post("/{client_id}/rotate-key", response_model=MCPClientCreated)
async def rotate_mcp_key(
    client_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Rotate the secret key for this client. Returns a new raw_key once."""
    result = await db.execute(
        select(MCPClient).where(MCPClient.id == client_id, MCPClient.owner_id == user.id)
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="MCP client not found")

    raw = "mcp_" + secrets.token_urlsafe(40)
    client.key_hash = hash_mcp_key(raw)
    client.key_prefix = raw[:11] + "…"
    await db.flush()
    await db.refresh(client)

    await log_action(
        db,
        action="mcp_client.rotate_key",
        user=user,
        resource_type="mcp_client",
        resource_id=str(client.id),
        detail=f"Rotated MCP key for '{client.name}'",
        ip_address=_client_ip(request),
    )

    out = MCPClientCreated.model_validate(client, from_attributes=True)
    out_dict = out.model_dump()
    out_dict["raw_key"] = raw
    return out_dict


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_client(
    client_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MCPClient).where(MCPClient.id == client_id, MCPClient.owner_id == user.id)
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="MCP client not found")
    name = client.name
    cid = str(client.id)
    await db.delete(client)
    await log_action(
        db,
        action="mcp_client.delete",
        user=user,
        resource_type="mcp_client",
        resource_id=cid,
        detail=f"Deleted MCP client '{name}'",
        ip_address=_client_ip(request),
    )
