"""Per-client grants: the granular, updatable permission layer for agents.

The coarse layer (MCPClient.scopes matched against item tags, gated by
item.mcp_enabled) answers "which tag neighbourhood may this client see".
It cannot answer "this agent may read 2 of 30 keys": for that, rights must
name exact resources. A grant row is one such name.

resource_type / resource_id semantics:

  credential_item    resource_id = item UUID   read every field of that item
  credential_field   resource_id = field UUID  read exactly that field
  api                resource_id = scope name  read a non-credential surface,
                                              currently 'backup.read' and
                                              'credentials.read'

Only 'read' exists. Agents get no write path by design; when a write scope
is ever needed it must be a deliberate addition, not a widened default.

Explicit grants are additive with the coarse layer: an item is visible via
tag-match (unchanged behaviour) OR because this specific client holds a
grant on it or on one of its fields. A grant deliberately overrides
mcp_enabled=False for this client alone: the grant IS the opt-in, recorded
and auditable, and flipping it must not silently widen what tag-matching
clients can see.

Grants are updatable as a set: PUT replaces the client's whole grant list,
so the answer to "what can this agent do" is one API call, one audit row,
no reconciliation guessing.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class MCPGrant(Base):
    __tablename__ = "mcp_grant"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_client.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # UUID-as-string for credential resources; the scope name for 'api'.
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    permission: Mapped[str] = mapped_column(String(20), nullable=False, default="read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    client = relationship("MCPClient", back_populates="grants")

    __table_args__ = (
        UniqueConstraint("client_id", "resource_type", "resource_id", "permission",
                         name="uq_mcp_grant"),
    )
