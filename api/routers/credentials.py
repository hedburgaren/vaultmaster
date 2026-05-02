"""Credential vault REST endpoints.

Plaintext is NEVER returned by list/get/update — only by the explicit
/reveal endpoint, which requires re-auth (current password) and writes
an audit_log row per call.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user, verify_password
from api.database import get_db
from api.models.credential import Credential
from api.models.user import User
from api.routers.audit import log_action
from api.schemas import (
    CredentialCreate,
    CredentialOut,
    CredentialRevealOut,
    CredentialRevealRequest,
    CredentialUpdate,
)
from api.services.credentials_crypto import get_crypto

router = APIRouter(
    prefix="/credentials",
    tags=["credentials"],
    dependencies=[Depends(get_current_user)],
)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.get("", response_model=list[CredentialOut])
async def list_credentials(
    credential_type: str | None = None,
    tag: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Credential).where(Credential.owner_id == user.id)
    if credential_type:
        q = q.where(Credential.credential_type == credential_type)
    if tag:
        q = q.where(Credential.tags.any(tag))
    q = q.order_by(Credential.name)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
async def create_credential(
    body: CredentialCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    crypto = get_crypto()
    token, version = crypto.encrypt(body.plaintext_value)

    cred = Credential(
        owner_id=user.id,
        name=body.name,
        credential_type=body.credential_type,
        encrypted_value=token,
        key_version=version,
        description=body.description,
        tags=body.tags,
        expires_at=body.expires_at,
        rotation_policy=body.rotation_policy,
        provenance=body.provenance,
        mcp_enabled=body.mcp_enabled,
        mcp_scopes=body.mcp_scopes,
    )
    db.add(cred)
    await db.flush()
    await db.refresh(cred)
    await log_action(
        db,
        "credential.create",
        user=user,
        resource_type="credential",
        resource_id=str(cred.id),
        detail=f"Created credential '{cred.name}' (type={cred.credential_type})",
        ip_address=_client_ip(request),
    )
    return cred


@router.get("/{credential_id}", response_model=CredentialOut)
async def get_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Credential).where(Credential.id == credential_id, Credential.owner_id == user.id)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    return cred


@router.patch("/{credential_id}", response_model=CredentialOut)
async def update_credential(
    credential_id: uuid.UUID,
    body: CredentialUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Credential).where(Credential.id == credential_id, Credential.owner_id == user.id)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    changes = body.model_dump(exclude_unset=True)
    if "plaintext_value" in changes:
        plain = changes.pop("plaintext_value")
        if plain is not None:
            crypto = get_crypto()
            token, version = crypto.encrypt(plain)
            cred.encrypted_value = token
            cred.key_version = version
    for field, value in changes.items():
        setattr(cred, field, value)

    await db.flush()
    await db.refresh(cred)
    await log_action(
        db,
        "credential.update",
        user=user,
        resource_type="credential",
        resource_id=str(cred.id),
        detail=f"Updated credential '{cred.name}' fields={list(changes.keys())}",
        ip_address=_client_ip(request),
    )
    return cred


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Credential).where(Credential.id == credential_id, Credential.owner_id == user.id)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    name = cred.name
    cred_id = str(cred.id)
    await db.delete(cred)
    await log_action(
        db,
        "credential.delete",
        user=user,
        resource_type="credential",
        resource_id=cred_id,
        detail=f"Deleted credential '{name}'",
        ip_address=_client_ip(request),
    )


@router.post("/{credential_id}/reveal", response_model=CredentialRevealOut)
async def reveal_credential(
    credential_id: uuid.UUID,
    body: CredentialRevealRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return plaintext value AFTER re-authentication.

    Audit-logged on every call (success or fail). Returned plaintext is
    in-memory only — clients should clear it after use.
    """
    if not verify_password(body.password, user.hashed_password):
        await log_action(
            db,
            "credential.reveal.denied",
            user=user,
            resource_type="credential",
            resource_id=str(credential_id),
            detail=f"Re-auth failed: {body.purpose}",
            ip_address=_client_ip(request),
        )
        raise HTTPException(status_code=403, detail="Re-authentication failed")

    result = await db.execute(
        select(Credential).where(Credential.id == credential_id, Credential.owner_id == user.id)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    crypto = get_crypto()
    plaintext = crypto.decrypt(cred.encrypted_value)

    cred.last_revealed_at = datetime.now(timezone.utc)
    cred.last_revealed_by = user.id
    cred.reveal_count = (cred.reveal_count or 0) + 1
    await db.flush()
    await log_action(
        db,
        "credential.reveal",
        user=user,
        resource_type="credential",
        resource_id=str(cred.id),
        detail=body.purpose,
        ip_address=_client_ip(request),
    )

    return CredentialRevealOut(
        id=cred.id,
        name=cred.name,
        credential_type=cred.credential_type,
        plaintext_value=plaintext,
    )


@router.post("/{credential_id}/rotate-key", response_model=CredentialOut)
async def rotate_key_version(
    credential_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-encrypt this credential under the current latest key version.

    Used by an admin sweep after a key rotation in CREDENTIALS_MASTER_KEYS.
    Plaintext is unchanged; only the ciphertext is re-encrypted.
    """
    result = await db.execute(
        select(Credential).where(Credential.id == credential_id, Credential.owner_id == user.id)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    crypto = get_crypto()
    new_token, new_version = crypto.rotate(cred.encrypted_value)
    if new_version == cred.key_version:
        return cred
    cred.encrypted_value = new_token
    cred.key_version = new_version
    await db.flush()
    await db.refresh(cred)
    await log_action(
        db,
        "credential.rotate_key",
        user=user,
        resource_type="credential",
        resource_id=str(cred.id),
        detail=f"Re-encrypted to v{new_version}",
        ip_address=_client_ip(request),
    )
    return cred
