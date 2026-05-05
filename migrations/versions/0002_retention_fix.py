"""retention_fix — null dangling FKs + ondelete=SET NULL

Revision ID: 0002_retention_fix
Revises: 0001_baseline
Create Date: 2026-05-05
"""
from alembic import op

revision = "0002_retention_fix"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade():
    # Cleanup dangling FK references — backup_job rows pointing at
    # retention_policy ids that no longer exist.
    op.execute("""
        UPDATE backup_job
        SET retention_id = NULL
        WHERE retention_id IS NOT NULL
          AND retention_id NOT IN (SELECT id FROM retention_policy)
    """)
    # Drop existing FK (no ondelete clause on it)
    op.drop_constraint("backup_job_retention_id_fkey", "backup_job", type_="foreignkey")
    # Recreate with ondelete=SET NULL so deleting a retention_policy does
    # not break dependent backup_job rows.
    op.create_foreign_key(
        "backup_job_retention_id_fkey",
        "backup_job",
        "retention_policy",
        ["retention_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("backup_job_retention_id_fkey", "backup_job", type_="foreignkey")
    op.create_foreign_key(
        "backup_job_retention_id_fkey",
        "backup_job",
        "retention_policy",
        ["retention_id"],
        ["id"],
    )
