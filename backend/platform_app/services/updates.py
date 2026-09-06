from sqlalchemy import select
from ..models import TenantMember, Tenant, Payment, Subscription, Contact, now
from ..errors import DomainError
from .common import send, emit
from .tenants import upsert_user, entitlement
from .crm import upsert_contact, incoming
from .texts import bot_text


class UpdateHandler:
    def __init__(self, runtime):
        self.r = runtime

    def master(self, session, update):
        if update.get("managed_bot"):
            self.r.manager.accept_managed_update(session, update["managed_bot"])
            return
        message = update.get("message", {})
        if message.get("managed_bot_created"):
            self.r.manager.accept_managed_update(
                session, message["managed_bot_created"], creator=message.get("from")
            )
            return
        if message.get("successful_payment"):
            self.r.billing.confirm(session, message["from"]["id"], message["successful_payment"])
            return
        if self.r.settings.deployment_mode == "telegram":
            from .console import handle
            return handle(self.r, session, update)
        if message.get("chat", {}).get("type") != "private" or not message.get("from"):
            return
        user = upsert_user(session, message["from"])
        text = message.get("text", "")
        if text.startswith("/start"):
            tenants = list(
                session.scalars(
                    select(Tenant)
                    .join(TenantMember, TenantMember.tenant_id == Tenant.id)
                    .where(TenantMember.user_id == user.id, TenantMember.active.is_(True))
                )
            )
            buttons = [
                [
                    {
                        "text": "🚀 Crear mi bot",
                        "web_app": {"url": self.r.settings.mini_app_url + "/?onboarding=1"},
                    }
                ],
                [{"text": "Ya tengo cuenta", "web_app": {"url": self.r.settings.mini_app_url}}],
                [
                    {
                        "text": "Cómo funciona",
                        "web_app": {"url": self.r.settings.mini_app_url + "/?section=support"},
                    }
                ],
            ]
            if tenants:
                buttons = [
                    [
                        {
                            "text": "📊 Abrir panel" if len(tenants) == 1 else "Seleccionar espacio",
                            "web_app": {"url": self.r.settings.mini_app_url},
                        }
                    ],
                    [
                        {
                            "text": "💳 Facturación",
                            "web_app": {"url": self.r.settings.mini_app_url + "/?section=billing"},
                        }
                    ],
                ]
            send(
                session,
                None,
                user.telegram_user_id,
                "🚀 Crea y administra tu propio sistema de suscripciones en Telegram.",
                f"master-start:{update['update_id']}",
                reply_markup={"inline_keyboard": buttons},
            )
        elif text.startswith(("/support", "/paysupport")):
            send(
                session,
                None,
                user.telegram_user_id,
                "Abre Ayuda en el panel para contactar al soporte de la plataforma.",
                f"master-help:{update['update_id']}",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": "Contactar soporte",
                                "web_app": {"url": self.r.settings.mini_app_url + "/?section=support"},
                            }
                        ]
                    ]
                },
            )

    def child(self, session, bot, update):
        bot.last_update_at = now()
        if bot.status == "OWNERSHIP_CHANGED":
            return
        if update.get("my_chat_member"):
            self.r.channels.connect_from_update(session, bot, update["my_chat_member"])
            return
        if update.get("chat_join_request"):
            self.r.channels.join_request(session, bot, update["chat_join_request"])
            return
        if update.get("subscription"):
            change = update["subscription"]
            payment = session.scalar(
                select(Payment).where(
                    Payment.bot_id == bot.id, Payment.invoice_payload == change["invoice_payload"]
                )
            )
            if payment:
                contact = session.get(Contact, payment.contact_id)
                sub = session.scalar(select(Subscription).where(Subscription.payment_id == payment.id))
                if sub and contact.telegram_user_id == change["user"]["id"]:
                    sub.renewal_status = {"canceled": "CANCELED", "active": "ACTIVE", "failed": "FAILED"}.get(
                        change["state"], "UNKNOWN"
                    )
                    sub.auto_renew = change["state"] == "active"
            return
        message = update.get("message", {})
        if message.get("successful_payment"):
            self.r.payments.confirm_stars(session, bot, message["from"]["id"], message["successful_payment"])
            return
        if message.get("refunded_payment"):
            self.r.payments.refunded_event(session, bot, message["refunded_payment"])
            return
        if self.r.settings.deployment_mode == "telegram":
            from .console import handle
            return handle(self.r, session, update, bot)
        if (
            message.get("chat", {}).get("type") != "private"
            or not message.get("from")
            or message["from"].get("is_bot")
        ):
            return
        user = message["from"]
        text = message.get("text", "")
        # Service paid updates remain processable while a tenant is suspended.
        try:
            entitlement(session, bot.tenant_id)
        except DomainError:
            return
        if not bot.published and user["id"] != bot.owner_telegram_user_id:
            send(
                session,
                bot,
                user["id"],
                "Este bot está en preparación. Vuelve pronto.",
                f"unpublished:{bot.id}:{update['update_id']}",
            )
            return
        code = text.split(maxsplit=1)[1] if text.startswith("/start ") else None
        contact = upsert_contact(session, bot, user, code)
        incoming(session, bot, contact, text or message.get("caption", "[Imagen]"), message["message_id"])
        if text.startswith("/stop"):
            contact.opted_out = True
            send(
                session,
                bot,
                user["id"],
                "Desactivaste los mensajes de campañas.",
                f"stop:{bot.id}:{update['update_id']}",
            )
        elif text.startswith(("/start", "/plans")):
            contact.opted_out = False
            emit(
                session,
                bot.tenant_id,
                "USER_STARTED",
                f"start:{bot.id}:{update['update_id']}",
                bot.id,
                contact.id,
            )
            send(
                session,
                bot,
                user["id"],
                bot_text(session, bot, "WELCOME", first_name=contact.first_name),
                f"welcome:{bot.id}:{update['update_id']}",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": "Ver planes y membresía",
                                "web_app": {"url": f"{self.r.settings.mini_app_url}/b/{bot.public_id}"},
                            }
                        ]
                    ]
                },
            )
        elif text.startswith(("/support", "/paysupport")):
            send(
                session,
                bot,
                user["id"],
                bot_text(session, bot, "SUPPORT"),
                f"support:{bot.id}:{update['update_id']}",
            )
        elif message.get("photo") or message.get("document"):
            pending = list(
                session.scalars(
                    select(Payment).where(
                        Payment.contact_id == contact.id,
                        Payment.bot_id == bot.id,
                        Payment.provider == "BANK_TRANSFER",
                        Payment.status.in_(["PENDING", "RECEIPT_SUBMITTED"]),
                    )
                )
            )
            if len(pending) == 1:
                file_id = (
                    message["photo"][-1]["file_id"]
                    if message.get("photo")
                    else message["document"]["file_id"]
                )
                data = self.r.clients.child(session, bot).download(file_id, self.r.settings.max_upload_bytes)
                self.r.receipts.submit(session, bot, pending[0], data)
                send(
                    session,
                    bot,
                    user["id"],
                    bot_text(session, bot, "RECEIPT_RECEIVED"),
                    f"receipt-received:{bot.id}:{update['update_id']}",
                )
            elif len(pending) > 1:
                send(
                    session,
                    bot,
                    user["id"],
                    "Tienes varios pagos pendientes. Abre Pagos en tu Mini App y selecciona el comprobante correspondiente.",
                    f"receipt-choice:{bot.id}:{update['update_id']}",
                )
