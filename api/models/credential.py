"""Credential vault model.

Stores API keys, OAuth tokens, passwords, certs, etc. encrypted with a
versioned Fernet key (see api/services/credentials_crypto.py).

Plaintext is NEVER persisted — `encrypted_value` is a Fernet token in
binary form. Decryption happens only inside reveal-style endpoints
under explicit re-auth.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, ForeignKey, Integer, Index, LargeBinary, Text, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base


class Credential(Base):
    __tablename__ = "credential"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Free-text classification of what's inside (api_key, oauth_token,
    # password, ssh_key, cert, json_blob, db_password). UI uses it for
    # icon + grouping; not enforced as enum to keep imports easy.
    credential_type: Mapped[str] = mapped_column(String(50), nullable=False, default="api_key")

    # Encrypted value (Fernet token). BYTEA per Kimi's spec — Fernet
    # tokens are URL-safe base64 ASCII so they'd fit Text too, but BYTEA
    # is the canonical column type for opaque ciphertext.
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Free-form description / notes (not encrypted — keep secrets out)
    description: Mapped[str | None] = mapped_column(Text)

    # Tagging for filter, scope, grouping
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=list)

    # MCP exposure (EPIC 4) — defaults off; opt-in per credential
    mcp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mcp_scopes: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=list)

    # Lifecycle
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotation_policy: Mapped[str | None] = mapped_column(String(50))  # manual, auto_30d, auto_90d, none
    provenance: Mapped[str | None] = mapped_column(String(255))  # e.g. "google_cloud_console", "notion-import"

    # Audit summary (full trail in audit_log)
    last_revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_revealed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reveal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_credential_owner_type", "owner_id", "credential_type"),
        Index("ix_credential_tags", "tags", postgresql_using="gin"),
        Index("ix_credential_expiry", "expires_at"),
    )
