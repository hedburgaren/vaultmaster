"""audit_log.created_at DESC index

Revision ID: 0005_audit_log_created_at_index
Revises: 0004_add_celery_task_id_to_run
Create Date: 2026-05-05

Adds a `created_at DESC` index on `audit_log` so the audit-router's
`ORDER BY created_at DESC LIMIT 50` doesn't full-scan + sort the entire
table. Bug #20 in the audit. Becomes load-bearing as soon as the table
crosses ~10k rows; right now it's still small but the cost of fixing it
is zero.

Idempotent: CREATE INDEX IF NOT EXISTS keeps a second `alembic upgrade
head` a no-op. CONCURRENTLY would be nicer in theory but Alembic wraps
every migration in a single transaction by default, which makes
CONCURRENTLY illegal — and on this size table the brief lock is
negligible.
"""
from __future__ import annotations

from alembic import op


revision = "0005_audit_log_created_at_index"
down_revision = "0004_add_celery_task_id_to_run"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_log_created_at "
        "ON audit_log (created_at DESC)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_audit_log_created_at")
