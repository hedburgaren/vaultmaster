import uuid
import hmac
import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from api.auth import get_current_user
from api.database import get_db
from api.models.webhook import Webhook
from api.models.user import User

router = APIRouter(prefix="/webhooks", tags=["webhooks"], dependencies=[Depends(get_current_user)])


# ── Schemas ──
from pydantic import BaseModel


class WebhookCreate(BaseModel):
    name: str
    url: str
    secret: str | None = None
    events: list[str] = []
    headers: dict = {}


class WebhookUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    secret: str | None = None
    events: list[str] | None = None
    is_active: bool | None = None
    headers: dict | None = None


class WebhookOut(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    events: list[str] | None
    is_active: bool
    last_triggered: datetime | None
    last_status_code: int | None
    failure_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── CRUD ──
@router.get("", response_model=list[WebhookOut])
async def list_webhooks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Webhook).order_by(Webhook.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=WebhookOut, status_code=status.HTTP_201_CREATED)
async def create_webhook(body: WebhookCreate, db: AsyncSession = Depends(get_db)):
    wh = Webhook(**body.model_dump())
    db.add(wh)
    await db.flush()
    await db.refresh(wh)
    return wh


@router.put("/{webhook_id}", response_model=WebhookOut)
async def update_webhook(webhook_id: uuid.UUID, body: WebhookUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
    wh = result.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(wh, key, value)
    await db.flush()
    await db.refresh(wh)
    return wh


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(webhook_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
    wh = result.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await db.delete(wh)


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
    wh = result.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    payload = {
        "event": "test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {"message": "VaultMaster webhook test"},
    }
    try:
        status_code = await _send_webhook(wh, payload)
        wh.last_triggered = datetime.now(timezone.utc)
        wh.last_status_code = status_code
        if status_code >= 400:
            wh.failure_count += 1
        await db.flush()
        return {"success": status_code < 400, "status_code": status_code}
    except Exception as e:
        wh.failure_count += 1
        await db.flush()
        return {"success": False, "message": str(e)}


# ── Event dispatcher ──
VALID_EVENTS = [
    "backup.started", "backup.completed", "backup.failed",
    "restore.started", "restore.completed", "restore.failed",
    "server.created", "server.deleted", "server.offline",
    "job.created", "job.deleted", "job.triggered",
    "storage.warning", "storage.critical",
    "user.login", "user.created",
]


async def dispatch_webhook_event(db: AsyncSession, event: str, data: dict):
    """Send event to all active webhooks subscribed to this event type."""
    result = await db.execute(select(Webhook).where(Webhook.is_active == True))
    webhooks = result.scalars().all()

    payload = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }

    for wh in webhooks:
        if not wh.events or event in wh.events or "*" in wh.events:
            try:
                code = await _send_webhook(wh, payload)
                wh.last_triggered = datetime.now(timezone.utc)
                wh.last_status_code = code
                if code >= 400:
                    wh.failure_count += 1
            except Exception:
                wh.failure_count += 1


async def _send_webhook(wh: Webhook, payload: dict) -> int:
    """Send a single webhook request."""
    body = json.dumps(payload)
    headers = dict(wh.headers or {})
    headers["Content-Type"] = "application/json"
    headers["User-Agent"] = "VaultMaster/2.0"

    if wh.secret:
        signature = hmac.new(wh.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        headers["X-VaultMaster-Signature"] = f"sha256={signature}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(wh.url, content=body, headers=headers)
        return resp.status_code
