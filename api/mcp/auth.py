"""X-MCP-Key authentication.

Resolves an MCPClient row from the X-MCP-Key request header (compared
by SHA-256 hash). Updates last_used_at + use_count on every successful
match. Returns 401 on missing/invalid key, 403 on inactive/expired.
"""

import hashlib
from datetime import datetime, timezone

from fastapi import Header, HTTPException, status, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.mcp_client import MCPClient


def hash_mcp_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get_mcp_client(
    x_mcp_key: str | None = Header(default=None, alias="X-MCP-Key"),
    db: AsyncSession = Depends(get_db),
) -> MCPClient:
    if not x_mcp_key:
        raise HTTPException(status_code=401, detail="X-MCP-Key header required")

    key_hash = hash_mcp_key(x_mcp_key)
    result = await db.execute(select(MCPClient).where(MCPClient.key_hash == key_hash))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=401, detail="Unknown MCP key")
    if not client.is_active:
        raise HTTPException(status_code=403, detail="MCP client is disabled")
    if client.expires_at and client.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail="MCP client key expired")

    # Bug #21: atomic UPDATE prevents lost-increment under concurrent calls.
    # Tidigare: read use_count, +1, flush — två requests samtidigt såg samma
    # värde och båda skrev tillbaka N+1 i stället för N+2. The returned
    # `client` ORM-object is best-effort stale on use_count (callers only
    # rely on `id`/`name`/`is_active`); the persisted row is correct.
    now = datetime.now(timezone.utc)
    await db.execute(
        update(MCPClient)
        .where(MCPClient.id == client.id)
        .values(
            last_used_at=now,
            use_count=MCPClient.use_count + 1,
        )
    )
    await db.flush()
    return client
