from sqlalchemy import String, BigInteger, JSON, Boolean, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, Scoped, scoped_constraints, tenant_fk


class Contact(Scoped, Base):
    __tablename__ = "contacts"
    __table_args__ = scoped_constraints(
        tenant_fk("bot_id", "managed_bots"),
        UniqueConstraint("bot_id", "telegram_user_id"),
        Index("ix_contact_bot_page", "bot_id", "id"),
        Index("ix_contact_bot_created", "bot_id", "created_at"),
    )
    bot_id: Mapped[str] = mapped_column(String(36), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128))
    stage: Mapped[str] = mapped_column(String(30), default="LEAD", index=True)
    source: Mapped[str | None] = mapped_column(String(64))
    campaign: Mapped[str | None] = mapped_column(String(64))
    referrer: Mapped[str | None] = mapped_column(String(36))
    last_seen_at: Mapped[int] = mapped_column(BigInteger)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    locale: Mapped[str] = mapped_column(String(8), default="es")


class Conversation(Scoped, Base):
    __tablename__ = "conversations"
    __table_args__ = scoped_constraints(
        tenant_fk("bot_id", "managed_bots"),
        tenant_fk("contact_id", "contacts"),
        UniqueConstraint("contact_id"),
    )
    bot_id: Mapped[str] = mapped_column(String(36))
    contact_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")


class Message(Scoped, Base):
    __tablename__ = "messages"
    __table_args__ = scoped_constraints(tenant_fk("conversation_id", "conversations"))
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    admin_id: Mapped[str | None] = mapped_column(String(36))
    direction: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(String(4096))
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")


class InternalNote(Scoped, Base):
    __tablename__ = "internal_notes"
    __table_args__ = scoped_constraints(tenant_fk("contact_id", "contacts"))
    contact_id: Mapped[str] = mapped_column(String(36))
    author_id: Mapped[str] = mapped_column(String(36))
    text: Mapped[str] = mapped_column(String(2000))


class Tag(Scoped, Base):
    __tablename__ = "tags"
    __table_args__ = scoped_constraints(UniqueConstraint("tenant_id", "name"))
    name: Mapped[str] = mapped_column(String(40))


class ContactTag(Scoped, Base):
    __tablename__ = "contact_tags"
    __table_args__ = scoped_constraints(
        tenant_fk("contact_id", "contacts"),
        tenant_fk("tag_id", "tags"),
        UniqueConstraint("contact_id", "tag_id"),
    )
    contact_id: Mapped[str] = mapped_column(String(36))
    tag_id: Mapped[str] = mapped_column(String(36))


class Campaign(Scoped, Base):
    __tablename__ = "campaigns"
    __table_args__ = scoped_constraints(tenant_fk("bot_id", "managed_bots"))
    bot_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(String(4096))
    segment: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    scheduled_at: Mapped[int | None] = mapped_column(BigInteger)
    cursor: Mapped[str | None] = mapped_column(String(36))
    media: Mapped[dict] = mapped_column(JSON, default=dict)
    buttons: Mapped[list] = mapped_column(JSON, default=list)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    audience_count: Mapped[int] = mapped_column(default=0)


class CampaignRecipient(Scoped, Base):
    __tablename__ = "campaign_recipients"
    __table_args__ = scoped_constraints(
        tenant_fk("campaign_id", "campaigns"),
        tenant_fk("contact_id", "contacts"),
        UniqueConstraint("campaign_id", "contact_id"),
    )
    campaign_id: Mapped[str] = mapped_column(String(36), index=True)
    contact_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")


class AutomationRule(Scoped, Base):
    __tablename__ = "automation_rules"
    __table_args__ = scoped_constraints(tenant_fk("bot_id", "managed_bots"))
    bot_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(100))
    trigger: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(40))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    delay_seconds: Mapped[int] = mapped_column(default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AutomationExecution(Scoped, Base):
    __tablename__ = "automation_executions"
    __table_args__ = scoped_constraints(
        tenant_fk("rule_id", "automation_rules"),
        tenant_fk("event_id", "events"),
        UniqueConstraint("rule_id", "event_id"),
    )
    rule_id: Mapped[str] = mapped_column(String(36))
    event_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")


class CRMTask(Scoped, Base):
    __tablename__ = "crm_tasks"
    __table_args__ = scoped_constraints(tenant_fk("contact_id", "contacts"))
    contact_id: Mapped[str] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")


class Coupon(Scoped, Base):
    __tablename__ = "coupons"
    __table_args__ = scoped_constraints(UniqueConstraint("tenant_id", "code"))
    code: Mapped[str] = mapped_column(String(32))
    percent_off: Mapped[int] = mapped_column(default=0)
    max_redemptions: Mapped[int] = mapped_column(default=100)
    expires_at: Mapped[int] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CouponRedemption(Scoped, Base):
    __tablename__ = "coupon_redemptions"
    __table_args__ = scoped_constraints(
        tenant_fk("coupon_id", "coupons"),
        tenant_fk("contact_id", "contacts"),
        tenant_fk("payment_id", "payments"),
        UniqueConstraint("coupon_id", "contact_id"),
    )
    coupon_id: Mapped[str] = mapped_column(String(36))
    contact_id: Mapped[str] = mapped_column(String(36))
    payment_id: Mapped[str] = mapped_column(String(36))


class Referral(Scoped, Base):
    __tablename__ = "referrals"
    __table_args__ = scoped_constraints(
        tenant_fk("referrer_id", "contacts"),
        tenant_fk("referred_id", "contacts"),
        UniqueConstraint("referred_id"),
    )
    referrer_id: Mapped[str] = mapped_column(String(36))
    referred_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    reward_units: Mapped[int] = mapped_column(default=0)


class AttributionLink(Scoped, Base):
    __tablename__ = "attribution_links"
    __table_args__ = scoped_constraints(
        tenant_fk("bot_id", "managed_bots"), tenant_fk("referrer_id", "contacts")
    )
    bot_id: Mapped[str] = mapped_column(String(36))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    source: Mapped[str] = mapped_column(String(64))
    campaign: Mapped[str | None] = mapped_column(String(64))
    referrer_id: Mapped[str | None] = mapped_column(String(36))
