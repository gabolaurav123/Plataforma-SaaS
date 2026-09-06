"""Telegram-native creator and owner console. No HTTP server or Mini App is involved.

Buttons are opaque, expire, and are bound to the bot and verified Telegram actor.
Every action rechecks membership/role; dialogs survive restarts in PostgreSQL.
"""

import json
from datetime import datetime, timezone
from sqlalchemy import select, func
from pydantic import ValidationError
from .. import models as m
from ..db import get_scoped
from ..errors import DomainError
from ..security import require_role, redact
from ..api.auth import TenantContext
from ..api.schemas import BotCreate, TextSave, PlanCreate, MemberCreate
from ..api.creator import save_plan
from ..api.resources import RESOURCES, calculate_analytics
from ..api.serialization import public
from . import tenants, crm
from .common import send, audit, enqueue
from .texts import DEFAULT_TEXTS

RES_LABELS = {
    "contacts": "👥 Clientes",
    "subscriptions": "🎟 Membresías",
    "payments": "💰 Pagos",
    "receipts": "🧾 Comprobantes",
    "conversations": "💬 Conversaciones",
    "team": "👤 Equipo",
    "campaigns": "📣 Campañas",
    "automations": "⏱ Automatizaciones",
    "audit": "📋 Actividad",
    "plans": "⭐ Planes",
    "channels": "📢 Canales",
    "charges": "💳 Cobros",
    "notes": "Notas",
    "tasks": "Tareas",
    "coupons": "Cupones",
    "referrals": "Referidos",
    "links": "Enlaces",
    "usage": "Uso del plan",
    "flags": "Funciones",
    "providers": "Métodos de pago",
    "tags": "Etiquetas",
    "prices": "Precios",
    "billing": "Suscripción SaaS",
    "bots": "🤖 Bots",
}
FIELD_LABELS = {
    "name": "Nombre",
    "description": "Descripción",
    "short_description": "Descripción corta",
    "support_username": "Usuario de soporte",
    "terms": "Términos",
    "privacy": "Privacidad",
    "refund": "Política de reembolso",
    "WELCOME": "Bienvenida",
    "SUPPORT": "Mensaje de soporte",
}
OWNER_RESOURCES = {
    "tenants": m.Tenant,
    "users": m.PlatformUser,
    "bots": m.ManagedBot,
    "jobs": m.Job,
    "audit": m.AuditLog,
    "support": m.PlatformSupportTicket,
    "saas": m.SaaSPlan,
}


