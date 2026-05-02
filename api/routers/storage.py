import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.config import get_settings
from api.database import get_db
from api.models.storage_destination import StorageDestination
from api.schemas import StorageDestinationCreate, StorageDestinationUpdate, StorageDestinationOut

router = APIRouter(prefix="/storage", tags=["storage"])


_auth = Depends(get_current_user)


# ── OAuth endpoints (callback is unauthenticated — redirect from Google/Microsoft) ──

class OAuthStartRequest(BaseModel):
    provider: str  # "gdrive" or "onedrive"
    client_id: str
    client_secret: str


@router.post("/oauth/start", dependencies=[_auth])
async def oauth_start(body: OAuthStartRequest):
    """Start an OAuth flow. Returns auth_url, state, redirect_uri."""
    from api.services.oauth_storage import start_oauth
    settings = get_settings()
    try:
        result = start_oauth(body.provider, body.client_id, body.client_secret, settings.base_url)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(state: str = Query(...), code: str = Query(None), error: str = Query(None)):
    """OAuth callback — receives auth code from Google/Microsoft. No auth required."""
    from api.services.oauth_storage import handle_callback, _error_html
    if error:
        return HTMLResponse(_error_html(f"Authorization denied: {error}"))
    if not code:
        return HTMLResponse(_error_html("No authorization code received."))
    html = await handle_callback(state, code)
    return HTMLResponse(html)


@router.get("/oauth/token/{state}", dependencies=[_auth])
async def oauth_get_token(state: str):
    """Poll for OAuth token after user completes authorization."""
    from api.services.oauth_storage import get_token
    return get_token(state)


@router.get("/oauth/redirect-uri", dependencies=[_auth])
async def oauth_redirect_uri():
    """Return the redirect URI to configure in Google/Microsoft console."""
    from api.services.oauth_storage import get_redirect_uri
    settings = get_settings()
    return {"redirect_uri": get_redirect_uri(settings.base_url)}


# ── CRUD endpoints (all authenticated) ──

@router.get("", response_model=list[StorageDestinationOut], dependencies=[_auth])
async def list_storage(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).order_by(StorageDestination.name))
    return result.scalars().all()


@router.post("", response_model=StorageDestinationOut, status_code=status.HTTP_201_CREATED, dependencies=[_auth])
async def create_storage(body: StorageDestinationCreate, db: AsyncSession = Depends(get_db)):
    from api.services.credentials_crypto import encrypt_dict_secrets
    payload = body.model_dump()
    payload["config"] = encrypt_dict_secrets(dict(payload.get("config") or {}), extra_keys=_SECRET_CONFIG_KEYS)
    dest = StorageDestination(**payload)
    db.add(dest)
    await db.flush()
    await db.refresh(dest)
    return dest


@router.get("/{storage_id}", response_model=StorageDestinationOut, dependencies=[_auth])
async def get_storage(storage_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).where(StorageDestination.id == storage_id))
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    return dest


_SECRET_CONFIG_KEYS = {
    "secret_key", "password", "client_secret", "application_key", "app_key", "token",
}


@router.put("/{storage_id}", response_model=StorageDestinationOut, dependencies=[_auth])
async def update_storage(storage_id: uuid.UUID, body: StorageDestinationUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).where(StorageDestination.id == storage_id))
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    from api.services.credentials_crypto import encrypt_dict_secrets
    data = body.model_dump(exclude_unset=True)
    # Merge config: preserve existing secret values when new value is empty
    # (existing values are stored in encrypted form `enc:vN:...`).
    if "config" in data:
        old_cfg = dict(dest.config or {})
        new_cfg = data["config"] or {}
        for key in _SECRET_CONFIG_KEYS:
            if key in old_cfg and (not new_cfg.get(key)):
                new_cfg[key] = old_cfg[key]  # already encrypted; pass through
        # Encrypt any new plaintext secret values; pass-through already-encrypted ones.
        new_cfg = encrypt_dict_secrets(new_cfg, extra_keys=_SECRET_CONFIG_KEYS)
        data["config"] = new_cfg
    for key, value in data.items():
        setattr(dest, key, value)
    await db.flush()
    await db.refresh(dest)
    return dest


@router.delete("/{storage_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_auth])
async def delete_storage(storage_id: uuid.UUID, force: bool = False, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).where(StorageDestination.id == storage_id))
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Storage destination not found")

    # SPOF guard: refuse if backup jobs reference this destination, or
    # any non-deleted artifact is stored on it.
    from sqlalchemy import func, cast
    from sqlalchemy.dialects.postgresql import ARRAY
    from sqlalchemy.types import String as SAString
    from api.models.backup_job import BackupJob
    from api.models.backup_artifact import BackupArtifact

    job_count = (await db.execute(
        select(func.count()).select_from(BackupJob).where(
            BackupJob.destination_ids.any(storage_id)
        )
    )).scalar() or 0
    art_count = (await db.execute(
        select(func.count()).select_from(BackupArtifact).where(
            BackupArtifact.storage_id == storage_id,
            BackupArtifact.is_deleted == False,
        )
    )).scalar() or 0
    if (job_count or art_count) and not force:
        raise HTTPException(
            status_code=400,
            detail=f"Storage in use: {job_count} job(s) and {art_count} live artifact(s). "
                   f"Reassign jobs and clean artifacts first, or pass ?force=true.",
        )
    await db.delete(dest)


@router.post("/{storage_id}/test", dependencies=[_auth])
async def test_storage(storage_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).where(StorageDestination.id == storage_id))
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    from api.services.rclone_client import test_storage_connection
    success, message = await test_storage_connection(dest)
    return {"success": success, "message": message}


@router.get("/{storage_id}/usage", dependencies=[_auth])
async def storage_usage(storage_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).where(StorageDestination.id == storage_id))
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    from api.services.rclone_client import get_storage_usage
    usage = await get_storage_usage(dest)
    return usage


@router.get("/{storage_id}/browse", dependencies=[_auth])
async def browse_storage(storage_id: uuid.UUID, path: str = "/", db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StorageDestination).where(StorageDestination.id == storage_id))
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail="Storage destination not found")
    from api.services.rclone_client import list_storage_directory
    entries = await list_storage_directory(dest, path)
    return {"path": path, "entries": entries}
