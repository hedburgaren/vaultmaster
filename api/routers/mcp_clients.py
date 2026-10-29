"""Admin endpoints for managing MCP clients (AI agents).

The plaintext key is generated server-side and returned ONCE on
create — never persisted. Subsequent GET/PATCH/DELETE work by id only.
"""

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.database import get_db
from api.mcp.auth import hash_mcp_key
from api.models.mcp_client import MCPClient
from api.models.user import User
from api.routers.audit import log_action
from api.schemas import (
    MCPClientCreate,
    MCPClientCreated,
    MCPClientOut,
    MCPClientUpdate,
    MCPGrantSetIn,
    MCPGrantsOut,
)

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

    # raw_key exists only here, never on the row, so the response model is
    # built from the row's fields plus the key. model_validate(client) alone
    # raises (raw_key required, absent on the ORM object), which made client
    # creation/rotation answer 500 while the row was already flushed: a key
    # nobody could ever use. Found live 2026-10-29.
    base = MCPClientOut.model_validate(client, from_attributes=True)
    out_dict = base.model_dump()
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

    # raw_key exists only here, never on the row, so the response model is
    # built from the row's fields plus the key. model_validate(client) alone
    # raises (raw_key required, absent on the ORM object), which made client
    # creation/rotation answer 500 while the row was already flushed: a key
    # nobody could ever use. Found live 2026-10-29.
    base = MCPClientOut.model_validate(client, from_attributes=True)
    out_dict = base.model_dump()
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


# ── Granular grants ──

ALLOWED_API_SCOPES = {"backup.read", "credentials.read"}


def _grants_out(client) -> MCPGrantsOut:
    out = MCPGrantsOut(client_id=client.id)
    for g in client.grants or []:
        if g.resource_type == "credential_item":
            out.credential_items.append(g.resource_id)
        elif g.resource_type == "credential_field":
            out.credential_fields.append(g.resource_id)
        elif g.resource_type == "api":
            out.api_scopes.append(g.resource_id)
    return out


@router.get("/{client_id}/grants", response_model=MCPGrantsOut)
async def get_mcp_client_grants(
    client_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MCPClient)
        .options(selectinload(MCPClient.grants))
        .where(MCPClient.id == client_id, MCPClient.owner_id == user.id)
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="MCP client not found")
    return _grants_out(client)


@router.put("/{client_id}/grants", response_model=MCPGrantsOut)
async def replace_mcp_client_grants(
    client_id: uuid.UUID,
    body: MCPGrantSetIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Replace the client's entire grant set in one call.

    Replace rather than add/remove per grant: the caller states the complete
    intended state, the difference is audited as one row, and there is no
    reconciliation guessing about what the previous state was. Grants are
    updatable by design; the key itself never changes.

    Unknown item/field ids are refused with 422 naming them: a grant on a
    resource that does not exist is almost certainly a stale id pasted from
    somewhere, and silently accepting it would make "this agent can read 2
    of 30 keys" a claim about 1 real key and one ghost.
    """
    from api.models.credential import CredentialField, CredentialItem
    from api.models.mcp_grant import MCPGrant

    result = await db.execute(
        select(MCPClient)
        .options(selectinload(MCPClient.grants))
        .where(MCPClient.id == client_id, MCPClient.owner_id == user.id)
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="MCP client not found")

    bad_scopes = sorted(set(body.api_scopes) - ALLOWED_API_SCOPES)
    if bad_scopes:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown api scopes {bad_scopes}; allowed: {sorted(ALLOWED_API_SCOPES)}",
        )

    item_ids = {str(i) for i in body.credential_item_ids}
    field_ids = {str(i) for i in body.credential_field_ids}

    problems = []
    if item_ids:
        rows = (await db.execute(
            select(CredentialItem.id).where(CredentialItem.id.in_(body.credential_item_ids))
        )).scalars().all()
        known = {str(r) for r in rows}
        problems += [f"unknown item {i}" for i in sorted(item_ids - known)]
    if field_ids:
        rows = (await db.execute(
            select(CredentialField.id).where(CredentialField.id.in_(body.credential_field_ids))
        )).scalars().all()
        known = {str(r) for r in rows}
        problems += [f"unknown field {i}" for i in sorted(field_ids - known)]
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))

    old = _grants_out(client)
    for g in list(client.grants or []):
        await db.delete(g)
    for rid in sorted(item_ids):
        client.grants.append(MCPGrant(resource_type="credential_item", resource_id=rid))
    for rid in sorted(field_ids):
        client.grants.append(MCPGrant(resource_type="credential_field", resource_id=rid))
    for scope in sorted(set(body.api_scopes)):
        client.grants.append(MCPGrant(resource_type="api", resource_id=scope))

    await db.flush()
    await db.refresh(client, attribute_names=["grants"])
    new = _grants_out(client)

    await log_action(
        db,
        action="mcp_client.grants",
        user=user,
        resource_type="mcp_client",
        resource_id=str(client.id),
        detail=(
            f"Grants for '{client.name}' replaced: "
            f"items {len(new.credential_items)} (was {len(old.credential_items)}), "
            f"fields {len(new.credential_fields)} (was {len(old.credential_fields)}), "
            f"api {new.api_scopes} (was {old.api_scopes})"
        ),
        ip_address=_client_ip(request),
    )
    return new
