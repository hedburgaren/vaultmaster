"""baseline — schema already created via SQLAlchemy create_all

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-05
"""
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Baseline: schema is created via SQLAlchemy Base.metadata.create_all()
    # at app startup. This migration only stamps the alembic_version table.
    pass


def downgrade():
    pass
