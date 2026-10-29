"""Credential vault REST endpoints: items with unlimited fields.

An item is one overlying title (e.g. "Aftonbladet") plus any number of
(field_title, value) fields. Every value is encrypted on its own, so a
reveal, a rotation or (later) a grant can name one field without touching
its siblings.

Plaintext is NEVER returned by list/get/update, only by the explicit
reveal endpoints, which require re-auth (current password, TOTP when
enabled) and write an audit_log row per call.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user, verify_password
from api.database import get_db
from api.models.credential import CredentialField, CredentialItem
from api.models.user import User
from api.routers.audit import log_action
from api.schemas import (
    CredentialFieldAdd,
    CredentialFieldOut,
    CredentialFieldRevealOut,
    CredentialFieldUpdate,
    CredentialItemCreate,
    CredentialItemOut,
    CredentialItemRevealOut,
    CredentialItemUpdate,
    CredentialRevealRequest,
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


def _item_out(item: CredentialItem) -> CredentialItemOut:
    """Build the response model, adding the computed field_count."""
    out = CredentialItemOut.model_validate(item)
    out.field_count = len(item.fields)
    return out


async def _get_owned_item(
    db: AsyncSession, user: User, item_id: uuid.UUID
) -> CredentialItem:
    result = await db.execute(
        select(CredentialItem)
        .options(selectinload(CredentialItem.fields))
        .where(CredentialItem.id == item_id, CredentialItem.owner_id == user.id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Credential item not found")
    return item


async def _require_reauth(
    db: AsyncSession,
    user: User,
    body: CredentialRevealRequest,
    request: Request,
    resource_type: str,
    resource_id: str,
) -> None:
    """Password (+ TOTP when enabled) before any plaintext leaves the vault.

    Failure is audited with the stated purpose, same as success, so a
    probing caller leaves as much of a trail as a legitimate one.
    """
    denied_detail = ""
    if not verify_password(body.password, user.hashed_password):
        denied_detail = f"Re-auth failed: {body.purpose}"
    elif user.totp_enabled:
        if not body.totp_code:
            denied_detail = f"TOTP required: {body.purpose}"
        else:
            import pyotp

            totp = pyotp.TOTP(user.totp_secret or "")
            if not totp.verify(body.totp_code, valid_window=1):
                denied_detail = f"Invalid TOTP: {body.purpose}"

    if denied_detail:
        await log_action(
            db,
            "credential.reveal.denied",
            user=user,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=denied_detail,
            ip_address=_client_ip(request),
        )
        # Commit before raising. The dependency teardown rolls the session
        # back on any exception that leaves the endpoint (get_db's except
        # path), and without this the denial would answer 403 while its own
        # audit row silently vanished. A probing caller must leave a trail.
        await db.commit()
        raise HTTPException(status_code=403, detail=denied_detail)


def _next_sort_order(item: CredentialItem) -> int:
    if not item.fields:
        return 0
    return max(f.sort_order for f in item.fields) + 1


# ── Items ──


@router.get("", response_model=list[CredentialItemOut])
async def list_credential_items(
    tag: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = (
        select(CredentialItem)
        .options(selectinload(CredentialItem.fields))
        .where(CredentialItem.owner_id == user.id)
        .order_by(CredentialItem.title)
    )
    if tag:
        query = query.where(CredentialItem.tags.any(tag))
    if q:
        query = query.where(CredentialItem.title.ilike(f"%{q}%"))
    result = await db.execute(query)
    items = result.scalars().all()
    return [_item_out(i) for i in items]


@router.post("", response_model=CredentialItemOut, status_code=status.HTTP_201_CREATED)
async def create_credential_item(
    body: CredentialItemCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    crypto = get_crypto()

    titles = [f.field_title for f in body.fields]
    if len(titles) != len(set(titles)):
        raise HTTPException(
            status_code=422,
            detail="Duplicate field titles in one item are refused: "
            "a field title is its handle for reveal and grants.",
        )

    item = CredentialItem(
        owner_id=user.id,
        title=body.title,
        description=body.description,
        tags=body.tags,
        expires_at=body.expires_at,
        rotation_policy=body.rotation_policy,
        provenance=body.provenance,
        mcp_enabled=body.mcp_enabled,
        mcp_scopes=body.mcp_scopes,
    )
    for order, field_in in enumerate(body.fields):
        token, version = crypto.encrypt(field_in.value)
        item.fields.append(CredentialField(
            field_title=field_in.field_title,
            encrypted_value=token,
            key_version=version,
            sort_order=order,
        ))

    db.add(item)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Could not create item")
    await db.refresh(item, attribute_names=["fields", "updated_at"])

    await log_action(
        db,
        "credential_item.create",
        user=user,
        resource_type="credential_item",
        resource_id=str(item.id),
        detail=f"Created item '{item.title}' with {len(item.fields)} field(s)",
        ip_address=_client_ip(request),
    )
    return _item_out(item)


@router.get("/items/{item_id}", response_model=CredentialItemOut)
async def get_credential_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _item_out(await _get_owned_item(db, user, item_id))


@router.patch("/items/{item_id}", response_model=CredentialItemOut)
async def update_credential_item(
    item_id: uuid.UUID,
    body: CredentialItemUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = await _get_owned_item(db, user, item_id)

    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(item, field, value)
    await db.flush()
    await db.refresh(item, attribute_names=["fields", "updated_at"])

    await log_action(
        db,
        "credential_item.update",
        user=user,
        resource_type="credential_item",
        resource_id=str(item.id),
        detail=f"Updated item '{item.title}' fields={sorted(changes.keys())}",
        ip_address=_client_ip(request),
    )
    return _item_out(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential_item(
    item_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = await _get_owned_item(db, user, item_id)
    title, item_id_str = item.title, str(item.id)
    # await is load-bearing; see the field-delete twin below.
    await db.delete(item)
    await db.flush()
    await log_action(
        db,
        "credential_item.delete",
        user=user,
        resource_type="credential_item",
        resource_id=item_id_str,
        detail=f"Deleted item '{title}' with its {len(item.fields)} field(s)",
        ip_address=_client_ip(request),
    )


@router.post("/items/{item_id}/rotate-key", response_model=CredentialItemOut)
async def rotate_item_keys(
    item_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-encrypt every field of the item under the latest key version.

    Plaintext is unchanged; only ciphertext moves. Per item rather than
    per field on purpose: key rotation is an all-or-nothing migration, and
    a half-rotated item would report two different key_versions with no
    way to tell which fields were missed.
    """
    item = await _get_owned_item(db, user, item_id)
    crypto = get_crypto()
    rotated = 0
    versions = set()
    for field in item.fields:
        new_token, new_version = crypto.rotate(field.encrypted_value)
        if new_version != field.key_version:
            field.encrypted_value = new_token
            field.key_version = new_version
            rotated += 1
        versions.add(field.key_version)
    await db.flush()
    await db.refresh(item, attribute_names=["fields", "updated_at"])

    await log_action(
        db,
        "credential_item.rotate_key",
        user=user,
        resource_type="credential_item",
        resource_id=str(item.id),
        detail=f"Re-encrypted {rotated}/{len(item.fields)} field(s); versions now {sorted(versions)}",
        ip_address=_client_ip(request),
    )
    return _item_out(item)


