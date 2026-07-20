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


CRITICAL_TRIGGERS = {
    "run.failed", "validation.failed", "server.offline", "storage.critical",
}


async def _triggers_going_dark(db, channel_id, surviving_triggers: set[str]) -> set[str]:
    """Which critical triggers would end up with no active listener.

    `surviving_triggers` is what this channel would still cover after the
    change, empty for a delete or a deactivation. Everything else active in
    the system counts as a peer.
    """
    peers = (await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.is_active == True,
            NotificationChannel.id != channel_id,
        )
    )).scalars().all()
    covered = {t for p in peers for t in (p.triggers or []) if t in CRITICAL_TRIGGERS}
    covered |= {t for t in surviving_triggers if t in CRITICAL_TRIGGERS}
    return CRITICAL_TRIGGERS - covered


@router.put("/{channel_id}", response_model=NotificationChannelOut)
async def update_channel(
    channel_id: uuid.UUID,
    body: NotificationChannelUpdate,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(NotificationChannel).where(NotificationChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # The delete endpoint has refused to remove the last listener for a
    # critical event since 2026-05-01. Update had no such check, so the same
    # outcome was reachable by setting is_active=false or triggers=[]. A guard
    # that only covers one of two doors is not a guard, and this one read as
    # though the case were handled.
    fields = body.model_dump(exclude_unset=True)
    if not force:
        will_be_active = fields.get("is_active", channel.is_active)
        will_have = set(fields.get("triggers", channel.triggers) or []) if will_be_active else set()
        going_dark = await _triggers_going_dark(db, channel_id, will_have)
        currently_covered = {t for t in (channel.triggers or []) if t in CRITICAL_TRIGGERS}
        losing = going_dark & currently_covered
        if losing:
            raise HTTPException(
                status_code=400,
                detail=(
                    "This change would leave no active channel listening for: "
                    + ", ".join(sorted(losing))
                    + ". Add another active channel for those triggers first, "
                      "or pass ?force=true."
                ),
            )

    for key, value in fields.items():
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
    CRITICAL = CRITICAL_TRIGGERS
    if (channel.is_active and not force
            and channel.triggers and any(t in CRITICAL for t in channel.triggers)):
        # Per trigger, not "any peer covers any critical trigger". The old
        # form passed as long as the survivors covered SOMETHING critical, so
        # deleting the only channel listening for run.failed was allowed
        # whenever some other channel happened to listen for storage.critical.
        # The guard reported itself satisfied while the most important alarm in
        # the system went dark.
        going_dark = await _triggers_going_dark(db, channel_id, set())
        losing = going_dark & {t for t in channel.triggers if t in CRITICAL}
        if losing:
            raise HTTPException(
                status_code=400,
                detail=(
                    "This is the last active channel listening for: "
                    + ", ".join(sorted(losing))
                    + ". Add another active channel for those triggers first, "
                      "or pass ?force=true."
                ),
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
