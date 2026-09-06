"""Commercial records; customer money and platform receivables never share a ledger."""

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, Record, Scoped, scoped_constraints, tenant_fk


class PaymentRefund(Scoped, Base):
    __tablename__ = "payment_refunds"
    __table_args__ = scoped_constraints(
        tenant_fk("bot_id", "managed_bots"),
        tenant_fk("charge_id", "payment_charges"),
        UniqueConstraint("bot_id", "provider", "reference"),
        Index("ix_refund_bot_period", "bot_id", "created_at", "currency"),
    )
    bot_id: Mapped[str] = mapped_column(String(36), index=True)
    charge_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    reference: Mapped[str] = mapped_column(String(255))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8))
    actor_id: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(500), default="")


class ConnectionAttempt(Scoped, Base):
    __tablename__ = "connection_attempts"
    __table_args__ = scoped_constraints(UniqueConstraint("tenant_id", "request_key"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id"))
    request_key: Mapped[str] = mapped_column(String(160))
    token_ciphertext: Mapped[dict | None] = mapped_column(JSON, deferred=True)
    candidate: Mapped[dict] = mapped_column(JSON, default=dict)
    replace_bot_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)
    error_code: Mapped[str | None] = mapped_column(String(64))


class BotAdmin(Scoped, Base):
    __tablename__ = "bot_admins"
    __table_args__ = scoped_constraints(
        tenant_fk("bot_id", "managed_bots"), UniqueConstraint("bot_id", "user_id")
    )
    bot_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id"))
    role: Mapped[str] = mapped_column(String(20))
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PlanChannel(Scoped, Base):
    __tablename__ = "plan_channels"
    __table_args__ = scoped_constraints(
        tenant_fk("plan_id", "plans"),
        tenant_fk("channel_id", "channels"),
        UniqueConstraint("plan_id", "channel_id"),
    )
    plan_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str] = mapped_column(String(36), index=True)


class SubscriptionHistory(Scoped, Base):
    __tablename__ = "subscription_history"
    __table_args__ = scoped_constraints(
        tenant_fk("subscription_id", "subscriptions"),
        UniqueConstraint("tenant_id", "operation_key"),
        UniqueConstraint("subscription_id", "revision"),
        Index("ix_sub_history_timeline", "subscription_id", "created_at", "revision"),
    )
    subscription_id: Mapped[str] = mapped_column(String(36), index=True)
    revision: Mapped[int] = mapped_column(BigInteger, default=1)
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(40))
    operation_key: Mapped[str] = mapped_column(String(200))
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(String(500), default="")


class AccessOffer(Scoped, Base):
    __tablename__ = "access_offers"
    __table_args__ = scoped_constraints(
        tenant_fk("bot_id", "managed_bots"), tenant_fk("plan_id", "plans"), UniqueConstraint("code_hash")
    )
    bot_id: Mapped[str] = mapped_column(String(36), index=True)
    plan_id: Mapped[str] = mapped_column(String(36))
    code_hash: Mapped[str] = mapped_column(String(64))
    code_ciphertext: Mapped[dict] = mapped_column(JSON)
    duration_days: Mapped[int] = mapped_column()
    channel_ids: Mapped[list] = mapped_column(JSON, default=list)
    max_uses: Mapped[int] = mapped_column()
    uses: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[int] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    note: Mapped[str] = mapped_column(String(500), default="")


class AccessRedemption(Scoped, Base):
    __tablename__ = "access_redemptions"
    __table_args__ = scoped_constraints(
        tenant_fk("offer_id", "access_offers"),
        tenant_fk("contact_id", "contacts"),
        tenant_fk("subscription_id", "subscriptions"),
        UniqueConstraint("offer_id", "contact_id"),
    )
    offer_id: Mapped[str] = mapped_column(String(36), index=True)
    contact_id: Mapped[str] = mapped_column(String(36))
    subscription_id: Mapped[str] = mapped_column(String(36))


class BotPaymentMethod(Scoped, Base):
    __tablename__ = "bot_payment_methods"
    __table_args__ = scoped_constraints(
        tenant_fk("bot_id", "managed_bots"), UniqueConstraint("bot_id", "provider")
    )
    bot_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    public_config: Mapped[dict] = mapped_column(JSON, default=dict)
    secrets_ciphertext: Mapped[dict | None] = mapped_column(JSON, deferred=True)
    webhook_key: Mapped[str] = mapped_column(String(36), unique=True)