def date(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime("%d/%m/%Y %H:%M UTC") if value else "—"


def handle(runtime, session, update, bot=None):
    query = update.get("callback_query")
    message = query.get("message", {}) if query else update.get("message", {})
    actor = query.get("from", {}) if query else message.get("from", {})
    if (
        message.get("chat", {}).get("type") != "private"
        or type(actor.get("id")) is not int
        or actor.get("is_bot")
        or message["chat"]["id"] != actor["id"]
    ):
        return
    ui = Console(runtime, session, bot, update, actor)
    try:
        with session.begin_nested():
            ui.run(message, query)
    except (DomainError, ValidationError, ValueError) as error:
        # Never echo validation input (which might contain a pasted token).
        text = (
            error.message if isinstance(error, DomainError) else "Dato no válido. Revisa el formato indicado."
        )
        ui.say("⚠️ " + text + "\nPuedes reintentar o usar /cancel.")


class Console:
    def __init__(self, runtime, session, bot, update, actor):
        self.r, self.db, self.bot, self.update, self.actor = runtime, session, bot, update, actor
        self.key, self.count = bot.id if bot else "master", 0
        self.user = tenants.upsert_user(session, actor) if not bot else None

    def button(self, label, action, **data):
        row = m.ConsoleButton(
            id=m.uid(),
            bot_key=self.key,
            telegram_user_id=self.actor["id"],
            action=action,
            data=data,
            expires_at=m.now() + 3600,
        )
        self.db.add(row)
        return {"text": label[:64], "callback_data": "ui:" + row.id}

    def say(self, text, buttons=None, markup=None):
        self.count += 1
        return send(
            self.db,
            self.bot,
            self.actor["id"],
            text[:4096],
            f"console:{self.key}:{self.update['update_id']}:{self.count}",
            reply_markup=markup
            or {"inline_keyboard": (buttons or []) + [[self.button("🏠 Inicio", "home")]]},
        )

    def state(self):
        row = self.db.scalar(
            select(m.ConsoleState)
            .where(m.ConsoleState.bot_key == self.key, m.ConsoleState.telegram_user_id == self.actor["id"])
            .with_for_update()
        )
        if not row:
            row = m.ConsoleState(
                bot_key=self.key, telegram_user_id=self.actor["id"], data={}, expires_at=m.now() + 86400
            )
            self.db.add(row)
            self.db.flush()
        if row.expires_at <= m.now():
            row.data = {}
        return row

    def ask(self, flow, prompt, **data):
        row = self.state()
        row.data, row.expires_at = {"flow": flow, **data}, m.now() + 86400
        self.say(prompt + "\n/cancel para salir.")

    def owner(self):
        if self.actor["id"] not in self.r.settings.owner_ids:
            raise DomainError(
                "OWNER_REQUIRED", "Solo el administrador de la plataforma puede abrir esta opción.", 403
            )

    def ctx(self, tid, permission="read"):
        member = self.db.scalar(
            select(m.TenantMember).where(
                m.TenantMember.tenant_id == tid,
                m.TenantMember.user_id == self.user.id,
                m.TenantMember.active.is_(True),
            )
        )
        if not member and self.actor["id"] not in self.r.settings.owner_ids:
            raise DomainError("NOT_FOUND", "No tienes acceso a este negocio.", 404)
        role = member.role if member else "OWNER"
        require_role(role, permission)
        tenants.entitlement(self.db, tid, writable=permission not in {"read", "billing", "export"})
        return TenantContext(tid, self.user.id, self.actor["id"], role)

    def entity(self, model, tid, entity_id, permission="read"):
        self.ctx(tid, permission)
        return get_scoped(self.db, model, entity_id, tid)

    def run(self, message, query):
        if query:
            callback = query.get("data", "")
            row = (
                self.db.scalar(
                    select(m.ConsoleButton)
                    .where(
                        m.ConsoleButton.id == callback[3:],
                        m.ConsoleButton.bot_key == self.key,
                        m.ConsoleButton.telegram_user_id == self.actor["id"],
                        m.ConsoleButton.expires_at > m.now(),
                    )
                    .with_for_update()
                )
                if callback.startswith("ui:")
                else None
            )
            if not row or row.used_at:
                self.say("Este botón caducó o ya fue utilizado. Abre /start para actualizar el menú.")
                return
            action, data = row.action, dict(row.data)
            row.used_at = m.now()
            if self.bot:
                from .console_customer import dispatch

                dispatch(self, action, data)
            else:
                self.dispatch(action, data)
            return
        text = message.get("text", "").strip()
        if self.bot:
            from .console_customer import message as customer_message

            customer_message(self, message)
        elif text.startswith(("/start", "/cancel", "/menu")):
            self.state().data = {}
            self.say("Tu negocio se administra aquí, en Telegram.", markup={"remove_keyboard": True})
            self.home()
        elif text == "/id":
            self.say(f"Tu ID de Telegram: {self.actor['id']}")
        elif text.startswith("/admin"):
            self.admin()
        elif text.startswith(("/support", "/paysupport")):
            self.ask("ticket", "Describe tu consulta o el problema con tu pago (5 a 3000 caracteres).")
        elif self.state().data:
            self.answer(text, message)
        else:
            self.home()

    def home(self):
        if self.bot:
            from .console_customer import home

            return home(self)
        self.state().data = {}
        rows = list(
            self.db.scalars(
                select(m.Tenant)
                .join(m.TenantMember, m.TenantMember.tenant_id == m.Tenant.id)
                .where(m.TenantMember.user_id == self.user.id, m.TenantMember.active.is_(True))
                .order_by(m.Tenant.created_at)
                .limit(30)
            )
        )
        buttons = [[self.button("🏢 " + row.name, "workspace", tid=row.id)] for row in rows]
        buttons += [
            [self.button("🚀 Crear mi negocio", "new_workspace")],
            [self.button("❓ Ayuda y soporte", "help")],
        ]
        if self.actor["id"] in self.r.settings.owner_ids:
            buttons.append([self.button("🛡 Administrar plataforma", "admin")])
        self.say("Selecciona tu negocio o crea uno para conectar tu bot.", buttons)

    def workspace(self, tid):
        self.ctx(tid)
        tenant, sub, plan = tenants.entitlement(self.db, tid, writable=False)
        audit(self.db, tid, self.user.id, "TELEGRAM_WORKSPACE_VIEWED", tid)
        bots = list(self.db.scalars(select(m.ManagedBot).where(m.ManagedBot.tenant_id == tid).limit(100)))
        buttons = [[self.button("🤖 @" + bot.username, "bot", tid=tid, id=bot.id)] for bot in bots]
        buttons += [
            [self.button("➕ Crear bot", "new_bot", tid=tid)],
            [
                self.button("📊 Estadísticas", "stats", tid=tid),
                self.button("💳 Mi plan SaaS", "billing", tid=tid),
            ],
        ]
        for res in [
            "contacts",
            "subscriptions",
            "payments",
            "receipts",
            "conversations",
            "team",
            "campaigns",
            "automations",
        ]:
            buttons.append([self.button(RES_LABELS[res], "list", tid=tid, resource=res)])
        buttons.append([self.button("📚 Todos los registros", "records", tid=tid)])
        self.say(
            f"🏢 {tenant.name}\nPlan {plan.name} · {sub.status}\nVence: {date(sub.current_period_end)}",
            buttons,
        )

    def bot_menu(self, tid, bid):
        bot = self.entity(m.ManagedBot, tid, bid)
        buttons = [[{"text": "Abrir mi bot", "url": f"https://t.me/{bot.username}"}]]
        for label, action in [
            ("⚙️ Nombre, textos y políticas", "settings"),
            ("🖼 Foto de perfil", "photo"),
            ("📢 Conectar canal", "channel"),
            ("⭐ Planes y precios", "plans"),
            ("📣 Crear campaña", "campaign"),
            ("⏱ Crear automatización", "automation"),
            ("✅ Comprobar y publicar", "publish"),
            ("🔧 Reparar conexión", "repair"),
        ]:
            buttons.append([self.button(label, action, tid=tid, id=bid)])
        self.say(
            f"🤖 @{bot.username}\n{bot.name}\nEstado: {bot.status}\nPublicado: {'Sí' if bot.published else 'No'}",
            buttons,
        )

    def settings(self, tid, bid):
        self.entity(m.ManagedBot, tid, bid, "configure")
        rows = [
            [self.button(label, "field", tid=tid, id=bid, field=field)]
            for field, label in FIELD_LABELS.items()
        ]
        rows += [[self.button("Otros mensajes automáticos", "texts", tid=tid, id=bid)]]
        self.say("Selecciona el dato que quieres cambiar.", rows)

    def dispatch(self, action, d):
        tid, eid = d.get("tid"), d.get("id")
        if action == "home":
            self.home()
        elif action == "admin":
            self.admin()
        elif action == "master_check":
            self.owner()
            capability = self.r.manager.capabilities()
            self.say(
                capability["message"]
                + (
                    "\nAbre el nuevo Master en @BotFather y activa Bot Management Mode."
                    if not capability["enabled"]
                    else ""
                )
            )
        elif action == "workspace":
            self.workspace(tid)
        elif action == "new_workspace":
            self.ask("workspace_name", "¿Cómo se llama tu negocio? (2 a 100 caracteres)")
        elif action == "help":
            self.say(
                "1. Crea tu negocio y su bot con el botón oficial de Telegram.\n2. Configura textos, soporte y políticas.\n3. Conecta el canal y crea un plan en Stars.\n4. Abre el bot hijo, pulsa Iniciar y vuelve aquí para publicarlo.\nUsa /support para contactar con la plataforma.\nNunca necesitas enviarnos el token de un bot hijo."
            )
        elif action == "new_bot":
            self.ctx(tid, "configure")
            self.ask("bot_name", "Nombre visible del nuevo bot (máximo 64 caracteres):", tid=tid)
        elif action == "bot":
            self.bot_menu(tid, eid)
        elif action == "settings":
            self.settings(tid, eid)
        elif action == "texts":
            self.entity(m.ManagedBot, tid, eid, "configure")
            self.say(
                "Mensajes del bot. Variables permitidas según el texto original.",
                [[self.button(key, "field", tid=tid, id=eid, field=key)] for key in DEFAULT_TEXTS],
            )
        elif action == "field":
            self.entity(m.ManagedBot, tid, eid, "configure")
            config = self.db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == eid))
            field = d["field"]
            if field in DEFAULT_TEXTS:
                current = self.db.scalar(
                    select(m.BotText.value).where(m.BotText.bot_id == eid, m.BotText.key == field)
                )
            else:
                current = (
                    config.policies.get(field, "")
                    if field in {"terms", "privacy", "refund"}
                    else (
                        self.db.get(m.ManagedBot, eid).name if field == "name" else getattr(config, field, "")
                    )
                )
            self.ask(
                "field",
                f"{FIELD_LABELS.get(field, field)} actual:\n{str(current)[:1500]}\n\nEnvía el nuevo texto:",
                **d,
            )
        elif action == "photo":
            self.entity(m.ManagedBot, tid, eid, "configure")
            self.ask("photo", "Envía una foto JPG, PNG o WebP (máximo 5 MB).", **d)
        elif action == "channel":
            bot = self.entity(m.ManagedBot, tid, eid, "configure")
            self.say(
                "Añade el bot al canal como administrador con permisos para invitar y restringir miembros. Telegram avisará a la plataforma automáticamente.",
                [
                    [{"text": "Añadir al canal", "url": self.r.channels.connect_link(bot)}],
                    [self.button("Verificar canales", "verify_channels", tid=tid, id=eid)],
                ],
            )
        elif action == "verify_channels":
            bot = self.entity(m.ManagedBot, tid, eid, "configure")
            channels = list(self.db.scalars(select(m.Channel).where(m.Channel.bot_id == bot.id)))
            for channel in channels:
                self.r.channels.verify(self.db, bot, channel)
            self.say(
                "\n".join(f"{x.title}: {x.status}" for x in channels)
                or "Todavía no se recibió ningún canal. Añade el bot como administrador y vuelve a verificar."
            )
        elif action == "plans":
            self.entity(m.ManagedBot, tid, eid)
            plans = list(self.db.scalars(select(m.Plan).where(m.Plan.bot_id == eid).limit(80)))
            self.say(
                "Planes del bot",
                [[self.button(p.name, "detail", tid=tid, resource="plans", id=p.id)] for p in plans]
                + [[self.button("➕ Crear plan", "new_plan", tid=tid, id=eid)]],
            )
        elif action == "new_plan":
            self.entity(m.ManagedBot, tid, eid, "configure")
            self.ask("plan_name", "Nombre del plan:", tid=tid, bid=eid)
        elif action == "plan_channel":
            self.create_plan({**d, "channel_id": eid})
        elif action == "price":
            self.entity(m.Plan, tid, eid, "configure")
            self.ask(
                "price",
                "Nuevo precio en Stars, entero entre 1 y 10000. Los pagos ya iniciados conservan su precio.",
                **d,
            )
        elif action == "plan_toggle":
            row = self.entity(m.Plan, tid, eid, "configure")
            row.active = not row.active
            audit(self.db, tid, self.user.id, "PLAN_CONFIGURED", eid)
            self.say(
                "Plan activado."
                if row.active
                else "Plan desactivado. Las membresías existentes se conservan."
            )
        elif action == "publish":
            bot = self.entity(m.ManagedBot, tid, eid, "configure")
            result = self.r.provisioner.publish(self.db, bot, self.user.id)
            labels = {
                "webhook": "conexión de Telegram",
                "support_and_policies": "soporte, términos, privacidad y reembolsos",
                "plan": "plan activo con precio Stars",
                "payment_method": "Stars",
                "channel_permissions": "permisos del canal",
            }
            missing = [labels.get(k, k) for k, v in result["checks"].items() if not v]
            self.say(
                "✅ Bot publicado y preparado para recibir clientes."
                if result["ready"]
                else "Falta completar:\n" + "\n".join(missing)
            )
        elif action == "repair":
            bot = self.entity(m.ManagedBot, tid, eid, "configure")
            enqueue(
                self.db, "PROVISION", tid, {}, f"native-repair:{bot.id}:{self.update['update_id']}", bot.id
            )
            self.say("Revisión de conexión en cola.")
        elif action == "stats":
            self.ctx(tid)
            values = calculate_analytics(self.db, tid)
            self.say(
                f"📊 Últimos 30 días\nClientes: {values['contacts']}\nNuevos: {values['new_clients']}\nMembresías activas: {values['active_subscriptions']}\nComprobantes pendientes: {values['pending_receipts']}\nConversión: {values['conversion_percent']}%\nIngresos (unidades mínimas por moneda): {values['revenue_minor']}"
            )
        elif action == "records":
            self.ctx(tid)
            self.say(
                "Registros del negocio",
                [[self.button(label, "list", tid=tid, resource=res)] for res, label in RES_LABELS.items()],
            )
        elif action == "list":
            self.list_records(d)
        elif action == "detail":
            self.detail(d)
        elif action == "reply":
            self.entity(m.Conversation, tid, eid, "support")
            self.ask("reply", "Escribe la respuesta que se enviará al cliente desde su bot:", **d)
        elif action == "note":
            self.entity(m.Contact, tid, eid, "support")
            self.ask("note", "Escribe una nota interna (máximo 2000 caracteres):", **d)
        elif action == "receipt_image":
            row = self.entity(m.BankReceipt, tid, eid, "payments")
            # Decrypt only during delivery. The outbox holds a reference, never image bytes.
            self.say("Comprobante", markup={"remove_keyboard": True}).payload = {
                "chat_id": self.actor["id"],
                "receipt_id": row.id,
                "viewer_id": self.actor["id"],
                "caption": "Comprobante para revisión",
            }
        elif action == "review":
            self.entity(m.BankReceipt, tid, eid, "payments")
            self.ask("review", "Escribe el motivo o referencia bancaria de tu decisión:", **d)
        elif action == "review_confirm":
            row = self.entity(m.BankReceipt, tid, eid, "payments")
            payment = get_scoped(self.db, m.Payment, row.payment_id, tid)
            bot = get_scoped(self.db, m.ManagedBot, payment.bot_id, tid)
            self.r.receipts.review(self.db, bot, row, self.user.id, d["decision"], d["note"], False)
            self.say("Revisión guardada.")
        elif action == "refund":
            row = self.entity(m.PaymentCharge, tid, eid, "payments")
            self.say(
                f"¿Reembolsar {row.amount_minor} {row.currency}? Esta acción devuelve el cobro y revoca el acceso si corresponde.",
                [[self.button("Confirmar reembolso", "refund_confirm", **d)]],
            )
        elif action == "refund_confirm":
            row = self.entity(m.PaymentCharge, tid, eid, "payments")
            payment = get_scoped(self.db, m.Payment, row.payment_id, tid)
            bot = get_scoped(self.db, m.ManagedBot, payment.bot_id, tid)
            if not row.refunded_at:
                self.r.payments.providers[payment.provider].refund(self.db, bot, payment, row)
                self.r.payments.refunded_event(self.db, bot, {"telegram_payment_charge_id": row.charge_id})
                audit(self.db, tid, self.user.id, "REFUND_REQUESTED", eid)
            self.say("Reembolso registrado.")
        elif action == "team_add":
            self.ctx(tid, "team")
            self.ask(
                "team",
                "Envía ID numérico y rol separados por un espacio.\nRoles: SUPERVISOR, PAYMENTS, SALES, SUPPORT, READ_ONLY.\nEjemplo: 123456789 SUPPORT\nLa persona debe haber abierto antes este bot maestro.",
                tid=tid,
            )
        elif action == "team_remove":
            member = self.entity(m.TenantMember, tid, eid, "team")
            if member.role == "OWNER":
                raise DomainError("OWNER_PROTECTED", "No se puede retirar al propietario.")
            member.active = False
            audit(self.db, tid, self.user.id, "TEAM_MEMBER_REMOVED", eid)
            self.say("Acceso retirado.")
        elif action == "billing":
            self.ctx(tid, "billing")
            plans = self.db.scalars(select(m.SaaSPlan).where(m.SaaSPlan.active.is_(True)))
            self.say(
                "Planes mensuales de la plataforma. El pago se confirma en Telegram Stars.",
                [
                    [
                        self.button(
                            f"{p.name}: {p.prices.get('XTR', 'sin precio')} ⭐/30 días",
                            "billing_buy",
                            tid=tid,
                            id=p.id,
                        )
                    ]
                    for p in plans
                ],
            )
        elif action == "billing_buy":
            self.ctx(tid, "billing")
            invoice = self.r.billing.checkout(self.db, tid, self.user, eid)
            self.say(
                "Suscripción mensual con renovación automática de Telegram. Revisa el importe antes de pagar.",
                [[{"text": "Revisar pago en Stars", "url": invoice.checkout_url}]],
            )
        elif action in {"campaign", "automation"}:
            self.entity(m.ManagedBot, tid, eid, "sales" if action == "campaign" else "configure")
            self.ask(
                action,
                "Escribe el mensaje de la campaña (se guardará como borrador):"
                if action == "campaign"
                else "Escribe el recordatorio que se enviará tres días antes de vencer una membresía:",
                tid=tid,
                bid=eid,
            )
        elif action == "campaign_start":
            row = self.entity(m.Campaign, tid, eid, "sales")
            self.say(
                f"Enviar «{row.name}» a los contactos que aceptaron campañas:\n\n{row.text[:2000]}",
                [[self.button("Confirmar envío", "campaign_confirm", **d)]],
            )
        elif action == "campaign_confirm":
            row = self.entity(m.Campaign, tid, eid, "sales")
            self.r.campaigns.start(self.db, row)
            audit(self.db, tid, self.user.id, "CAMPAIGN_START", eid)
            self.say("Campaña en cola. Puedes consultar su avance y pausarla desde Campañas.")
        elif action == "campaign_pause":
            row = self.entity(m.Campaign, tid, eid, "sales")
            if row.status != "COMPLETED":
                row.status = "PAUSED"
            self.say("Estado: " + row.status)
        elif action == "automation_toggle":
            row = self.entity(m.AutomationRule, tid, eid, "configure")
            row.active = not row.active
            audit(self.db, tid, self.user.id, "AUTOMATION_CONFIGURED", eid)
            self.say("Automatización activada." if row.active else "Automatización desactivada.")
        elif action == "owner_list":
            self.owner_list(d)
        elif action == "owner_detail":
            self.owner_detail(d)
        elif action == "ticket_reply":
            self.owner()
            self.ask("ticket_reply", "Escribe la respuesta que recibirá el creador en este bot:", **d)
        elif action in {"tenant_suspend", "tenant_extend", "saas_price"}:
            self.owner()
            prompts = {
                "tenant_suspend": "Motivo de suspensión (mínimo 5 caracteres):",
                "tenant_extend": "Días de acceso que quieres conceder sin cobro (1 a 365):",
                "saas_price": "Precio mensual en Stars (1 a 10000):",
            }
            self.ask(action, prompts[action], **d)
        elif action == "tenant_confirm":
            self.owner()
            tenant = self.db.get(m.Tenant, eid)
            if d["operation"] == "suspend":
                tenant.status, tenant.suspended_at = "SUSPENDED", m.now()
            else:
                sub = self.db.scalar(select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == eid))
                sub.current_period_end = max(m.now(), sub.current_period_end) + d["days"] * 86400
                sub.status, tenant.status, tenant.suspended_at = "ACTIVE", "ACTIVE", None
            audit(
                self.db,
                eid,
                self.user.id,
                "TELEGRAM_TENANT_" + d["operation"].upper(),
                eid,
                {"reason": d.get("reason"), "days": d.get("days")},
            )
            self.say("Estado del negocio actualizado.")
        else:
            raise DomainError("UNKNOWN_ACTION", "Esta opción ya no está disponible. Abre /start.")

    def answer(self, text, message):
        d = dict(self.state().data)
        flow, tid, eid = d.pop("flow"), d.get("tid"), d.get("id")
        if flow == "workspace_name":
            if not 2 <= len(text) <= 100:
                raise ValueError()
            tenant = tenants.create_tenant(self.db, self.user, text, self.r.settings)
            self.state().data = {}
            self.workspace(tenant.id)
        elif flow == "bot_name":
            self.ctx(tid, "configure")
            if not 1 <= len(text) <= 64:
                raise ValueError()
            self.ask(
                "bot_username",
                "Usuario del bot sin @; debe terminar en bot. Ejemplo: MiClubPremium_bot",
                tid=tid,
                name=text,
            )
        elif flow == "bot_username":
            self.ctx(tid, "configure")
            body = BotCreate(name=d["name"], username=text.lstrip("@"))
            result = self.r.manager.request_creation(self.db, tid, self.user, body.name, body.username)
            self.state().data = {}
            self.say(
                "Pulsa Crear mi bot y confirma la creación en Telegram. Después vuelve aquí a /start.",
                markup={"keyboard": result["keyboard"], "resize_keyboard": True, "one_time_keyboard": True},
            )
        elif flow == "field":
            bot = self.entity(m.ManagedBot, tid, eid, "configure")
            field = d["field"]
            config = self.db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == eid))
            if field in DEFAULT_TEXTS:
                TextSave(value=text)
                row = self.db.scalar(select(m.BotText).where(m.BotText.bot_id == eid, m.BotText.key == field))
                row.value = text
            elif field in {"terms", "privacy", "refund"}:
                if not 1 <= len(text) <= 3500:
                    raise ValueError()
                config.policies = {**config.policies, field: text}
            else:
                limits = {"name": 64, "description": 512, "short_description": 120, "support_username": 64}
                if field not in limits or not 1 <= len(text) <= limits[field]:
                    raise ValueError()
                if field == "support_username":
                    import re

                    if not re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{3,31}", text):
                        raise ValueError()
                setattr(bot if field == "name" else config, field, text)
            bot.config_version += 1
            enqueue(self.db, "CONFIGURE", tid, {}, f"config:{bot.id}:{bot.config_version}", bot.id)
            audit(self.db, tid, self.user.id, "BOT_CONFIGURED", eid, {"field": field})
            self.state().data = {}
            self.say("✅ Guardado. La configuración se sincronizará con Telegram.")
        elif flow == "photo":
            bot = self.entity(m.ManagedBot, tid, eid, "configure")
            photo = message.get("photo", [])
            file_id = photo[-1]["file_id"] if photo else message.get("document", {}).get("file_id")
            if not file_id:
                raise ValueError()
            data = self.r.clients.master().download(file_id, self.r.settings.max_upload_bytes)
            self.r.provisioner.photo(self.db, bot, data)
            self.state().data = {}
            self.say("Foto actualizada.")
        elif flow.startswith("plan_"):
            self.entity(m.ManagedBot, tid, d["bid"], "configure")
            if flow == "plan_name":
                if not 1 <= len(text) <= 100:
                    raise ValueError()
                self.ask("plan_days", "Duración en días (1 a 3650):", **d, name=text)
            elif flow == "plan_days":
                days = int(text)
                if not 1 <= days <= 3650:
                    raise ValueError()
                self.ask("plan_price", "Precio total en Stars (entero, 1 a 10000):", **d, days=days)
            elif flow == "plan_price":
                price = int(text)
                if not 1 <= price <= 10000:
                    raise ValueError()
                self.ask(
                    "plan_renew",
                    "¿Renovación automática? Escribe sí o no. Solo está disponible con duración de 30 días.",
                    **d,
                    price=price,
                )
            else:
                if text.lower() not in {"sí", "si", "no"}:
                    raise ValueError()
                recurring = text.lower() != "no"
                if recurring and d["days"] != 30:
                    raise DomainError(
                        "STARS_PERIOD",
                        "Para esta duración escribe no. Telegram renueva automáticamente cada 30 días.",
                    )
                self.state().data = {}
                channels = self.db.scalars(
                    select(m.Channel).where(m.Channel.bot_id == d["bid"], m.Channel.access_mode == "PLATFORM")
                )
                self.say(
                    "Selecciona el canal incluido. El plan se cobrará en Telegram Stars.",
                    [
                        [self.button(c.title, "plan_channel", **d, recurring=recurring, id=c.id)]
                        for c in channels
                    ]
                    + [
                        [
                            self.button(
                                "Sin canal (membresía)", "plan_channel", **d, recurring=recurring, id=None
                            )
                        ]
                    ],
                )
        elif flow == "price":
            plan = self.entity(m.Plan, tid, eid, "configure")
            price = int(text)
            if not 1 <= price <= 10000:
                raise ValueError()
            row = self.db.scalar(
                select(m.PlanPrice).where(m.PlanPrice.plan_id == eid, m.PlanPrice.currency == "XTR")
            )
            if not row:
                raise DomainError("NO_STARS_PRICE", "Crea primero un plan en Stars.")
            row.amount_minor = price
            audit(self.db, tid, self.user.id, "PLAN_CONFIGURED", plan.id)
            self.state().data = {}
            self.say("Precio actualizado.")
        elif flow == "reply":
            conv = self.entity(m.Conversation, tid, eid, "support")
            if not 1 <= len(text) <= 4096:
                raise ValueError()
            crm.reply(
                self.db,
                get_scoped(self.db, m.ManagedBot, conv.bot_id, tid),
                conv,
                self.user.id,
                text,
                f"telegram:{self.update['update_id']}",
            )
            self.state().data = {}
            self.say("Respuesta en cola.")
        elif flow == "note":
            self.entity(m.Contact, tid, eid, "support")
            if not 1 <= len(text) <= 2000:
                raise ValueError()
            self.db.add(m.InternalNote(tenant_id=tid, contact_id=eid, author_id=self.user.id, text=text))
            self.state().data = {}
            self.say("Nota interna guardada.")
        elif flow == "review":
            self.entity(m.BankReceipt, tid, eid, "payments")
            if not 5 <= len(text) <= 500:
                raise ValueError()
            self.state().data = {}
            self.say(
                f"Decisión: {d['decision']}\nMotivo: {text}",
                [[self.button("Confirmar revisión", "review_confirm", **d, note=text)]],
            )
        elif flow == "team":
            self.ctx(tid, "team")
            tenants.feature(self.db, tid, "team_members")
            user_id, role = text.split()
            body = MemberCreate(telegram_user_id=int(user_id), role=role.upper())
            user = self.db.scalar(
                select(m.PlatformUser).where(m.PlatformUser.telegram_user_id == body.telegram_user_id)
            )
            if not user:
                raise DomainError("USER_MUST_START_MASTER", "La persona debe abrir primero este bot maestro.")
            row = self.db.scalar(
                select(m.TenantMember).where(
                    m.TenantMember.tenant_id == tid, m.TenantMember.user_id == user.id
                )
            )
            if row and row.role == "OWNER":
                raise DomainError("OWNER_PROTECTED", "No se puede cambiar al propietario.")
            if not row:
                tenants.check_entity_limit(self.db, tid, "admins", m.TenantMember)
                row = m.TenantMember(tenant_id=tid, user_id=user.id)
                self.db.add(row)
            row.role, row.active = body.role, True
            audit(self.db, tid, self.user.id, "TEAM_MEMBER_CONFIGURED", user.id)
            self.state().data = {}
            self.say("Acceso de equipo configurado.")
        elif flow in {"campaign", "automation"}:
            self.entity(m.ManagedBot, tid, d["bid"], "sales" if flow == "campaign" else "configure")
            TextSave(value=text)
            if not text:
                raise ValueError()
            tenants.feature(self.db, tid, "campaigns" if flow == "campaign" else "automations")
            if flow == "campaign":
                row = m.Campaign(
                    tenant_id=tid, bot_id=d["bid"], name="Campaña " + date(m.now()), text=text, segment={}
                )
            else:
                tenants.check_entity_limit(self.db, tid, "automations", m.AutomationRule)
                row = m.AutomationRule(
                    tenant_id=tid,
                    bot_id=d["bid"],
                    name="Recordatorio de vencimiento",
                    trigger="SUBSCRIPTION_EXPIRING",
                    action="SEND_MESSAGE",
                    delay_seconds=0,
                    active=True,
                    config={"text": text},
                )
            self.db.add(row)
            self.db.flush()
            audit(self.db, tid, self.user.id, flow.upper() + "_CREATED", row.id)
            self.state().data = {}
            self.detail(
                {"tid": tid, "resource": "campaigns" if flow == "campaign" else "automations", "id": row.id}
            )
        elif flow == "ticket":
            if not 5 <= len(text) <= 3000:
                raise ValueError()
            ticket = m.PlatformSupportTicket(user_id=self.user.id, subject=text[:120], text=text)
            self.db.add(ticket)
            self.state().data = {}
            self.say("Consulta guardada. El administrador la verá en Soporte de la plataforma.")
        elif flow == "ticket_reply":
            self.owner()
            if not 1 <= len(text) <= 3500:
                raise ValueError()
            ticket = self.db.get(m.PlatformSupportTicket, eid)
            recipient = self.db.get(m.PlatformUser, ticket.user_id)
            send(
                self.db,
                None,
                recipient.telegram_user_id,
                "Respuesta de soporte:\n" + text,
                f"ticket-reply:{eid}:{self.update['update_id']}",
            )
            ticket.status = "ANSWERED"
            audit(self.db, None, self.user.id, "SUPPORT_TICKET_ANSWERED", eid)
            self.state().data = {}
            self.say("Respuesta en cola.")
        elif flow in {"tenant_suspend", "tenant_extend", "saas_price"}:
            self.owner()
            self.state().data = {}
            if flow == "saas_price":
                price = int(text)
                if not 1 <= price <= 10000:
                    raise ValueError()
                row = self.db.get(m.SaaSPlan, eid)
                row.prices = {"XTR": price}
                audit(self.db, None, self.user.id, "SAAS_PLAN_CONFIGURED", eid)
                self.say("Precio SaaS guardado.")
            else:
                if flow == "tenant_suspend":
                    if not 5 <= len(text) <= 500:
                        raise ValueError()
                    details = {"operation": "suspend", "reason": text}
                else:
                    days = int(text)
                    if not 1 <= days <= 365:
                        raise ValueError()
                    details = {"operation": "extend", "days": days}
                self.say(
                    "Confirma el cambio: "
                    + (
                        f"conceder {details['days']} días sin cobro"
                        if "days" in details
                        else "suspender: " + text
                    ),
                    [[self.button("Confirmar cambio", "tenant_confirm", id=eid, **details)]],
                )
        else:
            self.state().data = {}
            self.home()

    def create_plan(self, d):
        ctx = self.ctx(d["tid"], "configure")
        body = PlanCreate(
            bot_id=d["bid"],
            channel_id=d["channel_id"],
            name=d["name"],
            duration_days=d["days"],
            recurring=d["recurring"],
            prices=[{"provider": "TELEGRAM_STARS", "currency": "XTR", "amount_minor": d["price"]}],
        )
        save_plan(self.db, body, ctx)
        provider = self.db.scalar(
            select(m.ProviderConfig).where(
                m.ProviderConfig.tenant_id == d["tid"], m.ProviderConfig.provider == "TELEGRAM_STARS"
            )
        )
        if not provider:
            provider = m.ProviderConfig(tenant_id=d["tid"], provider="TELEGRAM_STARS")
            self.db.add(provider)
        provider.enabled = True
        self.say("✅ Plan creado y Stars habilitado. Completa soporte y políticas antes de publicar.")

    def list_records(self, d):
        tid, res = d["tid"], d["resource"]
        self.ctx(tid)
        model = RESOURCES[res]
        query = select(model).where(model.tenant_id == tid)
        if d.get("after"):
            query = query.where(model.id > d["after"])
        rows = list(self.db.scalars(query.order_by(model.id).limit(9)))
        buttons = [
            [self.button(self.label(row), "detail", tid=tid, resource=res, id=row.id)] for row in rows[:8]
        ]
        if len(rows) > 8:
            buttons.append([self.button("Siguiente →", "list", tid=tid, resource=res, after=rows[7].id)])
        if res == "team":
            buttons.append([self.button("➕ Añadir o cambiar rol", "team_add", tid=tid)])
        self.say(
            RES_LABELS.get(res, res) + ("\nSin registros." if not rows else "\nSelecciona un registro:"),
            buttons,
        )

    @staticmethod
    def label(row):
        name = next(
            (
                str(getattr(row, k))
                for k in ["name", "first_name", "title", "subject", "action", "kind", "role"]
                if getattr(row, k, None)
            ),
            row.id[:8],
        )
        return (name + " · " + str(getattr(row, "status", "")))[:64]

    def describe(self, row):
        values = redact(public(row))
        # Job bodies and arbitrary metadata are not displayed in operator menus.
        omit = {
            "payload",
            "data",
            "idempotency_key",
            "invoice_payload",
            "token_hash",
            "checkout_url",
            "tenant_id",
            "public_id",
            "config_version",
            "token_version",
            "lease_owner",
            "invoice_id",
            "initial_charge_id",
            "telegram_message_id",
        }
        labels = {
            "id": "Referencia",
            "name": "Nombre",
            "first_name": "Nombre",
            "username": "Usuario",
            "created_at": "Creado",
            "updated_at": "Actualizado",
            "status": "Estado",
            "text": "Mensaje",
            "description": "Descripción",
            "amount_minor": "Importe (Stars o centavos)",
            "amount_xtr": "Stars",
            "currency": "Moneda",
            "expires_at": "Vence",
            "current_period_end": "Fin del periodo",
            "trial_ends_at": "Fin de prueba",
            "starts_at": "Inicio",
            "role": "Rol",
            "active": "Activo",
            "auto_renew": "Renovación automática",
            "duration_days": "Duración (días)",
            "recurring": "Recurrente",
            "last_error_code": "Último error",
            "run_at": "Programado",
            "attempts": "Intentos",
            "kind": "Tipo",
            "action": "Acción",
            "stage": "Etapa",
            "subject": "Asunto",
        }
        refs = {
            "bot_id": m.ManagedBot,
            "contact_id": m.Contact,
            "plan_id": m.Plan,
            "user_id": m.PlatformUser,
            "owner_user_id": m.PlatformUser,
        }
        lines = []
        for key, value in values.items():
            if key in omit or value is None:
                continue
            if key in refs:
                target = self.db.get(refs[key], value)
                value = self.label(target) if target else value
            elif (key.endswith("_at") or key == "current_period_end") and isinstance(value, int):
                value = date(value)
            elif isinstance(value, bool):
                value = "Sí" if value else "No"
            elif isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"{labels.get(key, key.replace('_', ' '))}: {value}")
        return "\n".join(lines)[:2800]

    def detail(self, d):
        tid, res, eid = d["tid"], d["resource"], d["id"]
        row = self.entity(RESOURCES[res], tid, eid)
        buttons = []
        if res == "bots":
            return self.bot_menu(tid, eid)
        if res == "plans":
            price = self.db.scalar(
                select(m.PlanPrice).where(m.PlanPrice.plan_id == eid, m.PlanPrice.currency == "XTR")
            )
            self.say(f"Precio: {price.amount_minor if price else 'sin precio'} Stars")
            buttons += [
                [
                    self.button("Cambiar precio", "price", **d),
                    self.button("Desactivar" if row.active else "Activar", "plan_toggle", **d),
                ]
            ]
        elif res == "contacts":
            buttons += [[self.button("Añadir nota", "note", **d)]]
        elif res == "conversations":
            messages = list(
                self.db.scalars(
                    select(m.Message)
                    .where(m.Message.tenant_id == tid, m.Message.conversation_id == eid)
                    .order_by(m.Message.created_at.desc())
                    .limit(6)
                )
            )
            self.say(
                "\n\n".join(f"{x.direction}: {x.text[:450]}" for x in reversed(messages)) or "Sin mensajes."
            )
            buttons += [[self.button("Responder al cliente", "reply", **d)]]
        elif res == "receipts":
            buttons += [[self.button("Ver imagen", "receipt_image", **d)]]
            for label, decision in [
                ("Aprobar", "APPROVE"),
                ("Rechazar", "REJECT"),
                ("Pedir nuevo", "REQUEST_NEW"),
                ("Marcar sospechoso", "SUSPICIOUS"),
            ]:
                buttons.append([self.button(label, "review", **d, decision=decision)])
        elif res == "charges" and not row.refunded_at:
            buttons += [[self.button("Reembolsar cobro", "refund", **d)]]
        elif res == "team" and row.role != "OWNER":
            buttons += [[self.button("Retirar acceso", "team_remove", **d)]]
        elif res == "campaigns":
            buttons += [
                [
                    self.button("Iniciar / reanudar", "campaign_start", **d),
                    self.button("Pausar", "campaign_pause", **d),
                ]
            ]
        elif res == "automations":
            buttons += [[self.button("Desactivar" if row.active else "Activar", "automation_toggle", **d)]]
        self.say(self.describe(row), buttons)

    def admin(self):
        self.owner()

        def count(model):
            return self.db.scalar(select(func.count()).select_from(model))

        queue = dict(self.db.execute(select(m.Job.status, func.count()).group_by(m.Job.status)).all())
        revenue = self.db.scalar(select(func.sum(m.SaaSCharge.amount_xtr))) or 0
        audit(self.db, None, self.user.id, "TELEGRAM_PLATFORM_VIEWED")
        self.say(
            f"🛡 Plataforma\nNegocios: {count(m.Tenant)}\nUsuarios: {count(m.PlatformUser)}\nBots: {count(m.ManagedBot)}\nClientes: {count(m.Contact)}\nIngresos SaaS: {revenue} Stars\nCola: {queue}",
            [
                [self.button(label, "owner_list", resource=res)]
                for res, label in {
                    "tenants": "🏢 Negocios y acceso completo",
                    "users": "👥 Usuarios",
                    "bots": "🤖 Bots",
                    "jobs": "⚙️ Cola y errores",
                    "audit": "📋 Auditoría",
                    "support": "💬 Soporte",
                    "saas": "💳 Precios SaaS",
                }.items()
            ]
            + [[self.button("Verificar bot maestro", "master_check")]],
        )

    def owner_list(self, d):
        self.owner()
        model = OWNER_RESOURCES[d["resource"]]
        query = select(model)
        if d["resource"] == "jobs":
            query = query.where(m.Job.status != "DONE")
        if d.get("after"):
            query = query.where(model.id > d["after"])
        rows = list(self.db.scalars(query.order_by(model.id).limit(9)))
        buttons = [
            [self.button(self.label(x), "owner_detail", resource=d["resource"], id=x.id)] for x in rows[:8]
        ]
        if len(rows) > 8:
            buttons.append(
                [self.button("Siguiente →", "owner_list", resource=d["resource"], after=rows[7].id)]
            )
        self.say("Registros de plataforma" + ("\nSin registros." if not rows else ""), buttons)

    def owner_detail(self, d):
        self.owner()
        row = self.db.get(OWNER_RESOURCES[d["resource"]], d["id"])
        if not row:
            raise DomainError("NOT_FOUND", "Registro no disponible.")
        buttons = []
        if d["resource"] == "tenants":
            buttons += [
                [self.button("Abrir negocio completo", "workspace", tid=row.id)],
                [self.button("Suspender", "tenant_suspend", id=row.id)],
                [self.button("Conceder días / reactivar", "tenant_extend", id=row.id)],
            ]
        elif d["resource"] == "bots":
            buttons += [[self.button("Abrir configuración", "bot", tid=row.tenant_id, id=row.id)]]
        elif d["resource"] == "saas":
            buttons += [[self.button("Configurar precio Stars", "saas_price", id=row.id)]]
        elif d["resource"] == "support":
            buttons += [[self.button("Responder al creador", "ticket_reply", id=row.id)]]
        audit(
            self.db,
            None,
            self.user.id,
            "TELEGRAM_PLATFORM_RECORD_VIEWED",
            row.id,
            {"resource": d["resource"]},
        )
        self.say(self.describe(row), buttons)
