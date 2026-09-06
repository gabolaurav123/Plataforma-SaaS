"""Commercial Telegram platform; additive migration preserving historical grants and payments."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

NEW_SCOPED = [
    "connection_attempts",
    "billing_cycles",
    "bot_admins",
    "bot_payment_methods",
    "reports",
    "platform_invoices",
    "access_offers",
    "invoice_adjustments",
    "plan_channels",
    "platform_settlements",
    "access_redemptions",
    "commission_entries",
    "payment_refunds",
    "subscription_history",
]


def upgrade():
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    with op.batch_alter_table("platform_settings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_platform_settings_created_at"), ["created_at"], unique=False)

    op.create_table(
        "connection_attempts",
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("request_key", sa.String(length=160), nullable=False),
        sa.Column("token_ciphertext", sa.JSON(), nullable=True),
        sa.Column("candidate", sa.JSON(), nullable=False),
        sa.Column("replace_bot_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["platform_users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "request_key"),
    )
    with op.batch_alter_table("connection_attempts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_connection_attempts_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_connection_attempts_expires_at"), ["expires_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_connection_attempts_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "billing_cycles",
        sa.Column("subscription_id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("plan_name", sa.String(length=40), nullable=False),
        sa.Column("fixed_usd_minor", sa.BigInteger(), nullable=False),
        sa.Column("commission_bps", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.BigInteger(), nullable=False),
        sa.Column("ends_at", sa.BigInteger(), nullable=False),
        sa.Column("due_at", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["saas_plans.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "subscription_id"],
            ["saas_subscriptions.tenant_id", "saas_subscriptions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subscription_id", "starts_at"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    with op.batch_alter_table("billing_cycles", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_billing_cycles_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_billing_cycles_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index("ix_cycle_close", ["status", "ends_at"], unique=False)

    op.create_table(
        "bot_admins",
        sa.Column("bot_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bot_id"],
            ["managed_bots.tenant_id", "managed_bots.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["platform_users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id", "user_id"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    with op.batch_alter_table("bot_admins", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_bot_admins_bot_id"), ["bot_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_bot_admins_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_bot_admins_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "bot_payment_methods",
        sa.Column("bot_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("public_config", sa.JSON(), nullable=False),
        sa.Column("secrets_ciphertext", sa.JSON(), nullable=True),
        sa.Column("webhook_key", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bot_id"],
            ["managed_bots.tenant_id", "managed_bots.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id", "provider"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("webhook_key"),
    )
    with op.batch_alter_table("bot_payment_methods", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_bot_payment_methods_bot_id"), ["bot_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_bot_payment_methods_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_bot_payment_methods_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "reports",
        sa.Column("bot_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("starts_at", sa.BigInteger(), nullable=False),
        sa.Column("ends_at", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("content_ciphertext", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bot_id"],
            ["managed_bots.tenant_id", "managed_bots.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_reports_bot_id"), ["bot_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_reports_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_reports_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "platform_invoices",
        sa.Column("cycle_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.String(length=60), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("fixed_minor", sa.BigInteger(), nullable=False),
        sa.Column("commission_minor", sa.BigInteger(), nullable=True),
        sa.Column("adjustment_minor", sa.BigInteger(), nullable=False),
        sa.Column("paid_minor", sa.BigInteger(), nullable=False),
        sa.Column("breakdown", sa.JSON(), nullable=False),
        sa.Column("due_at", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "cycle_id"],
            ["billing_cycles.tenant_id", "billing_cycles.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cycle_id"),
        sa.UniqueConstraint("number"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    with op.batch_alter_table("platform_invoices", schema=None) as batch_op:
        batch_op.create_index("ix_platform_invoice_due", ["status", "due_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_invoices_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_invoices_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "access_offers",
        sa.Column("bot_id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("code_ciphertext", sa.JSON(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("channel_ids", sa.JSON(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bot_id"],
            ["managed_bots.tenant_id", "managed_bots.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "plan_id"],
            ["plans.tenant_id", "plans.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    with op.batch_alter_table("access_offers", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_access_offers_bot_id"), ["bot_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_access_offers_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_access_offers_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "invoice_adjustments",
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("operation_key", sa.String(length=160), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["platform_invoices.tenant_id", "platform_invoices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "operation_key"),
    )
    with op.batch_alter_table("invoice_adjustments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_invoice_adjustments_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_invoice_adjustments_invoice_id"), ["invoice_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_invoice_adjustments_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "plan_channels",
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "channel_id"],
            ["channels.tenant_id", "channels.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "plan_id"],
            ["plans.tenant_id", "plans.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "channel_id"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    with op.batch_alter_table("plan_channels", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_plan_channels_channel_id"), ["channel_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_plan_channels_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_plan_channels_plan_id"), ["plan_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_plan_channels_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "platform_settlements",
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("method", sa.String(length=24), nullable=False),
        sa.Column("reference_hash", sa.String(length=64), nullable=False),
        sa.Column("reference", sa.String(length=240), nullable=False),
        sa.Column("amount_usd_minor", sa.BigInteger(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("receipt_ciphertext", sa.JSON(), nullable=True),
        sa.Column("media_type", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("submitted_by", sa.String(length=36), nullable=False),
        sa.Column("reviewed_by", sa.String(length=64), nullable=True),
        sa.Column("reviewed_at", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["platform_invoices.tenant_id", "platform_invoices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference_hash"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    with op.batch_alter_table("platform_settlements", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_platform_settlements_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_settlements_invoice_id"), ["invoice_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_platform_settlements_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "access_redemptions",
        sa.Column("offer_id", sa.String(length=36), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["contacts.tenant_id", "contacts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "offer_id"],
            ["access_offers.tenant_id", "access_offers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "subscription_id"],
            ["subscriptions.tenant_id", "subscriptions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("offer_id", "contact_id"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    with op.batch_alter_table("access_redemptions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_access_redemptions_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_access_redemptions_offer_id"), ["offer_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_access_redemptions_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "commission_entries",
        sa.Column("cycle_id", sa.String(length=36), nullable=True),
        sa.Column("charge_id", sa.String(length=36), nullable=False),
        sa.Column("entry_key", sa.String(length=160), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("gross_minor", sa.BigInteger(), nullable=False),
        sa.Column("commission_bps", sa.Integer(), nullable=False),
        sa.Column("usd_rate", sa.String(length=60), nullable=True),
        sa.Column("rate_source", sa.String(length=100), nullable=False),
        sa.Column("entry_type", sa.String(length=20), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "charge_id"],
            ["payment_charges.tenant_id", "payment_charges.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "cycle_id"],
            ["billing_cycles.tenant_id", "billing_cycles.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "entry_key"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    with op.batch_alter_table("commission_entries", schema=None) as batch_op:
        batch_op.create_index("ix_commission_cycle_currency", ["cycle_id", "currency"], unique=False)
        batch_op.create_index(batch_op.f("ix_commission_entries_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_commission_entries_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "payment_refunds",
        sa.Column("bot_id", sa.String(length=36), nullable=False),
        sa.Column("charge_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bot_id"],
            ["managed_bots.tenant_id", "managed_bots.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "charge_id"],
            ["payment_charges.tenant_id", "payment_charges.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id", "provider", "reference"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    with op.batch_alter_table("payment_refunds", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_payment_refunds_bot_id"), ["bot_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_payment_refunds_charge_id"), ["charge_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_payment_refunds_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_payment_refunds_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index("ix_refund_bot_period", ["bot_id", "created_at", "currency"], unique=False)

    op.create_table(
        "subscription_history",
        sa.Column("subscription_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("operation_key", sa.String(length=200), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "subscription_id"],
            ["subscriptions.tenant_id", "subscriptions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subscription_id", "revision"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "operation_key"),
    )
    with op.batch_alter_table("subscription_history", schema=None) as batch_op:
        batch_op.create_index(
            "ix_sub_history_timeline", ["subscription_id", "created_at", "revision"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_subscription_history_created_at"), ["created_at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_subscription_history_subscription_id"), ["subscription_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_subscription_history_tenant_id"), ["tenant_id"], unique=False)

    with op.batch_alter_table("bank_receipts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reviewed_at", sa.BigInteger(), nullable=True))

    with op.batch_alter_table("bot_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("preferences", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )

    with op.batch_alter_table("campaigns", schema=None) as batch_op:
        batch_op.add_column(sa.Column("media", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch_op.add_column(sa.Column("buttons", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("actor_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column("audience_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )

    with op.batch_alter_table("console_states", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("navigation", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
        batch_op.add_column(sa.Column("screen", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

    with op.batch_alter_table("contacts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("locale", sa.String(length=8), nullable=False, server_default=sa.text("'es'"))
        )
        batch_op.create_index("ix_contact_bot_created", ["bot_id", "created_at"], unique=False)
        batch_op.create_index("ix_contact_bot_page", ["bot_id", "id"], unique=False)

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("lane", sa.String(length=16), nullable=False, server_default=sa.text("'background'"))
        )
        batch_op.add_column(sa.Column("started_at", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("stream_key", sa.String(length=100), nullable=True))
        batch_op.add_column(
            sa.Column("sequence", sa.BigInteger(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.create_index("ix_job_lane_due", ["lane", "status", "run_at", "tenant_id"], unique=False)
        batch_op.create_index("ix_job_stale", ["status", "lease_until"], unique=False)
        batch_op.create_index("ix_job_stream_sequence", ["stream_key", "status", "sequence"], unique=False)
        batch_op.create_index(batch_op.f("ix_jobs_lane"), ["lane"], unique=False)
        batch_op.create_index(batch_op.f("ix_jobs_stream_key"), ["stream_key"], unique=False)

    with op.batch_alter_table("managed_bots", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "connection_kind", sa.String(length=20), nullable=False, server_default=sa.text("'MANAGED'")
            )
        )
        batch_op.add_column(sa.Column("disconnected_at", sa.BigInteger(), nullable=True))

    with op.batch_alter_table("payment_charges", schema=None) as batch_op:
        batch_op.create_index("ix_charge_bot_period", ["bot_id", "created_at", "currency"], unique=False)
        batch_op.create_index("ix_charge_payment", ["payment_id", "created_at"], unique=False)

    with op.batch_alter_table("payments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("provider_reference", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column("channel_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
        batch_op.create_index("ix_payment_bot_status", ["bot_id", "status", "created_at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_payments_provider_reference"), ["provider_reference"], unique=False
        )

    with op.batch_alter_table("plans", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.text("true"))
        )
        batch_op.add_column(sa.Column("archived_at", sa.BigInteger(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "purchase_message", sa.String(length=2000), nullable=False, server_default=sa.text("''")
            )
        )

    with op.batch_alter_table("platform_users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trial_used_at", sa.BigInteger(), nullable=True))

    with op.batch_alter_table("provider_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("payload_ciphertext", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'"))
        )

    with op.batch_alter_table("saas_plans", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("fixed_usd_minor", sa.BigInteger(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("commission_bps", sa.Integer(), nullable=False, server_default=sa.text("800"))
        )

    with op.batch_alter_table("saas_subscriptions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trial_starts_at", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("cycle_started_at", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("pending_plan_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column("grace_days", sa.Integer(), nullable=False, server_default=sa.text("3"))
        )
        batch_op.add_column(sa.Column("cancelled_at", sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key("fk_saas_pending_plan", "saas_plans", ["pending_plan_id"], ["id"])

    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("origin", sa.String(length=24), nullable=False, server_default=sa.text("'PAYMENT'"))
        )
        batch_op.add_column(
            sa.Column("channel_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
        batch_op.alter_column("payment_id", existing_type=sa.VARCHAR(length=36), nullable=True)
        batch_op.create_index(
            "ix_subscription_bot_status_end", ["bot_id", "status", "expires_at"], unique=False
        )
        batch_op.create_index(
            "ix_subscription_contact_status_end", ["contact_id", "status", "expires_at"], unique=False
        )

    with op.batch_alter_table("telegram_updates", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sensitive_ciphertext", sa.JSON(), nullable=True))

    with op.batch_alter_table("tenants", schema=None) as batch_op:
        batch_op.add_column(sa.Column("admin_suspended_at", sa.BigInteger(), nullable=True))

    _backfill()
    if op.get_bind().dialect.name == "postgresql":
        for table in NEW_SCOPED:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(
                f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), ''))"
            )
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname='platform_api') THEN REVOKE ALL ON platform_settings FROM platform_api; END IF; END $$"
        )


def _backfill():
    pg = op.get_bind().dialect.name == "postgresql"
    ident = "gen_random_uuid()::text" if pg else "lower(hex(randomblob(16)))"
    array = "json_build_array" if pg else "json_array"
    obj = "json_build_object" if pg else "json_object"
    empty_array = "'[]'::json" if pg else "'[]'"
    empty_object = "'{}'::json" if pg else "'{}'"
    timestamp = "extract(epoch from clock_timestamp())::bigint" if pg else "unixepoch()"
    op.execute("UPDATE saas_subscriptions SET trial_starts_at=created_at WHERE trial_ends_at>created_at")
    op.execute(
        "UPDATE platform_users SET trial_used_at=(SELECT min(s.created_at) FROM saas_subscriptions s JOIN tenants t ON t.id=s.tenant_id WHERE t.owner_user_id=platform_users.id)"
    )
    for name, fixed, bps in [("STARTER", 0, 800), ("PRO", 3000, 400), ("AGENCY", 8000, 100)]:
        op.execute(f"UPDATE saas_plans SET fixed_usd_minor={fixed}, commission_bps={bps} WHERE name='{name}'")
    op.execute(
        "UPDATE saas_plans SET features=(features::jsonb || jsonb_build_object('external_payments',true))::json"
        if pg
        else "UPDATE saas_plans SET features=json_set(features,'$.external_payments',json('true'))"
    )
    op.execute(
        f"INSERT INTO plan_channels(id,created_at,updated_at,tenant_id,plan_id,channel_id) SELECT {ident},created_at,updated_at,tenant_id,id,channel_id FROM plans WHERE channel_id IS NOT NULL"
    )
    op.execute(
        f"UPDATE payments SET channel_snapshot=(SELECT CASE WHEN p.channel_id IS NULL THEN {empty_array} ELSE {array}(p.channel_id) END FROM plans p WHERE p.id=payments.plan_id AND p.tenant_id=payments.tenant_id)"
    )
    op.execute(
        "UPDATE subscriptions SET channel_snapshot=(SELECT p.channel_snapshot FROM payments p WHERE p.id=subscriptions.payment_id AND p.tenant_id=subscriptions.tenant_id)"
    )
    op.execute(
        f"INSERT INTO subscription_history(id,created_at,updated_at,tenant_id,subscription_id,revision,actor_id,action,operation_key,before,after,reason) SELECT {ident},{timestamp},{timestamp},tenant_id,id,1,'migration','MIGRATED','migration:' || id,{empty_object},{obj}('status',status,'expires_at',expires_at,'starts_at',starts_at,'origin',origin,'plan_id',plan_id,'channels',channel_snapshot),'Imported from version 0004; previous audit records preserved' FROM subscriptions"
    )
    op.execute(
        f"INSERT INTO bot_admins(id,created_at,updated_at,tenant_id,bot_id,user_id,role,permissions,active) SELECT {ident},tm.created_at,tm.updated_at,tm.tenant_id,b.id,tm.user_id,CASE tm.role WHEN 'SUPERVISOR' THEN 'ADMIN' WHEN 'PAYMENTS' THEN 'FINANCE' ELSE tm.role END,{empty_array},tm.active FROM tenant_members tm JOIN managed_bots b ON b.tenant_id=tm.tenant_id"
    )
    config = (
        "CASE WHEN p.provider='BANK_TRANSFER' THEN json_build_object('_legacy_provider_id',p.id,'currency',p.public_config->>'currency') ELSE '{}'::json END"
        if pg
        else "CASE WHEN p.provider='BANK_TRANSFER' THEN json_object('_legacy_provider_id',p.id,'currency',json_extract(p.public_config,'$.currency')) ELSE '{}' END"
    )
    op.execute(
        f"INSERT INTO bot_payment_methods(id,created_at,updated_at,tenant_id,bot_id,provider,enabled,public_config,secrets_ciphertext,webhook_key) SELECT {ident},p.created_at,p.updated_at,p.tenant_id,b.id,p.provider,p.enabled,{config},p.secrets_ciphertext,{ident} FROM payment_provider_configs p JOIN managed_bots b ON b.tenant_id=p.tenant_id WHERE p.provider IN ('TELEGRAM_STARS','BANK_TRANSFER')"
    )
    op.execute(
        "UPDATE jobs SET lane='interactive' WHERE kind='UPDATE' OR kind='SEND' AND dedup_key LIKE 'console:%'"
    )
    op.execute("UPDATE provider_events SET status='DONE'")
    op.execute(
        f"INSERT INTO commission_entries(id,created_at,updated_at,tenant_id,cycle_id,charge_id,entry_key,currency,gross_minor,commission_bps,usd_rate,rate_source,entry_type) SELECT {ident},created_at,updated_at,tenant_id,NULL,id,'sale:' || id,currency,amount_minor,0,CASE WHEN currency='USD' THEN '1' ELSE NULL END,'legacy','TRIAL_OR_LEGACY' FROM payment_charges"
    )
    op.execute(
        f"INSERT INTO payment_refunds(id,created_at,updated_at,tenant_id,bot_id,charge_id,provider,reference,amount_minor,currency,actor_id,reason) SELECT {ident},refunded_at,refunded_at,tenant_id,bot_id,id,provider,'legacy:' || id,amount_minor,currency,'migration','Existing refund before version 0005' FROM payment_charges WHERE refunded_at IS NOT NULL"
    )
    # Unknown old campaign expansion cursors are paused for deliberate owner review.
    op.execute(
        "UPDATE campaigns SET status='PAUSED', cursor=CASE WHEN cursor='DONE' THEN 'DONE' ELSE 'SNAPSHOT' END WHERE status IN ('RUNNING','SCHEDULED','PAUSED')"
    )


def downgrade():
    raise RuntimeError(
        "Version 0005 contains financial history and free subscriptions. Restore a verified backup instead of dropping these records."
    )
