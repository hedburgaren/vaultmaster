import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.database import get_db
from api.models.storage_destination import StorageDestination
from api.schemas import StorageDestinationCreate, StorageDestinationUpdate, StorageDestinationOut

router = APIRouter(prefix="/storage", tags=["storage"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[StorageDestinationOut])
async def list_storage(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).order_by(StorageDestination.name))
    return result.scalars().all()


@router.post("", response_model=StorageDestinationOut, status_code=status.HTTP_201_CREATED)
async def create_storage(body: StorageDestinationCreate, db: AsyncSession = Depends(get_db)):
    dest = StorageDestination(**body.model_dump())
    db.add(dest)
    await db.flush()
    await db.refresh(dest)
    return dest


@router.get("/{storage_id}", response_model=StorageDestinationOut)
async def get_storage(storage_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).where(StorageDestination.id == storage_id))
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    return dest


@router.put("/{storage_id}", response_model=StorageDestinationOut)
async def update_storage(storage_id: uuid.UUID, body: StorageDestinationUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).where(StorageDestination.id == storage_id))
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(dest, key, value)
    await db.flush()
    await db.refresh(dest)
    return dest


@router.delete("/{storage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_storage(storage_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).where(StorageDestination.id == storage_id))
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    await db.delete(dest)


@router.post("/{storage_id}/test")
async def test_storage(storage_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).where(StorageDestination.id == storage_id))
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    from api.services.rclone_client import test_storage_connection
    success, message = await test_storage_connection(dest)
    return {"success": success, "message": message}


@router.get("/{storage_id}/usage")
async def storage_usage(storage_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).where(StorageDestination.id == storage_id))
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    from api.services.rclone_client import get_storage_usage
    usage = await get_storage_usage(dest)
    return usage


@router.get("/{storage_id}/browse")
async def browse_storage(storage_id: uuid.UUID, path: str = "/", db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).where(StorageDestination.id == storage_id))
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    from api.services.rclone_client import list_storage_directory
    entries = await list_storage_directory(dest, path)
    return {"path": path, "entries": entries}
