from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from ..services.crm import STAGES
from ..services.growth import ACTIONS, TRIGGERS
from ..services.texts import validate_text


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    init_data: str = Field(max_length=16384)


class TenantCreate(Input):
    name: str = Field(min_length=2, max_length=100)


class BotCreate(Input):
    name: str = Field(min_length=1, max_length=64)
    username: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{3,28}[Bb][Oo][Tt]$")


class WizardSave(Input):
    step: int = Field(ge=1, le=9)
    # Only nonsecret preferences; real business entities use their own validated routes.
    bot_id: str | None = None
    template: str = "creator_subscription"


class Command(Input):
    command: str = Field(pattern=r"^[a-z0-9_]{1,32}$")
    description: str = Field(min_length=1, max_length=256)


class BotConfig(Input):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(max_length=512, default="")
    short_description: str = Field(max_length=120, default="")
    menu_text: str = Field(min_length=1, max_length=32, default="Mi membresía")
    commands: list[Command] = Field(max_length=100, default_factory=list)
    support_username: str = Field(pattern=r"^@?[A-Za-z0-9_]{0,64}$", default="")
    brand_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$", default="#2864ef")
    terms: str = Field(max_length=5000, default="")
    privacy: str = Field(max_length=5000, default="")
    refund: str = Field(max_length=5000, default="")
    remove_expired_members: bool = True


class TextSave(Input):
    value: str = Field(max_length=4096)

    @field_validator("value")
    @classmethod
    def template_valid(cls, v):
        validate_text(v)
        return v


class Price(Input):
    provider: Literal["BANK_TRANSFER", "CRYPTO_MANUAL", "TELEGRAM_STARS", "EXTERNAL_HOSTED_PROVIDER"]
    currency: Literal["MXN", "USD", "XTR"]
    amount_minor: StrictInt = Field(gt=0, le=1_000_000_000_000)


class PlanCreate(Input):
    bot_id: str
    channel_id: str | None = None
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=1000, default="")
    benefits: list[str] = Field(max_length=20, default_factory=list)
    duration_days: int = Field(ge=1, le=3650, default=30)
    recurring: bool = False
    sort_order: int = 0
    active: bool = True
    # This platform sells subscriptions: creators cannot relabel digital goods to bypass Stars.
    prices: list[Price] = Field(min_length=1, max_length=6)


class ProviderSave(Input):
    enabled: bool
    bank_name: str = Field(max_length=100, default="")
    account_holder: str = Field(max_length=200, default="")
    account: str = Field(max_length=64, default="")
    clabe: str = Field(pattern=r"^(|[0-9]{18})$", default="")
    currency: Literal["MXN", "USD"] = "MXN"
    instructions: str = Field(max_length=1000, default="")


class Checkout(Input):
    plan_id: str
    idempotency_key: str = Field(min_length=8, max_length=100)
    coupon_code: str | None = Field(max_length=32, default=None)


class BankPayment(Input):
    bot_id: str
    contact_id: str
    plan_id: str
    currency: Literal["MXN", "USD"] = "MXN"
    idempotency_key: str = Field(min_length=8, max_length=100)
    off_platform_order_reference: str = Field(min_length=5, max_length=100)


class Review(Input):
    decision: Literal["APPROVE", "REJECT", "REQUEST_NEW", "SUSPICIOUS"]
    note: str = Field(max_length=500, default="")
    accept_duplicate: bool = False


class MessageSend(Input):
    text: str = Field(min_length=1, max_length=4096)
    idempotency_key: str = Field(min_length=8, max_length=100)


class Note(Input):
    text: str = Field(min_length=1, max_length=2000)


class ContactUpdate(Input):
    stage: str
    opted_out: bool = False

    @field_validator("stage")
    @classmethod
    def valid_stage(cls, v):
        if v not in STAGES:
            raise ValueError("Etapa no válida")
        return v


class MemberCreate(Input):
    telegram_user_id: StrictInt = Field(gt=0)
    role: Literal["SUPERVISOR", "PAYMENTS", "SALES", "SUPPORT", "READ_ONLY"]


class CampaignCreate(Input):
    bot_id: str
    name: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=4096)
    stage: str | None = None
    source: str | None = Field(max_length=64, default=None)


class CampaignAction(Input):
    action: Literal["START", "PAUSE"]
    scheduled_at: int | None = None


class AutomationCreate(Input):
    bot_id: str
    name: str = Field(min_length=1, max_length=100)
    trigger: str
    action: str
    text: str = Field(max_length=4096, default="")
    stage: str | None = None
    tag: str = Field(max_length=40, default="")
    title: str = Field(max_length=200, default="")
    delay_seconds: int = Field(ge=0, le=2592000, default=0)
    active: bool = True

    @field_validator("trigger")
    @classmethod
    def trigger_valid(cls, v):
        if v not in set(TRIGGERS.values()):
            raise ValueError("Trigger no válido")
        return v

    @field_validator("action")
    @classmethod
    def action_valid(cls, v):
        if v not in ACTIONS:
            raise ValueError("Acción no válida")
        return v


class CouponCreate(Input):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{3,32}$")
    percent_off: int = Field(ge=1, le=99)
    max_redemptions: int = Field(ge=1, le=100000)
    expires_at: int


class LinkCreate(Input):
    bot_id: str
    source: str = Field(min_length=1, max_length=64)
    campaign: str | None = Field(max_length=64, default=None)
    referrer_id: str | None = None


class NativeSubscription(Input):
    price_xtr: int = Field(ge=1, le=10000)


class CancelRenewal(Input):
    canceled: bool = True


class TicketCreate(Input):
    subject: str = Field(min_length=3, max_length=120)
    text: str = Field(min_length=5, max_length=3000)


class OwnerAction(Input):
    action: Literal["SUSPEND", "REACTIVATE"]
    reason: str = Field(min_length=5, max_length=500)


class SaaSPlanUpdate(Input):
    amount_xtr: int = Field(ge=1, le=10000)
    bots: int = Field(ge=1, le=1000)
    admins: int = Field(ge=1, le=1000)
    active_contacts: int = Field(ge=1, le=10000000)
    campaigns_month: int = Field(ge=0, le=10000)


class FeatureUpdate(Input):
    enabled: bool


class AccessSettings(Input):
    is_access_restricted: bool
    added_user_ids: list[StrictInt] = Field(max_length=10, default_factory=list)
