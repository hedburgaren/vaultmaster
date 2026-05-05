"""encrypt existing notification_channel.config secrets

Revision ID: 0003_encrypt_notif_secrets
Revises: 0002_retention_fix
Create Date: 2026-05-05

Retroactively encrypts plaintext bot tokens, webhook URLs, chat IDs, etc.
in existing `notification_channel.config` JSONB rows. Bug #22 — these fields
were stored in clear before this migration; reading them required only DB
read access on a JSONB column.

Idempotent by design: every value already prefixed with `enc:v` (the
canonical "this is encrypted" sentinel from `credentials_crypto.py`) is
left untouched, so running the migration twice is a no-op.

If `CREDENTIALS_MASTER_KEYS` is missing or the crypto subsystem can't
boot, the migration logs a warning per row and leaves the value
plaintext rather than aborting — the runtime `_send_*` functions will
still treat raw plaintext as already-decrypted and the channel keeps
working. (You should fix the env and re-run, but a half-done world is
strictly better than a broken-deploy world.)
"""
from __future__ import annotations

import json
import logging

from alembic import op
import sqlalchemy as sa


revision = "0003_encrypt_notif_secrets"
down_revision = "0002_retention_fix"
branch_labels = None
depends_on = None


# Mirrors api.services.credentials_crypto.SECRET_FIELD_NAMES at the time
# this migration was written. We snapshot the list inline rather than
# importing it so the migration history is self-contained — future code
# that adds/removes secret keys won't retroactively change what 0003 did.
_SECRET_KEYS = {
    "password",
    "secret_access_key",
    "secret_key",
    "access_key_secret",
    "oauth_token",
    "refresh_token",
    "client_secret",
    "api_secret",
    "private_key",
    "smtp_password",
    "bot_token",
    "bridge_token",
    "webhook_url",
    "chat_id",
}

_ENC_PREFIX = "enc:v"

log = logging.getLogger("alembic.0003_encrypt_notif_secrets")


def upgrade():
    bind = op.get_bind()

    # Try to load the crypto layer. If it fails (e.g. missing env var in a
    # local dev box), log loudly and skip — empty result is still a
    # successful, idempotent migration.
    try:
        from api.services.credentials_crypto import get_crypto, encrypt_dict_secrets  # noqa
        get_crypto()  # forces validation of CREDENTIALS_MASTER_KEYS
    except Exception as exc:
        log.warning(
            "0003: crypto unavailable (%s) — migration will skip all rows. "
            "Re-run after fixing CREDENTIALS_MASTER_KEYS.",
            exc,
        )
        return

    rows = bind.execute(sa.text(
        "SELECT id, config FROM notification_channel"
    )).fetchall()

    encrypted_count = 0
    skipped_count = 0
    for row in rows:
        cfg = row.config
        # JSONB comes back as a dict already on most psycopg drivers; tolerate
        # either form to keep the migration robust against driver quirks.
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        if not isinstance(cfg, dict) or not cfg:
            skipped_count += 1
            continue

        changed = False
        new_cfg = dict(cfg)
        for k, v in list(new_cfg.items()):
            if k.lower() not in _SECRET_KEYS:
                continue
            if not isinstance(v, str) or not v:
                continue
            if v.startswith(_ENC_PREFIX):
                # Already encrypted — idempotent skip.
                continue
            try:
                encrypt_dict_secrets(new_cfg)
                changed = True
                # encrypt_dict_secrets mutates in place across all secret keys;
                # one call covers everything in this row, so break.
                break
            except Exception as exc:
                log.warning(
                    "0003: failed to encrypt config for channel %s key %s: %s",
                    row.id, k, exc,
                )

        if changed:
            bind.execute(
                sa.text("UPDATE notification_channel SET config = CAST(:cfg AS jsonb) WHERE id = :id"),
                {"cfg": json.dumps(new_cfg), "id": row.id},
            )
            encrypted_count += 1
        else:
            skipped_count += 1

    log.info(
        "0003: encrypted %d notification_channel rows, skipped %d (already encrypted, empty, or no secret fields).",
        encrypted_count,
        skipped_count,
    )


def downgrade():
    # No-op: we don't decrypt back to plaintext on rollback. The encrypted
    # values still validate against runtime decrypt_dict_secrets, so
    # downgrading the schema doesn't break anything — but actively
    # un-encrypting secrets would defeat the entire point of the migration.
    pass