# ── Fields ──


async def _get_owned_field(
    db: AsyncSession, user: User, field_id: uuid.UUID
) -> tuple[CredentialItem, CredentialField]:
    result = await db.execute(
        select(CredentialField)
        .options(selectinload(CredentialField.item).selectinload(CredentialItem.fields))
        .where(CredentialField.id == field_id)
    )
    field = result.scalar_one_or_none()
    if not field or field.item.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Credential field not found")
    return field.item, field


@router.post(
    "/items/{item_id}/fields",
    response_model=CredentialFieldOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_credential_field(
    item_id: uuid.UUID,
    body: CredentialFieldAdd,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = await _get_owned_item(db, user, item_id)
    crypto = get_crypto()
    token, version = crypto.encrypt(body.value)

    field = CredentialField(
        item_id=item.id,
        field_title=body.field_title,
        encrypted_value=token,
        key_version=version,
        sort_order=_next_sort_order(item),
    )
    db.add(field)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"A field titled '{body.field_title}' already exists on this item. "
            "Field titles must be unique within an item.",
        )
    await log_action(
        db,
        "credential_field.create",
        user=user,
        resource_type="credential_field",
        resource_id=str(field.id),
        detail=f"Added field '{field.field_title}' to item '{item.title}'",
        ip_address=_client_ip(request),
    )
    return field


@router.patch("/fields/{field_id}", response_model=CredentialFieldOut)
async def update_credential_field(
    field_id: uuid.UUID,
    body: CredentialFieldUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item, field = await _get_owned_field(db, user, field_id)

    changes = body.model_dump(exclude_unset=True)
    if "value" in changes:
        plain = changes.pop("value")
        if plain is not None:
            crypto = get_crypto()
            token, version = crypto.encrypt(plain)
            field.encrypted_value = token
            field.key_version = version
    for attr, value in changes.items():
        setattr(field, attr, value)

    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"A field titled '{body.field_title}' already exists on this item.",
        )
    await db.refresh(field)

    await log_action(
        db,
        "credential_field.update",
        user=user,
        resource_type="credential_field",
        resource_id=str(field.id),
        detail=(
            f"Updated field '{field.field_title}' on item '{item.title}'"
            f"{', value re-encrypted' if 'value' in body.model_dump(exclude_unset=True) else ''}"
        ),
        ip_address=_client_ip(request),
    )
    return field


@router.delete("/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential_field(
    field_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item, field = await _get_owned_field(db, user, field_id)
    if len(item.fields) == 1:
        raise HTTPException(
            status_code=422,
            detail="This is the item's last field. Delete the item itself instead; "
            "an item with no fields is a title that lies about holding a secret.",
        )
    field_title, field_id_str = field.field_title, str(field.id)
    # await is load-bearing: AsyncSession.delete is a coroutine. Called bare,
    # nothing is deleted, the endpoint still answers 204, and the row sits
    # there forever (found live against a real database 2026-10-29).
    await db.delete(field)
    await db.flush()
    await log_action(
        db,
        "credential_field.delete",
        user=user,
        resource_type="credential_field",
        resource_id=field_id_str,
        detail=f"Deleted field '{field_title}' from item '{item.title}'",
        ip_address=_client_ip(request),
    )


# ── Reveal ──


def _touch_reveal_counters(item: CredentialItem, field: CredentialField, user: User) -> None:
    now = datetime.now(timezone.utc)
    field.reveal_count = (field.reveal_count or 0) + 1
    field.last_revealed_at = now
    item.reveal_count = (item.reveal_count or 0) + 1
    item.last_revealed_at = now
    item.last_revealed_by = user.id


@router.post("/items/{item_id}/reveal", response_model=CredentialItemRevealOut)
async def reveal_credential_item(
    item_id: uuid.UUID,
    body: CredentialRevealRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return every field's plaintext AFTER re-authentication.

    Audit-logged per call. Returned plaintext is in-memory only; clients
    clear it after use.
    """
    await _require_reauth(db, user, body, request, "credential_item", str(item_id))
    item = await _get_owned_item(db, user, item_id)

    crypto = get_crypto()
    values = []
    for field in sorted(item.fields, key=lambda f: f.sort_order):
        values.append(CredentialFieldRevealOut(
            field_id=field.id,
            field_title=field.field_title,
            value=crypto.decrypt(field.encrypted_value),
        ))
        _touch_reveal_counters(item, field, user)

    await db.flush()
    await log_action(
        db,
        "credential_item.reveal",
        user=user,
        resource_type="credential_item",
        resource_id=str(item.id),
        detail=f"Revealed all {len(values)} field(s): {body.purpose}",
        ip_address=_client_ip(request),
    )

    return CredentialItemRevealOut(id=item.id, title=item.title, values=values)


@router.post("/fields/{field_id}/reveal", response_model=CredentialFieldRevealOut)
async def reveal_credential_field(
    field_id: uuid.UUID,
    body: CredentialRevealRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return ONE field's plaintext after re-authentication.

    The point of per-field reveal: showing the inloggningsnamn must not
    also show the lösenord.
    """
    await _require_reauth(db, user, body, request, "credential_field", str(field_id))
    item, field = await _get_owned_field(db, user, field_id)

    crypto = get_crypto()
    plaintext = crypto.decrypt(field.encrypted_value)
    _touch_reveal_counters(item, field, user)

    await db.flush()
    await log_action(
        db,
        "credential_field.reveal",
        user=user,
        resource_type="credential_field",
        resource_id=str(field.id),
        detail=f"Revealed field '{field.field_title}' on '{item.title}': {body.purpose}",
        ip_address=_client_ip(request),
    )

    return CredentialFieldRevealOut(
        field_id=field.id,
        field_title=field.field_title,
        value=plaintext,
    )
