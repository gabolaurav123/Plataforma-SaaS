from sqlalchemy import String, BigInteger, JSON, Boolean, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, Scoped, scoped_constraints, tenant_fk


class Channel(Scoped, Base):
    __tablename__ = "channels"
    __table_args__ = scoped_constraints(
        tenant_fk("bot_id", "managed_bots"), UniqueConstraint("bot_id", "telegram_chat_id")
    )
    bot_id: Mapped[str] = mapped_column(String(36))
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(20), default="channel")
    status: Mapped[str] = mapped_column(String(30), default="PERMISSIONS_MISSING")
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    connected_at: Mapped[int | None] = mapped_column(BigInteger)
    access_mode: Mapped[str] = mapped_column(String(30), default="PLATFORM")
    native_invite_link: Mapped[str | None] = mapped_column(String(512))


class Plan(Scoped, Base):
    __tablename__ = "plans"
    __table_args__ = scoped_constraints(
        tenant_fk("bot_id", "managed_bots"),
        tenant_fk("channel_id", "channels"),
        CheckConstraint("duration_days > 0"),
    )
    bot_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str | None] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(1000), default="")
    benefits: Mapped[list] = mapped_column(JSON, default=list)
    duration_days: Mapped[int] = mapped_column(default=30)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(default=0)
    product_kind: Mapped[str] = mapped_column(String(20), default="DIGITAL")


class PlanPrice(Scoped, Base):
    __tablename__ = "plan_prices"
    __table_args__ = scoped_constraints(
        tenant_fk("plan_id", "plans"),
        UniqueConstraint("plan_id", "provider", "currency"),
        CheckConstraint("amount_minor > 0"),
    )
    plan_id: Mapped[str] = mapped_column(String(36))
    provider: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(8))
    amount_minor: Mapped[int] = mapped_column(BigInteger)


class ProviderConfig(Scoped, Base):
    __tablename__ = "payment_provider_configs"
    __table_args__ = scoped_constraints(UniqueConstraint("tenant_id", "provider"))
    provider: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_for_activity: Mapped[bool] = mapped_column(Boolean, default=False)
    public_config: Mapped[dict] = mapped_column(JSON, default=dict)
    secrets_ciphertext: Mapped[dict | None] = mapped_column(JSON)


class Payment(Scoped, Base):
    __tablename__ = "payments"
    __table_args__ = scoped_constraints(
        tenant_fk("bot_id", "managed_bots"),
        tenant_fk("contact_id", "contacts"),
        tenant_fk("plan_id", "plans"),
        UniqueConstraint("tenant_id", "idempotency_key"),
        CheckConstraint("amount_minor > 0"),
    )
    bot_id: Mapped[str] = mapped_column(String(36))
    contact_id: Mapped[str] = mapped_column(String(36), index=True)
    plan_id: Mapped[str] = mapped_column(String(36))
    provider: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(8))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    duration_days: Mapped[int] = mapped_column(default=30)
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    invoice_payload: Mapped[str] = mapped_column(String(128), unique=True)
    checkout_url: Mapped[str | None] = mapped_column(String(1024))
    confirmed_at: Mapped[int | None] = mapped_column(BigInteger)


class PaymentAttempt(Scoped, Base):
    __tablename__ = "payment_attempts"
    __table_args__ = scoped_constraints(tenant_fk("payment_id", "payments"))
    payment_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(30))
    code: Mapped[str] = mapped_column(String(80))


class PaymentCharge(Scoped, Base):
    __tablename__ = "payment_charges"
    __table_args__ = scoped_constraints(
        tenant_fk("payment_id", "payments"),
        tenant_fk("bot_id", "managed_bots"),
        UniqueConstraint("bot_id", "provider", "charge_id"),
    )
    payment_id: Mapped[str] = mapped_column(String(36))
    bot_id: Mapped[str] = mapped_column(String(36))
    provider: Mapped[str] = mapped_column(String(40))
    charge_id: Mapped[str] = mapped_column(String(255))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8))
    period_end: Mapped[int | None] = mapped_column(BigInteger)
    refunded_at: Mapped[int | None] = mapped_column(BigInteger)


class BankReceipt(Scoped, Base):
    __tablename__ = "bank_receipts"
    __table_args__ = scoped_constraints(tenant_fk("payment_id", "payments"))
    payment_id: Mapped[str] = mapped_column(String(36), index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(16))
    storage_key: Mapped[str] = mapped_column(String(120))
    media_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    review_note: Mapped[str] = mapped_column(String(500), default="")


class Subscription(Scoped, Base):
    __tablename__ = "subscriptions"
    __table_args__ = scoped_constraints(
        tenant_fk("bot_id", "managed_bots"),
        tenant_fk("contact_id", "contacts"),
        tenant_fk("plan_id", "plans"),
        tenant_fk("payment_id", "payments"),
        UniqueConstraint("payment_id"),
    )
    bot_id: Mapped[str] = mapped_column(String(36))
    contact_id: Mapped[str] = mapped_column(String(36), index=True)
    plan_id: Mapped[str] = mapped_column(String(36))
    payment_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(30), default="CUSTOMER_SUBSCRIPTION")
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    starts_at: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False)
    initial_charge_id: Mapped[str | None] = mapped_column(String(255))
    renewal_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class ChannelInvite(Scoped, Base):
    __tablename__ = "channel_invites"
    __table_args__ = scoped_constraints(
        tenant_fk("channel_id", "channels"),
        tenant_fk("contact_id", "contacts"),
        tenant_fk("subscription_id", "subscriptions"),
    )
    channel_id: Mapped[str] = mapped_column(String(36))
    contact_id: Mapped[str] = mapped_column(String(36))
    subscription_id: Mapped[str] = mapped_column(String(36))
    invite_link: Mapped[str] = mapped_column(String(512), unique=True)
    expires_at: Mapped[int] = mapped_column(BigInteger)
    used_at: Mapped[int | None] = mapped_column(BigInteger)
    revoked_at: Mapped[int | None] = mapped_column(BigInteger)
