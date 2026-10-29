"""Rebuild the credential vault: items with unlimited fields.

The legacy `credential` table held exactly one encrypted value per row.
The new shape is a `credential_item` (overlying title, e.g. "Aftonbladet")
with any number of `credential_field` rows, each a (field_title, value)
pair such as ("inloggningsnamn", "..."), every value encrypted on its own.

Conversion rules, deliberately conservative:

- Every legacy row becomes one item with exactly one field. Nothing is
  merged by name: two legacy rows named "Google" stay two items, because
  guessing that they belong together could put a value under the wrong
  title, and a wrong title on a secret is a wrong grant later.
- The legacy row id is REUSED as the item id. audit_log rows reference
  credential ids; reusing them keeps 2026-07 and onwards reveal history
  connected to the items it was actually about.
- encrypted_value and key_version are copied verbatim. A Fernet token is
  self-contained and its meaning does not depend on which row holds it,
  so no decrypt/re-encrypt round is needed (and none could fail).
- The legacy field title comes from credential_type via a label map,
  falling back to the raw type string. Unknown types must not block the
  migration; the title is editable afterwards.
- reveal_count / last_revealed_at move to both the item and its single
  field: the item aggregates, the field records its own reveals.
- The legacy table is dropped in the same migration. Keeping it around
  would leave two live shapes for one concept, and every read path would
  need both. Downgrade recreates it from the FIRST field of each item and
  is therefore lossy for items with several fields; that is accepted
  because the old shape cannot represent them at all.

Revision ID: 0007_credential_items
Revises: 0006_artifact_purged_at
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "0007_credential_items"
down_revision = "0006_artifact_purged_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credential_item",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", ARRAY(sa.String()), nullable=True),
        sa.Column("mcp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("mcp_scopes", ARRAY(sa.String()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotation_policy", sa.String(50), nullable=True),
        sa.Column("provenance", sa.String(255), nullable=True),
        sa.Column("last_revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_revealed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("reveal_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_credential_item_owner", "credential_item", ["owner_id"])
    op.create_index("ix_credential_item_tags", "credential_item", ["tags"], postgresql_using="gin")
    op.create_index("ix_credential_item_expiry", "credential_item", ["expires_at"])

    op.create_table(
        "credential_field",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "item_id",
            UUID(as_uuid=True),
            sa.ForeignKey("credential_item.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_title", sa.String(255), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("reveal_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("item_id", "field_title", name="uq_credential_field_item_title"),
    )
    op.create_index("ix_credential_field_item", "credential_field", ["item_id"])

    # Convert rows. Ciphertext moves verbatim; see docstring.
    op.execute(
        """
        INSERT INTO credential_item (
            id, owner_id, title, description, tags, mcp_enabled, mcp_scopes,
            expires_at, rotation_policy, provenance,
            last_revealed_at, last_revealed_by, reveal_count,
            created_at, updated_at
        )
        SELECT
            id, owner_id, name, description, tags, mcp_enabled, mcp_scopes,
            expires_at, rotation_policy, provenance,
            last_revealed_at, last_revealed_by, reveal_count,
            created_at, updated_at
        FROM credential
        """
    )
    op.execute(
        """
        INSERT INTO credential_field (
            id, item_id, field_title, encrypted_value, key_version,
            sort_order, reveal_count, last_revealed_at, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            c.id,
            COALESCE(m.label, c.credential_type),
            c.encrypted_value,
            c.key_version,
            0,
            c.reveal_count,
            c.last_revealed_at,
            c.created_at,
            c.updated_at
        FROM credential AS c
        LEFT JOIN (
            VALUES
                ('api_key',      'API key'),
                ('password',     'Lösenord'),
                ('oauth_token',  'OAuth-token'),
                ('token',        'Token'),
                ('secret',       'Hemlighet'),
                ('ssh_key',      'SSH-nyckel'),
                ('cert',         'Certifikat'),
                ('db_password',  'Databaslösenord'),
                ('json_blob',    'JSON')
        ) AS m(type, label) ON m.type = c.credential_type
        """
    )

    op.drop_table("credential")


def downgrade() -> None:
    """Recreate the single-value table from the FIRST field of each item.

    Lossy for items with more than one field: the old shape cannot
    represent them, and silently concatenating values would fabricate a
    secret that never existed. Extra fields are dropped, loudly counted
    into the log so the operator can see what was lost before running it.
    """
    op.create_table(
        "credential",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("credential_type", sa.String(50), nullable=False, server_default=sa.text("'api_key'")),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", ARRAY(sa.String()), nullable=True),
        sa.Column("mcp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("mcp_scopes", ARRAY(sa.String()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotation_policy", sa.String(50), nullable=True),
        sa.Column("provenance", sa.String(255), nullable=True),
        sa.Column("last_revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_revealed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("reveal_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.execute(
        """
        INSERT INTO credential (
            id, owner_id, name, credential_type, encrypted_value, key_version,
            description, tags, mcp_enabled, mcp_scopes, expires_at,
            rotation_policy, provenance, last_revealed_at, last_revealed_by,
            reveal_count, created_at, updated_at
        )
        SELECT
            i.id, i.owner_id, i.title, 'api_key', f.encrypted_value, f.key_version,
            i.description, i.tags, i.mcp_enabled, i.mcp_scopes, i.expires_at,
            i.rotation_policy, i.provenance, i.last_revealed_at, i.last_revealed_by,
            i.reveal_count, i.created_at, i.updated_at
        FROM credential_item AS i
        JOIN LATERAL (
            SELECT encrypted_value, key_version
            FROM credential_field
            WHERE item_id = i.id
            ORDER BY sort_order, created_at
            LIMIT 1
        ) AS f ON true
        """
    )

    op.execute(
        """
        DO $$
        DECLARE
            extra integer;
        BEGIN
            SELECT count(*) INTO extra FROM credential_field;
            IF extra > (SELECT count(*) FROM credential) THEN
                RAISE NOTICE 'downgrade 0007: % field(s) beyond one per item were dropped', extra - (SELECT count(*) FROM credential);
            END IF;
        END $$;
        """
    )

    op.drop_table("credential_field")
    op.drop_table("credential_item")
