"""Laptop check-in: a token hash on server, and a schedule that may be empty.

plastop is a laptop that is not always online. Instead of the server pulling
from it on fixed crons, the laptop calls POST /servers/checkin when it is
switched on and has a network that is not mobile. That needs two schema
changes:

- server.checkin_token_hash: SHA-256 of the per-server check-in token (the raw
  token is never stored), unique so the token lookup is one indexed query.
- backup_job.schedule_cron becomes nullable: a job without a schedule is
  started only by the check-in, and is skipped by the scheduler and by the
  stale-job scan.

Existing rows are untouched; the operator sets the plastop jobs' schedule to
null after deploy.

Revision ID: 0011_checkin_and_nullable_cron
Revises: 0010_stale_and_missed_triggers
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_checkin_and_nullable_cron"
down_revision = "0010_stale_and_missed_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("server", sa.Column("checkin_token_hash", sa.String(64), nullable=True))
    op.create_index("ix_server_checkin_token_hash", "server", ["checkin_token_hash"], unique=True)
    op.alter_column("backup_job", "schedule_cron", existing_type=sa.String(100), nullable=True)


def downgrade() -> None:
    # A job without a schedule cannot go back to NOT NULL as it is. Give it the
    # one-off placeholder "0 3 * * *" so the downgrade cannot fail on the data.
    op.execute("UPDATE backup_job SET schedule_cron = '0 3 * * *' WHERE schedule_cron IS NULL")
    op.alter_column("backup_job", "schedule_cron", existing_type=sa.String(100), nullable=False)
    op.drop_index("ix_server_checkin_token_hash", table_name="server")
    op.drop_column("server", "checkin_token_hash")
