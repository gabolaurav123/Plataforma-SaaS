"""Plain-text, locale-aware templates. Legacy {{variables}} remain compatible."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from ..models import BotText, BotSettings, Plan, Payment, now
from ..errors import DomainError
from .i18n import locale as normalize_locale

TEXTS = {
    "WELCOME": (
        "Hola {name} 👋 Bienvenido a {bot_name}. Descubre nuestros planes.",
        "Hello {name} 👋 Welcome to {bot_name}. Explore our plans.",
        "Olá {name} 👋 Bem-vindo a {bot_name}. Conheça nossos planos.",
    ),
    "PRESENTATION": (
        "Consulta nuestros servicios y beneficios.",
        "Explore our services and benefits.",
        "Conheça nossos serviços e benefícios.",
    ),
    "PLAN_LIST": (
        "Elige el plan que mejor se adapte a ti.",
        "Choose the plan that suits you.",
        "Escolha o plano ideal para você.",
    ),
    "PLAN_SELECTED": (
        "Elegiste {plan}: {price} {currency}.",
        "You selected {plan}: {price} {currency}.",
        "Você escolheu {plan}: {price} {currency}.",
    ),
    "PAYMENT_METHOD": (
        "Completa el pago para activar tu suscripción.",
        "Complete payment to activate your subscription.",
        "Conclua o pagamento para ativar sua assinatura.",
    ),
    "BANK_DETAILS": (
        "Transfiere el importe exacto usando estos datos.",
        "Transfer the exact amount using these details.",
        "Transfira o valor exato usando estes dados.",
    ),
    "RECEIPT_REQUEST": (
        "Envía una foto o PDF de tu comprobante para revisión.",
        "Send a photo or PDF receipt for review.",
        "Envie uma foto ou PDF do comprovante para análise.",
    ),
    "RECEIPT_RECEIVED": (
        "Recibimos tu comprobante. Te avisaremos cuando termine la revisión.",
        "We received your receipt. We will notify you after review.",
        "Recebemos seu comprovante. Avisaremos após a análise.",
    ),
    "PAYMENT_APPROVED": (
        "✅ Pago aprobado. Tu suscripción está activa.",
        "✅ Payment approved. Your subscription is active.",
        "✅ Pagamento aprovado. Sua assinatura está ativa.",
    ),
    "PAYMENT_REJECTED": (
        "No pudimos aprobar el comprobante. Contacta con soporte.",
        "We could not approve the receipt. Please contact support.",
        "Não foi possível aprovar o comprovante. Entre em contato com o suporte.",
    ),
    "PURCHASE_COMPLETED": (
        "Gracias por tu compra de {plan}.",
        "Thank you for purchasing {plan}.",
        "Obrigado por adquirir {plan}.",
    ),
    "SUBSCRIPTION_ACTIVE": (
        "Tu plan {plan} está activo hasta {expiration_date}.",
        "Your {plan} plan is active until {expiration_date}.",
        "Seu plano {plan} está ativo até {expiration_date}.",
    ),
    "ACCESS_GRANTED": (
        "✅ Tu suscripción está activa. Solicita acceso a {channel} con tu enlace personal.",
        "✅ Your subscription is active. Request access to {channel} using your personal link.",
        "✅ Sua assinatura está ativa. Solicite acesso a {channel} com seu link pessoal.",
    ),
    "SUBSCRIPTION_EXPIRING": (
        "Tu plan {plan} vence en {days_remaining} días. Puedes renovarlo desde el menú.",
        "Your {plan} plan expires in {days_remaining} days. You can renew it from the menu.",
        "Seu plano {plan} vence em {days_remaining} dias. Renove pelo menu.",
    ),
    "SUBSCRIPTION_EXPIRED": (
        "Tu plan {plan} ha vencido. Puedes renovarlo desde el menú.",
        "Your {plan} plan has expired. You can renew it from the menu.",
        "Seu plano {plan} venceu. Renove pelo menu.",
    ),
    "RENEWAL": (
        "Gracias por renovar tu suscripción.",
        "Thank you for renewing your subscription.",
        "Obrigado por renovar sua assinatura.",
    ),
    "SUPPORT": (
        "Escribe tu consulta aquí. Nuestro equipo te responderá.",
        "Write your question here. Our team will reply.",
        "Escreva sua dúvida aqui. Nossa equipe responderá.",
    ),
    "ERROR": (
        "No pudimos completar la operación. Inténtalo de nuevo.",
        "We could not complete this operation. Please try again.",
        "Não foi possível concluir a operação. Tente novamente.",
    ),
}
DEFAULT_TEXTS = {key: values[0] for key, values in TEXTS.items()}
VARIABLES = {
    "name",
    "username",
    "plan",
    "price",
    "currency",
    "expiration_date",
    "days_remaining",
    "channel",
    "bot_name",
    "first_name",
    "plan_name",
    "support_username",
}
PATTERN = re.compile(r"{{\s*(\w+)\s*}}|(?<!{){\s*(\w+)\s*}(?!})")
TEMPLATES = {
    key: {"name": name, "welcome": DEFAULT_TEXTS["WELCOME"]}
    for key, name in [
        ("creator_subscription", "Creator Subscription"),
        ("private_community", "Private Community"),
        ("premium_channel", "Premium Channel"),
        ("membership_club", "Membership Club"),
    ]
}


def validate_text(value):
    names = {match[1] or match[2] for match in PATTERN.finditer(value)}
    if (
        names - VARIABLES
        or len(value) > 4096
        or "{" in PATTERN.sub("", value)
        or "}" in PATTERN.sub("", value)
    ):
        raise DomainError("INVALID_TEMPLATE", "El texto incluye variables desconocidas o es demasiado largo.")


def render(value, variables):
    variables = dict(variables)
    variables.setdefault("name", variables.get("first_name", ""))
    variables.setdefault("first_name", variables.get("name", ""))
    variables.setdefault("plan", variables.get("plan_name", ""))
    variables.setdefault("plan_name", variables.get("plan", ""))
    return PATTERN.sub(lambda match: str(variables.get(match[1] or match[2], "")), value)[:4096]


def default_text(key, language="es"):
    return TEXTS.get(key, TEXTS["ERROR"])[{"es": 0, "en": 1, "pt": 2}[normalize_locale(language)]]


def bot_text(session, bot, key, locale=None, **variables):
    config = session.scalar(select(BotSettings).where(BotSettings.bot_id == bot.id))
    language = normalize_locale(locale or (config.preferences.get("language") if config else "es"))
    value = session.scalar(
        select(BotText.value).where(
            BotText.tenant_id == bot.tenant_id,
            BotText.bot_id == bot.id,
            BotText.key == key,
            BotText.locale == language,
        )
    )
    variables.setdefault("bot_name", bot.name)
    variables.setdefault("support_username", config.support_username if config else "")
    return render(value if value is not None else default_text(key, language), variables)


def customer_variables(session, bot, contact, subscription=None, payment=None):
    from .business import money

    config = session.scalar(select(BotSettings).where(BotSettings.bot_id == bot.id))
    pref = config.preferences if config else {}
    values = {
        "name": contact.first_name,
        "username": "@" + contact.username if contact.username else str(contact.telegram_user_id),
        "bot_name": bot.name,
    }
    if subscription:
        plan = session.get(Plan, subscription.plan_id)
        payment = payment or (
            session.get(Payment, subscription.payment_id) if subscription.payment_id else None
        )
        fmt = {"DMY": "%d/%m/%Y %H:%M", "MDY": "%m/%d/%Y %H:%M", "YMD": "%Y-%m-%d %H:%M"}.get(
            pref.get("date_format"), "%Y-%m-%d %H:%M"
        )
        values.update(
            plan=plan.name,
            expiration_date=datetime.fromtimestamp(
                subscription.expires_at, ZoneInfo(pref.get("timezone", "UTC"))
            ).strftime(fmt),
            days_remaining=max(0, (subscription.expires_at - now() + 86399) // 86400),
        )
    if payment:
        values.update(
            plan=session.get(Plan, payment.plan_id).name,
            price=money(payment.amount_minor, payment.currency).rsplit(" ", 1)[0],
            currency=payment.currency,
        )
    return values
