"""Per-bot payment credentials. Only the domain service can decrypt them."""

import json
import re
from sqlalchemy import select
from .. import models as m
from ..errors import DomainError
from ..security import random_secret
from .common import audit

PROVIDERS = {
    "TELEGRAM_STARS": "⭐ Telegram Stars",
    "BANK_TRANSFER": "🏦 Transferencia",
    "STRIPE": "Stripe",
    "PAYPAL": "PayPal Business",
}
PUBLIC_FIELDS = {
    "TELEGRAM_STARS": set(),
    "BANK_TRANSFER": {"bank", "holder", "account", "currency", "instructions", "additional", "qr_file_id"},
    "STRIPE": set(),
    "PAYPAL": {"environment", "client_id", "webhook_id"},
}
SECRET_FIELDS = {
    "STRIPE": {"secret_key", "webhook_secret"},
    "PAYPAL": {"client_secret"},
    "TELEGRAM_STARS": set(),
    "BANK_TRANSFER": set(),
}


def get(db, bot, provider, create=False):
    if provider not in PROVIDERS:
        raise DomainError("INVALID_PROVIDER", "Proveedor no válido.")
    row = db.scalar(
        select(m.BotPaymentMethod).where(
            m.BotPaymentMethod.tenant_id == bot.tenant_id,
            m.BotPaymentMethod.bot_id == bot.id,
            m.BotPaymentMethod.provider == provider,
        )
    )
    if not row and create:
        row = m.BotPaymentMethod(
            id=m.uid(),
            tenant_id=bot.tenant_id,
            bot_id=bot.id,
            provider=provider,
            enabled=False,
            public_config={},
            webhook_key=random_secret(),
        )
        db.add(row)
        db.flush()
    return row


def secrets(runtime, row):
    return (
        json.loads(
            runtime.vault.decrypt(
                row.secrets_ciphertext, f"{row.tenant_id}:{row.bot_id}:{row.provider}:payment-method"
            )
        )
        if row.secrets_ciphertext
        else {}
    )


def public_config(runtime, row):
    config = {key: value for key, value in row.public_config.items() if value is not None}
    legacy = config.pop("_legacy_provider_id", None)
    if legacy and row.provider == "BANK_TRANSFER" and row.secrets_ciphertext:
        values = json.loads(
            runtime.vault.decrypt(row.secrets_ciphertext, f"{row.tenant_id}:{legacy}:provider")
        )
        config = {
            "bank": values.get("bank_name", ""),
            "holder": values.get("account_holder", ""),
            "account": values.get("account") or values.get("clabe", ""),
            "currency": values.get("currency", "USD"),
            "instructions": values.get("instructions", ""),
            **config,
        }
    return config


def update(db, runtime, bot, provider, actor, field, value):
    row = get(db, bot, provider, True)
    if field not in PUBLIC_FIELDS[provider] | SECRET_FIELDS[provider]:
        raise DomainError("INVALID_FIELD", "Campo no disponible.")
    value = value.strip()
    if not value or len(value) > 1800:
        raise DomainError("INVALID_VALUE", "Revisa el valor del campo.")
    if field == "secret_key" and not re.fullmatch(r"(?:sk|rk)_(?:test|live)_[A-Za-z0-9]{12,200}", value):
        raise DomainError("INVALID_KEY", "Usa una clave secreta de Stripe válida.")
    if field == "webhook_secret" and not re.fullmatch(r"whsec_[A-Za-z0-9]{12,200}", value):
        raise DomainError("INVALID_KEY", "Usa el secreto de firma del webhook de Stripe.")
    if field == "environment" and value not in {"sandbox", "live"}:
        raise DomainError("INVALID_ENVIRONMENT", "Usa sandbox o live.")
    if field == "currency":
        from .business import amount_minor

        value = value.upper()
        amount_minor("1", value)
    if field in SECRET_FIELDS[provider]:
        config = {**secrets(runtime, row), field: value}
        row.secrets_ciphertext = runtime.vault.encrypt(
            json.dumps(config), f"{row.tenant_id}:{row.bot_id}:{provider}:payment-method"
        )
    else:
        if row.public_config.get("_legacy_provider_id"):
            row.public_config = public_config(runtime, row)
            row.secrets_ciphertext = None
        row.public_config = {**row.public_config, field: value}
    row.enabled = False if provider in {"STRIPE", "PAYPAL"} else row.enabled
    audit(
        db,
        bot.tenant_id,
        actor,
        "PAYMENT_METHOD_CONFIGURED",
        row.id,
        {"bot_id": bot.id, "provider": provider, "field": field, "secret": field in SECRET_FIELDS[provider]},
    )
    return row


def enable(db, runtime, bot, row, actor):
    config = public_config(runtime, row)
    private = secrets(runtime, row) if row.provider in {"STRIPE", "PAYPAL"} else {}
    required = {
        "BANK_TRANSFER": {"bank", "holder", "account", "currency", "instructions"},
        "STRIPE": {"secret_key", "webhook_secret"},
        "PAYPAL": {"client_id", "client_secret", "webhook_id", "environment"},
        "TELEGRAM_STARS": set(),
    }[row.provider]
    missing = required - {key for key, value in {**config, **private}.items() if value}
    if missing:
        raise DomainError("PAYMENT_CONFIG_INCOMPLETE", "Faltan campos: " + ", ".join(sorted(missing)))
    if row.provider in {"STRIPE", "PAYPAL"} and not runtime.settings.payment_webhooks_enabled:
        raise DomainError(
            "WEBHOOK_SERVICE_REQUIRED",
            "Credenciales guardadas. Para activar este método la plataforma debe habilitar la recepción pública de webhooks.",
            409,
        )
    row.enabled = True
    audit(
        db,
        bot.tenant_id,
        actor,
        "PAYMENT_METHOD_ENABLED",
        row.id,
        {"bot_id": bot.id, "provider": row.provider},
    )
    return row
