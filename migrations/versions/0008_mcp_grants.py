"""Grant table for granular agent permissions.

Revision ID: 0008_mcp_grants
Revises: 0007_credential_items
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0008_mcp_grants"
down_revision = "0007_credential_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_grant",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("mcp_client.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("permission", sa.String(20), nullable=False, server_default=sa.text("'read'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("client_id", "resource_type", "resource_id", "permission",
                            name="uq_mcp_grant"),
    )
    op.create_index("ix_mcp_grant_client", "mcp_grant", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_grant_client", table_name="mcp_grant")
    op.drop_table("mcp_grant")
