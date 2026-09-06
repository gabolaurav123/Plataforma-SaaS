"""Customer checkout, membership and support inside Telegram."""

from sqlalchemy import select
from .. import models as m
from ..db import get_scoped
from ..errors import DomainError
from . import tenants, crm
from .common import emit, enqueue
from .texts import bot_text
from .console import date


def contact(ui, attribution_code=None):
    tenants.entitlement(ui.db, ui.bot.tenant_id)
    if ui.bot.status in {"OWNERSHIP_CHANGED", "SUSPENDED"}:
        raise DomainError("BOT_UNAVAILABLE", "Bot no disponible.")
    if not ui.bot.published and ui.actor["id"] != ui.bot.owner_telegram_user_id:
        raise DomainError("BOT_NOT_READY", "Este bot está en preparación. Vuelve pronto.")
    return crm.upsert_contact(ui.db, ui.bot, ui.actor, attribution_code)


def home(ui):
    person = contact(ui)
    ui.say(
        bot_text(ui.db, ui.bot, "WELCOME", first_name=person.first_name),
        [
            [ui.button("⭐ Ver planes", "plans")],
            [ui.button("🎟 Mi membresía", "memberships")],
            [ui.button("📜 Políticas", "policies")],
            [ui.button("💬 Soporte", "support")],
            [ui.button("🔕 Desactivar campañas", "stop")],
        ],
    )


def message(ui, message):
    text = message.get("text", "").strip()
    code = text.split(maxsplit=1)[1] if text.startswith("/start ") else None
    person = contact(ui, code)
    crm.incoming(ui.db, ui.bot, person, text or message.get("caption", "[Archivo]"), message["message_id"])
    if text.startswith(("/start", "/cancel")):
        ui.state().data = {}
        person.opted_out = False
        emit(
            ui.db,
            ui.bot.tenant_id,
            "USER_STARTED",
            f"start:{ui.bot.id}:{ui.update['update_id']}",
            ui.bot.id,
            person.id,
        )
        home(ui)
    elif text.startswith("/plans"):
        dispatch(ui, "plans", {})
    elif text.startswith("/membership"):
        dispatch(ui, "memberships", {})
    elif text.startswith("/stop"):
        dispatch(ui, "stop", {})
    elif text.startswith(("/support", "/paysupport")):
        dispatch(ui, "support", {})
    elif message.get("photo") or message.get("document"):
        pending = list(
            ui.db.scalars(
                select(m.Payment).where(
                    m.Payment.bot_id == ui.bot.id,
                    m.Payment.contact_id == person.id,
                    m.Payment.provider == "BANK_TRANSFER",
                    m.Payment.status.in_(["PENDING", "RECEIPT_SUBMITTED"]),
                )
            )
        )
        if len(pending) == 1:
            file_id = (
                message["photo"][-1]["file_id"] if message.get("photo") else message["document"]["file_id"]
            )
            data = ui.r.clients.child(ui.db, ui.bot).download(file_id, ui.r.settings.max_upload_bytes)
            ui.r.receipts.submit(ui.db, ui.bot, pending[0], data)
            ui.say(bot_text(ui.db, ui.bot, "RECEIPT_RECEIVED"))
        elif len(pending) > 1:
            ui.say(
                "Hay varios pagos externos pendientes. Contacta al equipo para identificar el comprobante."
            )
        else:
            ui.say("Mensaje recibido. Para soporte escribe también tu consulta en texto.")
    else:
        ui.say("Mensaje recibido. El equipo podrá responderte desde este bot.")


