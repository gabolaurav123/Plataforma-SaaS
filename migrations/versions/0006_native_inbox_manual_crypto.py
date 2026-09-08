"""Native inbox delivery mapping and immutable manual payment instructions."""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    for table, column in (("messages", "media"), ("payments", "instructions_snapshot")):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(column, sa.JSON(), nullable=False, server_default="{}"))
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, server_default=None)
    op.create_table(
        "inbox_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("bot_id", sa.String(36), nullable=False),
        sa.Column("message_id", sa.String(36), nullable=False),
        sa.Column("viewer_id", sa.BigInteger(), nullable=False),
        sa.Column("part", sa.String(10), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("message_id", "viewer_id", "part"),
        sa.UniqueConstraint("bot_id", "viewer_id", "telegram_message_id"),
        sa.ForeignKeyConstraint(["tenant_id", "bot_id"], ["managed_bots.tenant_id", "managed_bots.id"]),
        sa.ForeignKeyConstraint(["tenant_id", "message_id"], ["messages.tenant_id", "messages.id"]),
    )
    op.create_index("ix_inbox_deliveries_created_at", "inbox_deliveries", ["created_at"])
    op.create_index("ix_inbox_deliveries_tenant_id", "inbox_deliveries", ["tenant_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE inbox_deliveries ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE inbox_deliveries FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_isolation ON inbox_deliveries USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''))"
        )
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname='platform_api') THEN REVOKE ALL ON inbox_deliveries FROM platform_api; END IF; END $$"
        )


def downgrade():
    raise RuntimeError("Restore a verified backup to preserve message routes and payment instructions.")
