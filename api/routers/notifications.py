import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.database import get_db
from api.models.notification_channel import NotificationChannel
from api.schemas import NotificationChannelCreate, NotificationChannelUpdate, NotificationChannelOut
from api.services.credentials_crypto import encrypt_dict_secrets

router = APIRouter(prefix="/notifications/channels", tags=["notifications"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[NotificationChannelOut])
async def list_channels(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationChannel).order_by(NotificationChannel.name))
    return result.scalars().all()


@router.post("", response_model=NotificationChannelOut, status_code=status.HTTP_201_CREATED)
async def create_channel(body: NotificationChannelCreate, db: AsyncSession = Depends(get_db)):
    payload = body.model_dump()
    # Bug #22 — encrypt sensitive fields (bot_token, bridge_token, webhook_url,
    # chat_id, smtp_password, etc.) before persisting. `encrypt_dict_secrets`
    # is idempotent: values already prefixed with `enc:vN:` pass through.
    payload["config"] = encrypt_dict_secrets(payload.get("config") or {}) or {}
    channel = NotificationChannel(**payload)
    db.add(channel)
    await db.flush()
    await db.refresh(channel)
    return channel


@router.get("/{channel_id}", response_model=NotificationChannelOut)
async def get_channel(channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationChannel).where(NotificationChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@router.put("/{channel_id}", response_model=NotificationChannelOut)
async def update_channel(channel_id: uuid.UUID, body: NotificationChannelUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationChannel).where(NotificationChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "config" and value is not None:
            # Re-encrypt any plaintext secrets the caller submitted; passthrough
            # for already-`enc:vN:` values is idempotent.
            new_cfg = dict(value)
            # The GET response masks secrets as "********" — if the UI submits
            # the masked sentinel back unchanged, fall back to the existing
            # encrypted value rather than overwriting the real secret.
            existing = dict(channel.config or {})
            for k, v in list(new_cfg.items()):
                if isinstance(v, str) and v == "********" and k in existing:
                    new_cfg[k] = existing[k]
            value = encrypt_dict_secrets(new_cfg) or {}
        setattr(channel, key, value)
    await db.flush()
    await db.refresh(channel)
    return channel


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_id: uuid.UUID, force: bool = False, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationChannel).where(NotificationChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # SPOF guard: refuse to delete the last active channel listening for
    # critical events. Without it, future failures would land silently
    # — exactly what bit us on 2026-05-01.
    CRITICAL = {"run.failed", "validation.failed", "server.offline", "storage.critical"}
    if (channel.is_active and not force
            and channel.triggers and any(t in CRITICAL for t in channel.triggers)):
        from sqlalchemy import func
        result = await db.execute(
            select(NotificationChannel).where(
                NotificationChannel.is_active == True,
                NotificationChannel.id != channel_id,
            )
        )
        peers = result.scalars().all()
        peer_covers_crit = any(
            any(t in CRITICAL for t in (p.triggers or [])) for p in peers
        )
        if not peer_covers_crit:
            raise HTTPException(
                status_code=400,
                detail="This is the last active channel listening for critical events "
                       "(run.failed/validation.failed/server.offline/storage.critical). "
                       "Add another active channel for those triggers first, or pass ?force=true.",
            )
    await db.delete(channel)


@router.post("/{channel_id}/test")
async def test_channel(channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationChannel).where(NotificationChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    from api.services.notifier import send_test_notification
    success, message = await send_test_notification(channel)
    return {"success": success, "message": message}
