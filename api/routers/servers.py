import os
import uuid
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.database import get_db
from api.models.server import Server
from api.models.user import User
from api.schemas import ServerCreate, ServerUpdate, ServerOut
from api.services.ssh_client import test_ssh_connection, connectivity_is_testable, list_remote_directory, list_remote_databases, list_remote_docker, prune_docker_volumes

router = APIRouter(prefix="/servers", tags=["servers"], dependencies=[Depends(get_current_user)])

SSH_KEY_DIR = Path("/root/.ssh")


class TestConnectionRequest(BaseModel):
    host: str
    port: int = 22
    auth_type: str = "ssh_key"
    ssh_user: str | None = "root"
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    meta: dict = {}


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
    meta = {**body.meta}
    if body.ssh_password:
        meta["ssh_password"] = body.ssh_password
    fake_server = SimpleNamespace(
        host=body.host,
        port=body.port,
        auth_type=body.auth_type,
        ssh_user=body.ssh_user or "root",
        ssh_key_path=body.ssh_key_path,
        meta=meta,
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


@router.get("/{server_id}/databases")
async def list_databases(server_id: uuid.UUID, db_type: str = "postgresql", db: AsyncSession = Depends(get_db)):
    """List databases on a server using its stored DB credentials."""
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    databases = await list_remote_databases(server, db_type)
    return {"databases": databases, "db_type": db_type}


@router.get("/{server_id}/docker")
async def list_docker(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List Docker containers and volumes on a server."""
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    docker_info = await list_remote_docker(server)
    return docker_info


@router.post("/{server_id}/docker/prune-volumes")
async def prune_volumes(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Remove unused Docker volumes on a server."""
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return await prune_docker_volumes(server)


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
async def delete_server(server_id: uuid.UUID, force: bool = False, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # SPOF guard: refuse if active backup jobs still target this server.
    from api.models.backup_job import BackupJob
    job_count = (await db.execute(
        select(func.count()).select_from(BackupJob).where(
            BackupJob.server_id == server_id,
            BackupJob.is_active == True,
        )
    )).scalar() or 0
    if job_count > 0 and not force:
        raise HTTPException(
            status_code=400,
            detail=f"{job_count} active backup job(s) target this server. "
                   f"Disable or reassign them first, or pass ?force=true.",
        )
    await db.delete(server)


@router.post("/{server_id}/test")
async def test_connection(server_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    success, message = await test_ssh_connection(server)
    tested = connectivity_is_testable(server)
    if success and tested:
        from datetime import datetime, timezone
        server.last_seen = datetime.now(timezone.utc)
        server.last_error = None
        await db.flush()
    elif not success:
        server.last_error = message
        await db.flush()
    # success but not tested: leave last_seen alone. Stamping it would record
    # a sighting that never happened.
    return {"success": success, "message": message, "connectivity_tested": tested}


@router.get("/{server_id}/browse")
async def browse_server(server_id: uuid.UUID, path: str = "/", db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    entries = await list_remote_directory(server, path)
    return {"path": path, "entries": entries}


def _parse_du_output(out: str, path: str) -> int:
    """Parse `du -sb PATH` output into bytes. First field, one line.

    Extracted so the picker's size promise is testable: `du -sb` prints
    apparent size in bytes, which is what an operator means when asking
    how big a folder is, not block-allocated size.
    """
    line = (out or "").strip().splitlines()[0] if (out or "").strip() else ""
    if not line:
        raise ValueError(f"du returned no output for {path}")
    first = line.split()[0]
    if not first.isdigit():
        raise ValueError(f"du output not parseable for {path}: {line[:80]}")
    return int(first)


@router.post("/{server_id}/dirsize")
async def server_dir_size(
    server_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Apparent size in bytes of one directory, on demand.

    The tree picker lists sizes for free (files carry them in the listing);
    directories do not, and running du for every expanded folder would
    hammer the disk for numbers nobody asked for. So: the UI asks for one
    folder when the operator asks for it, with a timeout, and the answer
    says both the number and how long it took.
    """
    from time import monotonic

    from api.services.ssh_client import run_remote_command

    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    import shlex as _shlex
    raw = str(body.get("path") or "").strip()
    if not raw.startswith("/"):
        raise HTTPException(status_code=422, detail="path must be absolute")
    # -s: one summary line. -B1: bytes, not blocks (apparent size).
    started = monotonic()
    code, out, err = await run_remote_command(
        server, f"du -sb -B1 {_shlex.quote(raw)}", timeout=120
    )
    took_ms = int((monotonic() - started) * 1000)
    if code != 0:
        raise HTTPException(status_code=502, detail=f"du failed: {(err or '').strip()[:200]}")
    try:
        bytes_ = _parse_du_output(out, raw)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"path": raw, "bytes": bytes_, "took_ms": took_ms}
