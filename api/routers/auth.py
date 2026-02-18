from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import verify_password, create_access_token, hash_password, get_current_user
from api.database import get_db
from api.models.user import User
from api.schemas import LoginRequest, Token, UserOut, SetupRequest, SetupStatus

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/setup-status", response_model=SetupStatus)
async def setup_status(db: AsyncSession = Depends(get_db)):
    """Check if initial setup is needed (no users in database)."""
    result = await db.execute(select(func.count()).select_from(User))
    count = result.scalar() or 0
    return SetupStatus(needs_setup=count == 0)


@router.post("/setup", response_model=Token)
async def setup(body: SetupRequest, db: AsyncSession = Depends(get_db)):
    """Create the first admin user. Only works when no users exist."""
    result = await db.execute(select(func.count()).select_from(User))
    count = result.scalar() or 0
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already completed. Use /login instead.",
        )

    if len(body.username) < 2:
        raise HTTPException(status_code=400, detail="Username must be at least 2 characters")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    admin = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        is_active=True,
        is_admin=True,
    )
    db.add(admin)
    await db.commit()

    token = create_access_token(data={"sub": admin.username})
    return Token(access_token=token)


@router.post("/login", response_model=Token)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(data={"sub": user.username})
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
