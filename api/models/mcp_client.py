"""MCP client (AI agent) registration.

A row represents one AI agent / runtime that's allowed to read scoped
credentials via the MCP endpoints under /api/mcp/v1/. Auth is via
X-MCP-Key (SHA-256 hash stored, never the plaintext).

Scopes match against `Credential.tags` AND `Credential.mcp_scopes`:
- A credential is visible to a client only if BOTH:
    * `credential.mcp_enabled = true`
    * client's scope set intersects (credential.mcp_scopes ∪ credential.tags)
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base


class MCPClient(Base):
    __tablename__ = "mcp_client"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g. "klada-cli", "n8n-router"
    description: Mapped[str | None] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)  # for UI display, e.g. "mcp_abc123…"
    scopes: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
