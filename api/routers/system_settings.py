from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.database import get_db
from api.models.system_settings import SystemSetting

router = APIRouter(prefix="/settings/system", tags=["system"], dependencies=[Depends(get_current_user)])

# Default values for all system settings
DEFAULTS = {
    "work_dir": "/tmp/vaultmaster",
}


@router.get("")
async def get_system_settings(db: AsyncSession = Depends(get_db)):
    """Get all system settings with defaults applied."""
    result = await db.execute(select(SystemSetting))
    stored = {s.key: s.value for s in result.scalars().all()}
    return {k: stored.get(k, v) for k, v in DEFAULTS.items()}


@router.put("")
async def update_system_settings(body: dict, db: AsyncSession = Depends(get_db)):
    """Update one or more system settings."""
    for key, value in body.items():
        if key not in DEFAULTS:
            continue
        result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = str(value)
        else:
            db.add(SystemSetting(key=key, value=str(value)))
    await db.flush()
    return await get_system_settings(db=db)
