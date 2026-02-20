import os
import uuid
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.database import get_db
from api.models.server import Server
from api.models.user import User
from api.schemas import ServerCreate, ServerUpdate, ServerOut
from api.services.ssh_client import test_ssh_connection, list_remote_directory

router = APIRouter(prefix="/servers", tags=["servers"], dependencies=[Depends(get_current_user)])

SSH_KEY_DIR = Path("/root/.ssh")


class TestConnectionRequest(BaseModel):
    host: str
    port: int = 22
    auth_type: str = "ssh_key"
    ssh_user: str | None = "root"
    ssh_key_path: str | None = None


@router.get("", response_model=list[ServerOut])
async def list_servers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Server).order_by(Server.name))
    return result.scalars().all()


@router.post("", response_model=ServerOut, status_code=status.HTTP_201_CREATED)
async def create_server(body: ServerCreate, db: AsyncSession = Depends(get_db)):
    server = Server(**body.model_dump(exclude={"api_token"}))
    if body.api_token:
        from api.services.encryption import encrypt_secret
        server.api_token_encrypted = encrypt_secret(body.api_token)
    db.add(server)
    await db.flush()
    await db.refresh(server)
    return server


@router.post("/test-connection")
async def test_connection_presave(body: TestConnectionRequest):
    """Test SSH connection without saving the server first."""
    fake_server = SimpleNamespace(
        host=body.host,
        port=body.port,
        auth_type=body.auth_type,
        ssh_user=body.ssh_user or "root",
        ssh_key_path=body.ssh_key_path,
        name="(unsaved)",
    )
    success, message = await test_ssh_connection(fake_server)
    return {"success": success, "message": message}


@router.get("/ssh-keys")
async def list_ssh_keys():
    """List available SSH keys."""
    keys = []
    if SSH_KEY_DIR.exists():
        for f in sorted(SSH_KEY_DIR.iterdir()):
            if f.suffix == '.pub':
                private = f.with_suffix('')
                keys.append({
                    "name": private.name,
                    "path": str(private),
                    "public_key": f.read_text().strip(),
                    "has_private": private.exists(),
                })
    return keys


@router.post("/ssh-keys/generate")
async def generate_ssh_key():
    """Generate a new ed25519 SSH keypair."""
    import subprocess
    SSH_KEY_DIR.mkdir(parents=True, exist_ok=True)
    key_path = SSH_KEY_DIR / "vaultmaster_ed25519"
    if key_path.exists():
        pub = key_path.with_suffix('.pub')
        return {"path": str(key_path), "public_key": pub.read_text().strip() if pub.exists() else None, "message": "Key already exists"}
    result = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", "", "-C", "vaultmaster@backup"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Key generation failed: {result.stderr}")
    pub = key_path.with_suffix('.pub')
    return {"path": str(key_path), "public_key": pub.read_text().strip() if pub.exists() else None, "message": "Key generated"}


@router.get("/{server_id}", response_model=ServerOut)
async def get_server(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


@router.put("/{server_id}", response_model=ServerOut)
async def update_server(server_id: uuid.UUID, body: ServerUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    for key, value in body.model_dump(exclude_unset=True, exclude={"api_token"}).items():
        setattr(server, key, value)
    if body.api_token is not None:
        from api.services.encryption import encrypt_secret
        server.api_token_encrypted = encrypt_secret(body.api_token)
    await db.flush()
    await db.refresh(server)
    return server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    await db.delete(server)


@router.post("/{server_id}/test")
async def test_connection(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    success, message = await test_ssh_connection(server)
    return {"success": success, "message": message}


@router.get("/{server_id}/browse")
async def browse_server(server_id: uuid.UUID, path: str = "/", db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    entries = await list_remote_directory(server, path)
    return {"path": path, "entries": entries}
