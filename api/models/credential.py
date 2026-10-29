"""Credential vault models: items with unlimited fields.

Rebuilt 2026-10-29 from the single-value model. A credential item carries
an overlying title (e.g. "Aftonbladet") and any number of fields, each
field being a (field_title, value) pair such as ("inloggningsnamn",
"redaktion@aftonbladet.se"). Every field value is encrypted on its own
with the versioned Fernet key (see api/services/credentials_crypto.py),
which is what makes it possible to reveal, grant or rotate one field
without touching its siblings.

Plaintext is NEVER persisted: `encrypted_value` is a Fernet token in
binary form. Decryption happens only inside reveal-style endpoints under
explicit re-auth.

Migration 0007 converts every legacy single-value credential into an item
with exactly one field, reusing the old row id as the item id so audit
history stays connected. The legacy `credential` table is dropped.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class CredentialItem(Base):
    __tablename__ = "credential_item"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)

    # The overlying title: what all the fields below belong to.
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    # Free-text context (not encrypted; keep secrets out of it)
    description: Mapped[str | None] = mapped_column(Text)

    # Tagging for filter, scope, grouping
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=list)

    # MCP exposure (EPIC 4), defaults off, opt-in per item. Coarse
    # all-or-nothing visibility; per-field grants are a separate upcoming
    # layer and must not silently widen this one.
    mcp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mcp_scopes: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=list)

    # Lifecycle: an item's fields belong to one service and expire together.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotation_policy: Mapped[str | None] = mapped_column(String(50))  # manual, auto_30d, auto_90d, none
    provenance: Mapped[str | None] = mapped_column(String(255))  # e.g. "google_cloud_console", "notion-import"

    # Audit summary (full trail in audit_log). Item level aggregates every
    # reveal of any field; per-field counters live on the field rows.
    last_revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_revealed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reveal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    fields = relationship(
        "CredentialField",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="CredentialField.sort_order",
    )

    __table_args__ = (
        Index("ix_credential_item_owner", "owner_id"),
        Index("ix_credential_item_tags", "tags", postgresql_using="gin"),
        Index("ix_credential_item_expiry", "expires_at"),
    )


class CredentialField(Base):
    __tablename__ = "credential_field"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credential_item.id", ondelete="CASCADE"),
        nullable=False,
    )

    # What this value is, e.g. "inloggningsnamn" or "lösenord". Not secret;
    # it has to be readable to list and grant without decrypting anything.
    field_title: Mapped[str] = mapped_column(String(255), nullable=False)

    # Encrypted value (Fernet token, BYTEA). One token per field so one
    # field can be revealed, granted or rotated on its own.
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    reveal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    item = relationship("CredentialItem", back_populates="fields")

    __table_args__ = (
        # Field titles are the human handle within an item; two fields with
        # the same title in one item would make both reveal and grants
        # ambiguous. Across items the same title is of course fine.
        UniqueConstraint("item_id", "field_title", name="uq_credential_field_item_title"),
        Index("ix_credential_field_item", "item_id"),
    )