def dispatch(ui, action, d):
    person = contact(ui)
    bot, db = ui.bot, ui.db
    if action == "home":
        home(ui)
    elif action == "plans":
        query = select(m.Plan).where(
            m.Plan.bot_id == bot.id, m.Plan.tenant_id == bot.tenant_id, m.Plan.active.is_(True)
        )
        if d.get("after"):
            query = query.where(m.Plan.id > d["after"])
        plans = list(db.scalars(query.order_by(m.Plan.id).limit(9)))
        buttons = []
        for plan in plans[:8]:
            price = db.scalar(
                select(m.PlanPrice).where(m.PlanPrice.plan_id == plan.id, m.PlanPrice.currency == "XTR")
            )
            if price:
                buttons.append(
                    [
                        ui.button(
                            f"{plan.name}: {price.amount_minor} ⭐ / {plan.duration_days} días",
                            "plan",
                            id=plan.id,
                        )
                    ]
                )
        if len(plans) > 8:
            buttons.append([ui.button("Más planes →", "plans", after=plans[7].id)])
        ui.say(
            "Selecciona un plan para ver las condiciones."
            if buttons
            else "Todavía no hay planes disponibles.",
            buttons,
        )
    elif action == "plan":
        plan = get_scoped(db, m.Plan, d["id"], bot.tenant_id)
        if plan.bot_id != bot.id or not plan.active:
            raise DomainError("NOT_FOUND", "Plan no disponible.")
        price = db.scalar(
            select(m.PlanPrice).where(m.PlanPrice.plan_id == plan.id, m.PlanPrice.currency == "XTR")
        )
        ui.say(
            f"{plan.name}\n{plan.description}\n{price.amount_minor} Stars · {plan.duration_days} días\nRenovación: {'automática cada 30 días' if plan.recurring else 'manual'}\nLee las políticas antes de continuar.",
            [
                [ui.button("📜 Leer políticas", "policies")],
                [ui.button("Aceptar condiciones y continuar", "buy", id=plan.id)],
            ],
        )
    elif action == "buy":
        payment = ui.r.payments.create(
            db, bot, person, d["id"], "TELEGRAM_STARS", "XTR", f"native:{person.id}:{ui.update['update_id']}"
        )
        emit(db, bot.tenant_id, "PLAN_SELECTED", f"plan-selected:{payment.id}", bot.id, person.id)
        ui.say(
            "Revisa y confirma el pago en Telegram. La membresía se activará cuando Telegram confirme el cobro.",
            [[{"text": "Pagar con Stars", "url": payment.checkout_url}]],
        )
    elif action == "policies":
        config = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
        for key, label in [("terms", "Términos"), ("privacy", "Privacidad"), ("refund", "Reembolsos")]:
            ui.say(label + "\n" + (config.policies.get(key) or "Pendiente de configurar."))
    elif action == "memberships":
        query = select(m.Subscription).where(
            m.Subscription.bot_id == bot.id, m.Subscription.contact_id == person.id
        )
        if d.get("after"):
            query = query.where(m.Subscription.id > d["after"])
        subs = list(db.scalars(query.order_by(m.Subscription.id).limit(9)))
        buttons, lines = [], []
        for sub in subs[:8]:
            plan = db.get(m.Plan, sub.plan_id)
            active = sub.status == "ACTIVE" and sub.expires_at > m.now()
            lines.append(
                f"{plan.name}: {sub.status if active else 'Vencida o inactiva'} · hasta {date(sub.expires_at)}"
            )
            if active and plan.channel_id:
                buttons.append([ui.button("Entrar: " + plan.name, "access", id=sub.id)])
            if active and sub.initial_charge_id:
                buttons.append(
                    [
                        ui.button(
                            ("Cancelar" if sub.auto_renew else "Reactivar") + " renovación: " + plan.name,
                            "renewal",
                            id=sub.id,
                            canceled=sub.auto_renew,
                        )
                    ]
                )
        if len(subs) > 8:
            buttons.append([ui.button("Más membresías →", "memberships", after=subs[7].id)])
        ui.say("\n".join(lines) or "Aún no tienes membresías.", buttons)
    elif action in {"access", "renewal", "renewal_confirm"}:
        sub = get_scoped(db, m.Subscription, d["id"], bot.tenant_id)
        if sub.contact_id != person.id or sub.bot_id != bot.id:
            raise DomainError("NOT_FOUND", "Membresía no disponible.")
        if action == "access":
            if sub.status != "ACTIVE" or sub.expires_at <= m.now():
                raise DomainError("EXPIRED", "La membresía ya venció.")
            enqueue(
                db,
                "GRANT_ACCESS",
                bot.tenant_id,
                {"subscription_id": sub.id},
                f"native-access:{sub.id}:{ui.update['update_id']}",
                bot.id,
            )
            previous = db.scalar(
                select(m.ChannelInvite).where(
                    m.ChannelInvite.subscription_id == sub.id,
                    m.ChannelInvite.expires_at > m.now(),
                    m.ChannelInvite.used_at.is_(None),
                    m.ChannelInvite.revoked_at.is_(None),
                )
            )
            ui.say(
                "Usa tu enlace personal." if previous else "Estamos preparando tu enlace de acceso.",
                [[{"text": "Entrar al canal", "url": previous.invite_link}]] if previous else [],
            )
        elif action == "renewal":
            ui.say(
                "Confirma el cambio de renovación. Tu periodo ya pagado se conserva.",
                [[ui.button("Confirmar", "renewal_confirm", **d)]],
            )
        else:
            payment = db.get(m.Payment, sub.payment_id)
            if payment.provider != "TELEGRAM_STARS" or not payment.recurring:
                raise DomainError("NOT_RECURRING", "Esta membresía se renueva manualmente.")
            ui.r.payments.providers["TELEGRAM_STARS"].cancel_subscription(db, bot, person, sub, d["canceled"])
            sub.auto_renew, sub.renewal_status = not d["canceled"], "CANCELED" if d["canceled"] else "ACTIVE"
            ui.say("Renovación actualizada.")
    elif action == "stop":
        person.opted_out = True
        ui.say("Desactivaste los mensajes de campañas. Tus mensajes de pago y acceso siguen habilitados.")
    elif action == "support":
        config = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
        ui.say(
            bot_text(db, bot, "SUPPORT") + "\nEscribe aquí tu consulta para que el equipo la vea.",
            [[{"text": "Contactar soporte", "url": "https://t.me/" + config.support_username.lstrip("@")}]]
            if config.support_username
            else [],
        )
    else:
        raise DomainError("UNKNOWN_ACTION", "Abre /start para actualizar las opciones.")
