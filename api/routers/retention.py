import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.database import get_db
from api.models.retention_policy import RetentionPolicy
from api.schemas import RetentionPolicyCreate, RetentionPolicyUpdate, RetentionPolicyOut

router = APIRouter(prefix="/retention", tags=["retention"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[RetentionPolicyOut])
async def list_policies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RetentionPolicy).order_by(RetentionPolicy.name))
    return result.scalars().all()


@router.post("", response_model=RetentionPolicyOut, status_code=status.HTTP_201_CREATED)
async def create_policy(body: RetentionPolicyCreate, db: AsyncSession = Depends(get_db)):
    policy = RetentionPolicy(**body.model_dump())
    db.add(policy)
    await db.flush()
    await db.refresh(policy)
    return policy


@router.get("/{policy_id}", response_model=RetentionPolicyOut)
async def get_policy(policy_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RetentionPolicy).where(RetentionPolicy.id == policy_id))
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Retention policy not found")
    return policy


@router.put("/{policy_id}", response_model=RetentionPolicyOut)
async def update_policy(policy_id: uuid.UUID, body: RetentionPolicyUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RetentionPolicy).where(RetentionPolicy.id == policy_id))
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Retention policy not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(policy, key, value)
    await db.flush()
    await db.refresh(policy)
    return policy


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(policy_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RetentionPolicy).where(RetentionPolicy.id == policy_id))
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Retention policy not found")
    await db.delete(policy)


@router.post("/{policy_id}/preview")
async def preview_rotation(policy_id: uuid.UUID, job_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)):
    """Preview which artifacts would be deleted by this retention policy."""
    result = await db.execute(select(RetentionPolicy).where(RetentionPolicy.id == policy_id))
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Retention policy not found")
    from api.services.rotation import preview_rotation
    preview = await preview_rotation(db, policy, job_id)
    return preview
