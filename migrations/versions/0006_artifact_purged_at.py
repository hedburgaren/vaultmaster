"""Add purged_at to backup_artifact.

Separates "flagged for deletion" from "file is actually gone".

Both is_deleted and deleted_at are set by apply_rotation at flag time, before
anything touches storage. Neither can therefore tell purge whether a file has
already been removed, which meant plan_purge re-planned every historical row on
every run: 6255 items and 5382 GB per day, almost all of them already deleted.
delete_file_from_storage answers "already absent" with ok=True, so they were
counted as fresh deletions and the daily notice reported the same space over
and over.

Filtering on deleted_at was tried and reverted: because rotation sets it too,
the filter made phase 2 of enforce_retention skip exactly what phase 1 had just
flagged, so retention went back to marking rows while the disk filled up.

purged_at is written only by execute_purge, and only once the backend has
confirmed the file is gone.

No backfill on purpose. Backfilling from deleted_at would hide any historical
row whose file is still present, stranding it forever. Instead the first purge
run after this migration does the full expensive pass once, stamps every row it
confirms gone, and every run after that only sees genuinely new expirations.

Revision ID: 0006_artifact_purged_at
Revises: 0005_audit_log_created_at_index
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_artifact_purged_at"
down_revision = "0005_audit_log_created_at_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "backup_artifact",
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
    )
    # plan_purge filters on this on every run, over the full artifact table.
    op.create_index(
        "ix_backup_artifact_purged_at",
        "backup_artifact",
        ["purged_at"],
        postgresql_where=sa.text("purged_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_backup_artifact_purged_at", table_name="backup_artifact")
    op.drop_column("backup_artifact", "purged_at")
