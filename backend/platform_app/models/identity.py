from sqlalchemy import String, BigInteger, JSON, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, Record, Scoped, scoped_constraints, tenant_fk


class PlatformUser(Record, Base):
    __tablename__ = "platform_users"
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    first_name: Mapped[str] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(8), default="es")
    trial_used_at: Mapped[int | None] = mapped_column(BigInteger)


class Tenant(Record, Base):
    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(100))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id"))
    status: Mapped[str] = mapped_column(String(30), default="TRIAL")
    suspended_at: Mapped[int | None] = mapped_column(BigInteger)
    admin_suspended_at: Mapped[int | None] = mapped_column(BigInteger)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger)


class TenantMember(Scoped, Base):
    __tablename__ = "tenant_members"
    __table_args__ = scoped_constraints(UniqueConstraint("tenant_id", "user_id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="OWNER")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuthSession(Record, Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("platform_users.id"))
    bot_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(10))
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)


class Onboarding(Scoped, Base):
    __tablename__ = "onboarding"
    __table_args__ = scoped_constraints(UniqueConstraint("tenant_id", "user_id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("platform_users.id"))
    step: Mapped[int] = mapped_column(default=1)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)


class BotCreationRequest(Scoped, Base):
    __tablename__ = "bot_creation_requests"
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    request_id: Mapped[int] = mapped_column(unique=True)
    expires_at: Mapped[int] = mapped_column(BigInteger)
    consumed_bot_id: Mapped[str | None] = mapped_column(String(36))


class ManagedBot(Scoped, Base):
    __tablename__ = "managed_bots"
    telegram_bot_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    owner_telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    public_id: Mapped[str] = mapped_column(String(36), unique=True)
    username: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="PROVISIONING")
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    config_version: Mapped[int] = mapped_column(default=1)
    last_update_at: Mapped[int | None] = mapped_column(BigInteger)
    health: Mapped[dict] = mapped_column(JSON, default=dict)
    last_error_code: Mapped[str | None] = mapped_column(String(60))
    connection_kind: Mapped[str] = mapped_column(String(20), default="MANAGED")
    disconnected_at: Mapped[int | None] = mapped_column(BigInteger)


class BotSecret(Scoped, Base):
    __tablename__ = "bot_secrets"
    __table_args__ = scoped_constraints(tenant_fk("bot_id", "managed_bots"), UniqueConstraint("bot_id"))
    bot_id: Mapped[str] = mapped_column(String(36))
    token_ciphertext: Mapped[dict] = mapped_column(JSON)
    webhook_ciphertext: Mapped[dict] = mapped_column(JSON)
    webhook_secret_hash: Mapped[str] = mapped_column(String(64))
    token_version: Mapped[int] = mapped_column(default=1)
    token_last_rotated_at: Mapped[int] = mapped_column(BigInteger)


class BotSettings(Scoped, Base):
    __tablename__ = "bot_settings"
    __table_args__ = scoped_constraints(tenant_fk("bot_id", "managed_bots"), UniqueConstraint("bot_id"))
    bot_id: Mapped[str] = mapped_column(String(36))
    description: Mapped[str] = mapped_column(String(512), default="")
    short_description: Mapped[str] = mapped_column(String(120), default="")
    menu_text: Mapped[str] = mapped_column(String(32), default="Mi membresía")
    commands: Mapped[list] = mapped_column(JSON, default=list)
    branding: Mapped[dict] = mapped_column(JSON, default=dict)
    policies: Mapped[dict] = mapped_column(JSON, default=dict)
    template: Mapped[str] = mapped_column(String(40), default="creator_subscription")
    support_username: Mapped[str] = mapped_column(String(64), default="")
    remove_expired_members: Mapped[bool] = mapped_column(Boolean, default=True)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)


class BotText(Scoped, Base):
    __tablename__ = "bot_texts"
    __table_args__ = scoped_constraints(
        tenant_fk("bot_id", "managed_bots"), UniqueConstraint("bot_id", "key", "locale")
    )
    bot_id: Mapped[str] = mapped_column(String(36))
    key: Mapped[str] = mapped_column(String(40))
    locale: Mapped[str] = mapped_column(String(8), default="es")
    value: Mapped[str] = mapped_column(String(4096))
