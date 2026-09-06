"""Mandatory tenant RLS on PostgreSQL; SQLite is for local development only."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = (
    "tenant_members",
    "onboarding",
    "bot_creation_requests",
    "managed_bots",
    "bot_secrets",
    "bot_settings",
    "bot_texts",
    "channels",
    "plans",
    "plan_prices",
    "contacts",
    "payments",
    "payment_charges",
    "payment_attempts",
    "bank_receipts",
    "payment_provider_configs",
    "subscriptions",
    "channel_invites",
    "conversations",
    "messages",
    "internal_notes",
    "tags",
    "contact_tags",
    "campaigns",
    "campaign_recipients",
    "automation_rules",
    "automation_executions",
    "crm_tasks",
    "coupons",
    "coupon_redemptions",
    "referrals",
    "attribution_links",
    "events",
    "saas_subscriptions",
    "saas_invoices",
    "saas_charges",
    "feature_flags",
    "usage_counters",
    "audit_logs",
    "telegram_updates",
    "provider_events",
    "jobs",
)


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'''CREATE POLICY tenant_isolation ON "{table}" USING
            (tenant_id = nullif(current_setting('app.tenant_id', true), '')) WITH CHECK
            (tenant_id = nullif(current_setting('app.tenant_id', true), ''))''')


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f'DROP POLICY tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
