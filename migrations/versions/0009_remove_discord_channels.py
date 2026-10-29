"""Remove Discord notification channels.

Discord left the environment in October 2026 (Telegram is the only
channel; alarms go through Kurwa Bober). The code path is gone from the
notifier in the same release, so leftover rows would answer every event
with "Unknown channel type: discord" and nothing else: noise about a
channel that can never deliver again.

The DELETE names its rows explicitly. Telegram, email, ntfy, slack and
generic webhook channels are untouched.

Revision ID: 0009_remove_discord_channels
Revises: 0008_mcp_grants
"""

from alembic import op

revision = "0009_remove_discord_channels"
down_revision = "0008_mcp_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM notification_channel WHERE channel_type = 'discord'")


def downgrade() -> None:
    # No restore: the transport no longer exists, and resurrecting rows
    # pointing at a retired bridge would be a channel that lies.
    pass
