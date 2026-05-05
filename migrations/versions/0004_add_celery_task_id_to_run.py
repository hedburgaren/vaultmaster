"""add celery_task_id to backup_run

Revision ID: 0004_add_celery_task_id_to_run
Revises: 0003_encrypt_notif_secrets
Create Date: 2026-05-05

Adds `backup_run.celery_task_id` so the cancel-endpoint can revoke the
underlying Celery task instead of only flipping DB-status (Bug #12). The
previous implementation set `status='cancelled'` then watched the task
overwrite it back to `success` a few seconds later — exactly the
silent-failure mode this column eliminates.

Idempotent: uses IF NOT EXISTS so a second `alembic upgrade head` is a
no-op. Column is nullable because runs created before this migration —
and the in-flight backup currently held by the worker — won't have one;
the cancel-endpoint must therefore treat NULL as "no task to revoke".
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_add_celery_task_id_to_run"
down_revision = "0003_encrypt_notif_secrets"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE backup_run "
        "ADD COLUMN IF NOT EXISTS celery_task_id varchar(100)"
    )


def downgrade():
    op.execute(
        "ALTER TABLE backup_run DROP COLUMN IF EXISTS celery_task_id"
    )
