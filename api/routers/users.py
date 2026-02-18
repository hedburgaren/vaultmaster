import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from api.auth import get_current_user, hash_password
from api.database import get_db
from api.models.user import User

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "viewer"  # admin, operator, viewer
    email_addresses: list[str] = []


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    email_addresses: list[str] | None = None


class UserListOut(BaseModel):
    id: uuid.UUID
    username: str
    email_addresses: list[str] | None
    role: str
    is_active: bool
    is_admin: bool
    totp_enabled: bool
    api_key_prefix: str | None
    created_at: str | None
    updated_at: str | None

    model_config = {"from_attributes": True}


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


@router.get("", response_model=list[UserListOut])
async def list_users(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return [
        UserListOut(
            id=u.id,
            username=u.username,
            email_addresses=u.email_addresses,
            role=u.role or ("admin" if u.is_admin else "viewer"),
            is_active=u.is_active,
            is_admin=u.is_admin,
            totp_enabled=u.totp_enabled if hasattr(u, 'totp_enabled') else False,
            api_key_prefix=u.api_key_prefix,
            created_at=u.created_at.isoformat() if u.created_at else None,
            updated_at=u.updated_at.isoformat() if u.updated_at else None,
        )
        for u in users
    ]


@router.post("", response_model=UserListOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if body.role not in ("admin", "operator", "viewer"):
        raise HTTPException(status_code=400, detail="Role must be admin, operator, or viewer")

    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        role=body.role,
        is_admin=body.role == "admin",
        is_active=True,
        email_addresses=body.email_addresses,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return UserListOut(
        id=user.id,
        username=user.username,
        email_addresses=user.email_addresses,
        role=user.role,
        is_active=user.is_active,
        is_admin=user.is_admin,
        totp_enabled=False,
        api_key_prefix=None,
        created_at=user.created_at.isoformat() if user.created_at else None,
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
    )


@router.put("/{user_id}", response_model=UserListOut)
async def update_user(user_id: uuid.UUID, body: UserUpdate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.role is not None:
        if body.role not in ("admin", "operator", "viewer"):
            raise HTTPException(status_code=400, detail="Role must be admin, operator, or viewer")
        user.role = body.role
        user.is_admin = body.role == "admin"
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.email_addresses is not None:
        user.email_addresses = body.email_addresses

    await db.flush()
    await db.refresh(user)
    return UserListOut(
        id=user.id,
        username=user.username,
        email_addresses=user.email_addresses,
        role=user.role or ("admin" if user.is_admin else "viewer"),
        is_active=user.is_active,
        is_admin=user.is_admin,
        totp_enabled=user.totp_enabled if hasattr(user, 'totp_enabled') else False,
        api_key_prefix=user.api_key_prefix,
        created_at=user.created_at.isoformat() if user.created_at else None,
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    await db.delete(user)
