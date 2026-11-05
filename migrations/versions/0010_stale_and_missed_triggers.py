"""Subscribe the failure channels to schedule.missed and job.stale.

Card DEV-7 adds two events for a backup that never started: schedule.missed
(a fire time seen too late to run) and job.stale (an active job with no run
for over 1.5 schedule intervals). A new event that no channel subscribes to
is logged and delivered to nobody, which is the silence this release exists
to end. Every channel that already subscribes to run.failed gets both, since
a backup that never ran is at least as serious as one that failed.

Idempotent: a channel that already has a trigger does not get it twice.

Revision ID: 0010_stale_and_missed_triggers
Revises: 0009_remove_discord_channels
"""

from alembic import op

revision = "0010_stale_and_missed_triggers"
down_revision = "0009_remove_discord_channels"
branch_labels = None
depends_on = None

NEW_TRIGGERS = ("schedule.missed", "job.stale")


def upgrade() -> None:
    for trigger in NEW_TRIGGERS:
        op.execute(
            "UPDATE notification_channel "
            f"SET triggers = array_append(triggers, '{trigger}') "
            "WHERE 'run.failed' = ANY(triggers) "
            f"AND NOT ('{trigger}' = ANY(triggers))"
        )


def downgrade() -> None:
    for trigger in NEW_TRIGGERS:
        op.execute(
            "UPDATE notification_channel "
            f"SET triggers = array_remove(triggers, '{trigger}') "
            f"WHERE '{trigger}' = ANY(triggers)"
        )
