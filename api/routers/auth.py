from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, HTTPException, status, Request

from api.auth import (
    verify_password, create_access_token, hash_password,
    get_current_user, generate_api_key,
)
from api.database import get_db
from api.models.user import User
from api.rate_limiter import limiter
from api.schemas import (
    LoginRequest, Token, UserOut, SetupRequest, SetupStatus,
    ProfileUpdate, ChangePasswordRequest, ApiKeyOut,
    TotpSetupOut, TotpVerifyRequest, TotpDisableRequest,
)

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
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user.totp_enabled:
        if not body.totp_code:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="TOTP code required",
            )
        import pyotp
        totp = pyotp.TOTP(user.totp_secret or "")
        if not totp.verify(body.totp_code, valid_window=1):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid TOTP code",
            )

    token = create_access_token(data={"sub": user.username})
    return Token(access_token=token)


@router.post("/totp/setup", response_model=TotpSetupOut)
async def totp_setup(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a fresh TOTP secret + QR. Activation requires /totp/verify."""
    if user.totp_enabled:
        raise HTTPException(status_code=400, detail="TOTP already enabled — disable first")
    import pyotp
    secret = pyotp.random_base32()
    user.totp_secret = secret
    user.totp_enabled = False
    await db.commit()

    otpauth = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user.username,
        issuer_name="VaultMaster",
    )
    qr_b64 = _qr_png_base64(otpauth)
    return TotpSetupOut(secret=secret, otpauth_uri=otpauth, qr_png_base64=qr_b64)


@router.post("/totp/verify")
async def totp_verify(
    body: TotpVerifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm enrolment by submitting a code from the authenticator app."""
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="No TOTP secret on file — call /totp/setup first")
    import pyotp
    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(body.totp_code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    user.totp_enabled = True
    await db.commit()
    return {"enabled": True}


@router.post("/totp/disable")
async def totp_disable(
    body: TotpDisableRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disable TOTP. Requires both current password and a valid current TOTP."""
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=403, detail="Password verification failed")
    if not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="TOTP is not enabled")
    import pyotp
    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(body.totp_code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    user.totp_enabled = False
    user.totp_secret = None
    await db.commit()
    return {"enabled": False}


def _qr_png_base64(uri: str) -> str:
    """Render a TOTP otpauth URI as a base64-encoded PNG suitable for
    embedding directly in an <img src=...>."""
    import base64
    import io
    import qrcode
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.put("/profile", response_model=UserOut)
async def update_profile(
    body: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's profile (email addresses)."""
    if body.email_addresses is not None:
        user.email_addresses = body.email_addresses
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the current user's password."""
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    user.hashed_password = hash_password(body.new_password)
    await db.commit()
    return {"message": "Password changed successfully"}


@router.post("/api-key", response_model=ApiKeyOut)
async def create_api_key(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new API key. The raw key is only shown once."""
    raw_key, key_hash, key_prefix = generate_api_key()
    user.api_key_hash = key_hash
    user.api_key_prefix = key_prefix
    await db.commit()
    return ApiKeyOut(api_key=raw_key, prefix=key_prefix)


@router.delete("/api-key")
async def revoke_api_key(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the current user's API key."""
    user.api_key_hash = None
    user.api_key_prefix = None
    await db.commit()
    return {"message": "API key revoked"}
