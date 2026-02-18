import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.database import get_db
from api.models.notification_channel import NotificationChannel
from api.schemas import NotificationChannelCreate, NotificationChannelUpdate, NotificationChannelOut

router = APIRouter(prefix="/notifications/channels", tags=["notifications"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[NotificationChannelOut])
async def list_channels(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationChannel).order_by(NotificationChannel.name))
    return result.scalars().all()


@router.post("", response_model=NotificationChannelOut, status_code=status.HTTP_201_CREATED)
async def create_channel(body: NotificationChannelCreate, db: AsyncSession = Depends(get_db)):
    channel = NotificationChannel(**body.model_dump())
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
        setattr(channel, key, value)
    await db.flush()
    await db.refresh(channel)
    return channel


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationChannel).where(NotificationChannel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
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
