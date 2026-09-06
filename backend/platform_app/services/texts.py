import re
from sqlalchemy import select
from ..models import BotText
from ..errors import DomainError

DEFAULT_TEXTS = {
    "WELCOME": "Hola {{first_name}} 👋 Bienvenido a nuestra comunidad. Descubre los planes disponibles.",
    "PLAN_LIST": "Elige el plan que mejor se adapte a ti.",
    "PLAN_SELECTED": "Elegiste {{plan_name}}: {{price}} {{currency}}.",
    "PAYMENT_METHOD": "Completa tu pago para activar tu membresía.",
    "BANK_DETAILS": "Consulta los datos de transferencia de tu pedido autorizado.",
    "RECEIPT_REQUEST": "Envía una imagen de tu comprobante para revisión.",
    "RECEIPT_RECEIVED": "Recibimos tu comprobante. Te avisaremos cuando termine la revisión.",
    "PAYMENT_APPROVED": "✅ Pago aprobado. Tu membresía está activa.",
    "PAYMENT_REJECTED": "No pudimos aprobar el comprobante. Contacta con soporte.",
    "SUBSCRIPTION_ACTIVE": "Tu plan {{plan_name}} está activo hasta {{expiration_date}}.",
    "SUBSCRIPTION_EXPIRING": "Tu membresía vence en {{days_remaining}} días.",
    "SUBSCRIPTION_EXPIRED": "Tu membresía ha vencido. Puedes renovarla desde el menú.",
    "RENEWAL": "Gracias por renovar tu membresía.",
    "SUPPORT": "Escribe tu consulta aquí. Nuestro equipo te responderá.",
    "ERROR": "No pudimos completar la operación. Inténtalo de nuevo.",
}
VARIABLES = {
    "first_name",
    "plan_name",
    "price",
    "currency",
    "expiration_date",
    "days_remaining",
    "support_username",
}
TEMPLATES = {
    "creator_subscription": {"name": "Creator Subscription", "welcome": DEFAULT_TEXTS["WELCOME"]},
    "private_community": {
        "name": "Private Community",
        "welcome": "Hola {{first_name}} 👋 Encuentra tu lugar en nuestra comunidad privada.",
    },
    "premium_channel": {
        "name": "Premium Channel",
        "welcome": "Hola {{first_name}} 👋 Accede a nuestro canal premium desde aquí.",
    },
    "membership_club": {
        "name": "Membership Club",
        "welcome": "Bienvenido al club, {{first_name}}. Consulta tus beneficios y membresías.",
    },
}


def validate_text(value):
    invalid = set(re.findall(r"{{\s*(.*?)\s*}}", value)) - VARIABLES
    if invalid or len(value) > 4096:
        raise DomainError("INVALID_TEMPLATE", "El texto incluye variables desconocidas o es demasiado largo.")


def render(value, variables):
    # Plain text only: no HTML/Markdown parse mode sent to Telegram.
    return re.sub(r"{{\s*(\w+)\s*}}", lambda m: str(variables.get(m[1], "")), value)[:4096]


def bot_text(session, bot, key, **variables):
    value = session.scalar(
        select(BotText.value).where(
            BotText.tenant_id == bot.tenant_id,
            BotText.bot_id == bot.id,
            BotText.key == key,
            BotText.locale == "es",
        )
    )
    return render(value or DEFAULT_TEXTS.get(key, DEFAULT_TEXTS["ERROR"]), variables)
