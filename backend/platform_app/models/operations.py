from sqlalchemy import String, BigInteger, JSON, Boolean, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, Record, Scoped, scoped_constraints


class Event(Scoped, Base):
    __tablename__ = "events"
    __table_args__ = scoped_constraints(UniqueConstraint("tenant_id", "dedup_key"))
    bot_id: Mapped[str | None] = mapped_column(String(36), index=True)
    contact_id: Mapped[str | None] = mapped_column(String(36))
    type: Mapped[str] = mapped_column(String(50), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(180))


class AuditLog(Record, Base):
    __tablename__ = "audit_logs"
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class TelegramUpdate(Record, Base):
    __tablename__ = "telegram_updates"
    __table_args__ = (UniqueConstraint("bot_key", "update_id"),)
    bot_key: Mapped[str] = mapped_column(String(36))
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    update_id: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")


class ProviderEvent(Record, Base):
    __tablename__ = "provider_events"
    __table_args__ = (UniqueConstraint("provider", "account_key", "external_id"),)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    account_key: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str] = mapped_column(String(255))
    payload_hash: Mapped[str] = mapped_column(String(64))


class Job(Record, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_job_due", "status", "run_at", "tenant_id"),)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    bot_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    run_at: Mapped[int] = mapped_column(BigInteger)
    lease_until: Mapped[int | None] = mapped_column(BigInteger)
    lease_owner: Mapped[str | None] = mapped_column(String(36))
    attempts: Mapped[int] = mapped_column(default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(80))


class SaaSPlan(Record, Base):
    __tablename__ = "saas_plans"
    name: Mapped[str] = mapped_column(String(40), unique=True)
    limits: Mapped[dict] = mapped_column(JSON, default=dict)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    prices: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SaaSSubscription(Scoped, Base):
    __tablename__ = "saas_subscriptions"
    __table_args__ = scoped_constraints(UniqueConstraint("tenant_id"))
    plan_id: Mapped[str] = mapped_column(ForeignKey("saas_plans.id"))
    kind: Mapped[str] = mapped_column(String(30), default="SAAS_SUBSCRIPTION")
    status: Mapped[str] = mapped_column(String(20), default="TRIAL")
    trial_ends_at: Mapped[int] = mapped_column(BigInteger)
    current_period_end: Mapped[int] = mapped_column(BigInteger)


class SaaSInvoice(Scoped, Base):
    __tablename__ = "saas_invoices"
    invoice_payload: Mapped[str] = mapped_column(String(128), unique=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("saas_plans.id"))
    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    amount_xtr: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    checkout_url: Mapped[str | None] = mapped_column(String(1024))


class SaaSCharge(Scoped, Base):
    __tablename__ = "saas_charges"
    charge_id: Mapped[str] = mapped_column(String(255), unique=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("saas_invoices.id"))
    amount_xtr: Mapped[int] = mapped_column(BigInteger)
    period_end: Mapped[int] = mapped_column(BigInteger)


class FeatureFlag(Scoped, Base):
    __tablename__ = "feature_flags"
    __table_args__ = scoped_constraints(UniqueConstraint("tenant_id", "key"))
    key: Mapped[str] = mapped_column(String(60))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class UsageCounter(Scoped, Base):
    __tablename__ = "usage_counters"
    __table_args__ = scoped_constraints(UniqueConstraint("tenant_id", "key", "period"))
    key: Mapped[str] = mapped_column(String(60))
    period: Mapped[str] = mapped_column(String(20))
    value: Mapped[int] = mapped_column(BigInteger, default=0)


class PlatformSupportTicket(Record, Base):
    __tablename__ = "platform_support_tickets"
    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id"))
    subject: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(String(3000))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