class PlatformSetting(Record, Base):
    __tablename__ = "platform_settings"
    key: Mapped[str] = mapped_column(String(80), unique=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class BillingCycle(Scoped, Base):
    __tablename__ = "billing_cycles"
    __table_args__ = scoped_constraints(
        tenant_fk("subscription_id", "saas_subscriptions"),
        UniqueConstraint("subscription_id", "starts_at"),
        Index("ix_cycle_close", "status", "ends_at"),
    )
    subscription_id: Mapped[str] = mapped_column(String(36))
    plan_id: Mapped[str] = mapped_column(ForeignKey("saas_plans.id"))
    plan_name: Mapped[str] = mapped_column(String(40))
    fixed_usd_minor: Mapped[int] = mapped_column(BigInteger)
    commission_bps: Mapped[int] = mapped_column()
    starts_at: Mapped[int] = mapped_column(BigInteger)
    ends_at: Mapped[int] = mapped_column(BigInteger)
    due_at: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="OPEN")


class CommissionEntry(Scoped, Base):
    __tablename__ = "commission_entries"
    __table_args__ = scoped_constraints(
        tenant_fk("cycle_id", "billing_cycles"),
        tenant_fk("charge_id", "payment_charges"),
        UniqueConstraint("tenant_id", "entry_key"),
        Index("ix_commission_cycle_currency", "cycle_id", "currency"),
    )
    cycle_id: Mapped[str | None] = mapped_column(String(36))
    charge_id: Mapped[str] = mapped_column(String(36))
    entry_key: Mapped[str] = mapped_column(String(160))
    currency: Mapped[str] = mapped_column(String(8))
    gross_minor: Mapped[int] = mapped_column(BigInteger)
    commission_bps: Mapped[int] = mapped_column()
    usd_rate: Mapped[str | None] = mapped_column(String(60))
    rate_source: Mapped[str] = mapped_column(String(100), default="")
    entry_type: Mapped[str] = mapped_column(String(20), default="SALE")


class PlatformInvoice(Scoped, Base):
    __tablename__ = "platform_invoices"
    __table_args__ = scoped_constraints(
        tenant_fk("cycle_id", "billing_cycles"),
        UniqueConstraint("cycle_id"),
        Index("ix_platform_invoice_due", "status", "due_at"),
    )
    cycle_id: Mapped[str] = mapped_column(String(36))
    number: Mapped[str] = mapped_column(String(60), unique=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    fixed_minor: Mapped[int] = mapped_column(BigInteger)
    commission_minor: Mapped[int | None] = mapped_column(BigInteger)
    adjustment_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    paid_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    due_at: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="PAYMENT_PENDING")


class PlatformSettlement(Scoped, Base):
    __tablename__ = "platform_settlements"
    __table_args__ = scoped_constraints(
        tenant_fk("invoice_id", "platform_invoices"), UniqueConstraint("reference_hash")
    )
    invoice_id: Mapped[str] = mapped_column(String(36), index=True)
    method: Mapped[str] = mapped_column(String(24))
    reference_hash: Mapped[str] = mapped_column(String(64))
    reference: Mapped[str] = mapped_column(String(240))
    amount_usd_minor: Mapped[int] = mapped_column(BigInteger)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    receipt_ciphertext: Mapped[dict | None] = mapped_column(JSON, deferred=True)
    media_type: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    submitted_by: Mapped[str] = mapped_column(String(36))
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str] = mapped_column(String(500), default="")


class InvoiceAdjustment(Scoped, Base):
    __tablename__ = "invoice_adjustments"
    __table_args__ = scoped_constraints(
        tenant_fk("invoice_id", "platform_invoices"), UniqueConstraint("tenant_id", "operation_key")
    )
    invoice_id: Mapped[str] = mapped_column(String(36), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(500))
    actor_id: Mapped[str] = mapped_column(String(64))
    operation_key: Mapped[str] = mapped_column(String(160))


class Report(Scoped, Base):
    __tablename__ = "reports"
    __table_args__ = scoped_constraints(tenant_fk("bot_id", "managed_bots"))
    bot_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    starts_at: Mapped[int] = mapped_column(BigInteger)
    ends_at: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    content_ciphertext: Mapped[dict | None] = mapped_column(JSON, deferred=True)
    expires_at: Mapped[int] = mapped_column(BigInteger)
