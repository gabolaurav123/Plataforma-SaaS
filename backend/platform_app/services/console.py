"""Telegram-native creator and owner console. No HTTP server or Mini App is involved.

Buttons are opaque, expire, and are bound to the bot and verified Telegram actor.
Every action rechecks membership/role; dialogs survive restarts in PostgreSQL.
"""

import json
import logging
from contextlib import nullcontext
from decimal import InvalidOperation
from datetime import datetime, timezone
from sqlalchemy import select
from pydantic import ValidationError
from .. import models as m
from ..db import get_scoped
from ..errors import DomainError
from ..security import require_role, redact, EffectiveRole, ROLES
from ..api.auth import TenantContext
from ..api.schemas import BotCreate, TextSave, PlanCreate, MemberCreate
from ..api.creator import save_plan
from ..api.resources import RESOURCES, calculate_analytics
from ..api.serialization import public
from . import tenants, crm
from .common import send, audit, enqueue
from .texts import DEFAULT_TEXTS

RES_LABELS = {
    "contacts": "ui_4a756c24fe",
    "subscriptions": "ui_a9426ae3db",
    "payments": "ui_a3b4f095b9",
    "receipts": "ui_92485e58f8",
    "conversations": "ui_a8897541eb",
    "team": "ui_2de59a82f0",
    "campaigns": "ui_8a25c99c04",
    "automations": "ui_c932d29a53",
    "audit": "ui_ce2ae67021",
    "plans": "ui_00ec16f7a6",
    "channels": "ui_75702fe412",
    "charges": "ui_7d3cadebec",
    "notes": "ui_8a6172e21a",
    "tasks": "ui_ab434464d1",
    "coupons": "ui_37fccdea61",
    "referrals": "ui_c203da909d",
    "links": "ui_f1a5125bb4",
    "usage": "ui_522438169f",
    "flags": "ui_ce8e3b6256",
    "providers": "ui_719dcdb45d",
    "tags": "ui_137cb944c5",
    "prices": "ui_efdf4a8868",
    "billing": "ui_a5b41aaecd",
    "bots": "ui_46c7714c73",
}
FIELD_LABELS = {
    "name": "ui_562bb15757",
    "description": "ui_ee00b96fff",
    "short_description": "ui_d4a256c2db",
    "support_username": "ui_29e7e810a3",
    "terms": "ui_60eaf1f65f",
    "privacy": "ui_52233e2c4d",
    "refund": "ui_5a21795626",
    "WELCOME": "ui_f5f273d88e",
    "SUPPORT": "ui_a0bc738463",
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
    # These master commands only render navigation; business mutations retain savepoint rollback.
    navigation_only = (
        not bot
        and not query
        and message.get("text", "").strip()
        in {
            "/start",
            "/menu",
            "/cancel",
            "/admin",
            "/id",
        }
    )
    try:
        with nullcontext() if navigation_only else session.begin_nested():
            ui.run(message, query)
    except (DomainError, ValidationError, ValueError, InvalidOperation) as error:
        # Never echo validation input (which might contain a pasted token).
        from .i18n import error_text

        text = error_text(error, ui.language)
        ui.say("⚠️ " + text + ui.t("ui_46ce881775"))
    except Exception:
        logging.getLogger("platform.console").error(
            "console_operation_failed", extra={"bot_key": ui.key, "update_id": update["update_id"]}
        )
        ui._state = None
        ui.say(ui.t("operation_failed"))


class Console:
    def __init__(self, runtime, session, bot, update, actor):
        self.r, self.db, self.bot, self.update, self.actor = runtime, session, bot, update, actor
        self.key, self.count = bot.id if bot else "master", 0
        self.user = (
            tenants.upsert_user(session, actor)
            if not bot
            else session.scalar(select(m.PlatformUser).where(m.PlatformUser.telegram_user_id == actor["id"]))
        )
        self._state = None
        self._roles = {}
        self.render_admin = False
        self.language = self.user.locale if self.user else actor.get("language_code", "es")

    def t(self, key, **values):
        from .i18n import t

        return t(key, self.language, **values)

    def caption(self, value):
        from .i18n import CATALOG

        return self.t(value) if value in CATALOG else value

    def date(self, value):
        if not value:
            return "—"
        from zoneinfo import ZoneInfo

        if not hasattr(self, "_date_preferences"):
            row = (
                self.db.scalar(
                    select(m.BotSettings).where(
                        m.BotSettings.bot_id == self.bot.id, m.BotSettings.tenant_id == self.bot.tenant_id
                    )
                )
                if self.bot
                else None
            )
            self._date_preferences = row.preferences if row else {}
        preferences = self._date_preferences
        pattern = {"DMY": "%d/%m/%Y", "MDY": "%m/%d/%Y", "YMD": "%Y-%m-%d"}.get(
            preferences.get("date_format"), "%d/%m/%Y"
        )
        return (
            datetime.fromtimestamp(value, timezone.utc)
            .astimezone(ZoneInfo(preferences.get("timezone", "UTC")))
            .strftime(pattern + " %H:%M %Z")
        )

    def button(self, label, action, **data):
        if self.bot and self.render_admin and not action.startswith(("biz:", "__")):
            action = "biz:" + action
        row = m.ConsoleButton(
            id=m.uid(),
            bot_key=self.key,
            telegram_user_id=self.actor["id"],
            action=action,
            data=data,
            expires_at=m.now() + 3600,
        )
        self.db.add(row)
        return {"text": self.caption(label)[:64], "callback_data": "ui:" + row.id}

    def say(self, text, buttons=None, markup=None):
        self.count += 1
        state = self.state()
        footer = ([self.button(self.t("back"), "__back")] if state.navigation else []) + [
            self.button(self.t("home"), "home")
        ]
        if state.data:
            footer.append(self.button(self.t("cancel"), "__cancel"))
        return send(
            self.db,
            self.bot,
            self.actor["id"],
            text[:4096],
            f"console:{self.key}:{self.update['update_id']}:{self.count}",
            reply_markup=markup or {"inline_keyboard": (buttons or []) + [footer]},
            service_message=True,
            ingested_at_ms=self.update.get("_ingested_at_ms"),
        )

    def state(self):
        if self._state is not None:
            return self._state
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
            row.navigation, row.screen = [], {}
        self._state = row
        return row

    def ask(self, flow, prompt, **data):
        if self.bot and self.render_admin:
            data["business"] = True
        row = self.state()
        row.data, row.expires_at = {"flow": flow, **data}, m.now() + 86400
        self.say(prompt + self.t("ui_b1e3e1d989"))

    def owner(self):
        if self.actor["id"] not in self.r.settings.owner_ids:
            raise DomainError(
                "OWNER_REQUIRED", "Solo el administrador de la plataforma puede abrir esta opción.", 403
            )

    def ctx(self, tid, permission="read"):
        if self.bot and self.bot.tenant_id != tid:
            raise DomainError("NOT_FOUND", "No tienes acceso a este negocio.", 404)
        if not self.user:
            raise DomainError("NOT_FOUND", "No tienes acceso a este negocio.", 404)
        if self.bot:
            role = self.business_role()
            if not role:
                raise DomainError("NOT_FOUND", "No tienes acceso a este negocio.", 404)
            require_role(role, permission)
            tenants.entitlement(
                self.db, tid, writable=permission not in {"read", "billing", "export", "stats", "payments"}
            )
            return TenantContext(tid, self.user.id, self.actor["id"], role)
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
        obj = get_scoped(self.db, model, entity_id, tid)
        if self.bot:
            bid = getattr(obj, "bot_id", None)
            if isinstance(obj, m.ManagedBot):
                bid = obj.id
            if isinstance(obj, m.BankReceipt):
                bid = self.db.get(m.Payment, obj.payment_id).bot_id
            if isinstance(obj, m.Message):
                bid = self.db.get(m.Conversation, obj.conversation_id).bot_id
            if isinstance(obj, (m.PlanPrice, m.PlanChannel)):
                bid = self.db.get(m.Plan, obj.plan_id).bot_id
            if bid and bid != self.bot.id:
                raise DomainError("NOT_FOUND", "Recurso no disponible en este bot.", 404)
        return obj

    def business_role(self):
        if not self.bot or not self.user:
            return None
        if self.bot.id in self._roles:
            return self._roles[self.bot.id]
        tenant = self.db.get(m.Tenant, self.bot.tenant_id)
        if tenant.owner_user_id == self.user.id:
            role = EffectiveRole("OWNER")
        elif self.actor["id"] in self.r.settings.owner_ids:
            audit(self.db, tenant.id, self.user.id, "PLATFORM_OWNER_BOT_ACCESS", self.bot.id)
            role = EffectiveRole("OWNER")
        else:
            member = self.db.scalar(
                select(m.BotAdmin).where(
                    m.BotAdmin.bot_id == self.bot.id,
                    m.BotAdmin.tenant_id == tenant.id,
                    m.BotAdmin.user_id == self.user.id,
                    m.BotAdmin.active.is_(True),
                )
            )
            role = (
                EffectiveRole(
                    member.role,
                    member.permissions if member.role == "CUSTOM" else ROLES.get(member.role, set()),
                )
                if member
                else None
            )
        self._roles[self.bot.id] = role
        return role

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
                self.say(self.t("ui_6c4913e8ec"))
                return
            action, data = row.action, dict(row.data)
            row.used_at = m.now()
            state = self.state()
            if action == "__cancel":
                state.data = {}
                action, data = ("biz:home" if self.bot and self.business_role() else "home"), {}
            elif action == "__back":
                previous = list(state.navigation or [])
                target = (
                    previous.pop()
                    if previous
                    else {"action": "biz:home" if self.bot and self.business_role() else "home", "data": {}}
                )
                state.navigation, state.screen, state.data = previous, target, {}
                action, data = target["action"], target["data"]
            else:
                base = action.removeprefix("biz:")
                screens = {
                    "home",
                    "admin",
                    "workspace",
                    "connection_menu",
                    "billing",
                    "platform_invoices",
                    "platform_invoice",
                    "finance_list",
                    "finance_detail",
                    "platform_methods",
                    "saas_plans",
                    "platform_finance",
                    "list",
                    "detail",
                    "plans",
                    "plan",
                    "memberships",
                    "policies",
                    "policy",
                    "support",
                    "help",
                    "filters",
                    "methods",
                    "method_edit",
                    "templates",
                    "template_select",
                    "settings",
                    "settings_menu",
                    "languages",
                    "reports",
                    "stats",
                    "checklist",
                    "notifications",
                    "contact_plan_filter",
                    "invite_history",
                    "owner_list",
                    "owner_detail",
                }
                if base in screens:
                    target = {"action": action, "data": data}
                    if base in {"home", "admin"}:
                        state.navigation = []
                    elif state.screen and state.screen != target:
                        state.navigation = [*(state.navigation or []), state.screen][-15:]
                    state.screen = target
            if self.bot and not action.startswith("biz:"):
                from .console_customer import dispatch

                dispatch(self, action, data)
            elif action.startswith("biz:"):
                from .console_business import dispatch

                dispatch(self, action[4:], data)
            else:
                self.dispatch(action, data)
            return
        text = message.get("text", "").strip()
        command = text.split(maxsplit=1)[0].split("@", 1) if text else []
        if (
            command
            and command[0].lower() == "/id"
            and (
                len(command) == 1
                or command[1].lower()
                == (self.bot.username if self.bot else self.r.settings.master_bot_username)
                .lstrip("@")
                .lower()
            )
        ):
            if self.bot and not self.user:
                self.user = tenants.upsert_user(self.db, self.actor)
            self.say(self.t("ui_67e865c7ff", p0=self.actor["id"]))
            return
        if self.bot and message.get("reply_to_message"):
            from .inbox import native_reply

            if native_reply(self, message):
                return
            if self.business_role():
                self.say(self.t("inbox_reply_target"))
                return
        if self.bot and self.state().data.get("business") and not self.business_role():
            self.state().data = {}
            self.say(self.t("ui_1202515e3b"))
            return
        if text.startswith(("/start", "/admin", "/cancel", "/menu")):
            state = self.state()
            state.navigation = []
            state.screen = {"action": "biz:home" if self.bot and self.business_role() else "home", "data": {}}
        if (
            self.bot
            and self.business_role()
            and (
                text.startswith(("/start", "/admin", "/cancel", "/menu")) or self.state().data.get("business")
            )
        ):
            from .console_business import message as business_message

            business_message(self, message)
        elif self.bot:
            from .console_customer import message as customer_message

            customer_message(self, message)
        elif text.startswith(("/start", "/cancel", "/menu")):
            self.state().data = {}
            self.home()
        elif text.startswith("/admin"):
            self.admin()
        elif text.startswith(("/support", "/paysupport")):
            self.ask("ticket", self.t("ui_3eef234094"))
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
            [self.button(self.t("ui_4cf7d4f76d"), "new_workspace")],
            [self.button(self.t("admin_language"), "master_language")],
            [self.button(self.t("ui_cc24326e48"), "help")],
        ]
        if self.actor["id"] in self.r.settings.owner_ids:
            buttons.append([self.button(self.t("ui_e520b01b67"), "admin")])
        self.say(self.t("ui_e9381004a1"), buttons)

    def workspace(self, tid):
        from .console_saas import workspace

        return workspace(self, tid)

    def bot_menu(self, tid, bid):
        bot = self.entity(m.ManagedBot, tid, bid)
        buttons = [[{"text": self.t("ui_b7b48a33c0"), "url": f"https://t.me/{bot.username}"}]]
        for label, action in [
            (self.t("ui_e6bbd34190"), "settings"),
            (self.t("ui_3120002bbd"), "photo"),
            (self.t("ui_2e76cd740b"), "channel"),
            (self.t("ui_dcdac0bd75"), "plans"),
            (self.t("ui_8b360bdff2"), "campaign"),
            (self.t("ui_2990fad4a1"), "automation"),
            (self.t("ui_53342e5e73"), "publish"),
            (self.t("ui_06b64ed69a"), "repair"),
        ]:
            buttons.append([self.button(label, action, tid=tid, id=bid)])
        self.say(
            self.t(
                "ui_40f8e79a34",
                p0=bot.username,
                p1=bot.name,
                p2=bot.status,
                p3=self.t("ui_7392158895") if bot.published else self.t("ui_1ea442a134"),
            ),
            buttons,
        )

    def settings(self, tid, bid):
        self.entity(m.ManagedBot, tid, bid, "configure")
        rows = [
            [self.button(label, "field", tid=tid, id=bid, field=field)]
            for field, label in FIELD_LABELS.items()
        ]
        rows += [[self.button(self.t("ui_b7c2354b76"), "texts", tid=tid, id=bid)]]
        self.say(self.t("ui_3fc99777fe"), rows)

    def dispatch(self, action, d):
        if action in {"master_language", "set_master_language"} and not self.bot:
            from .i18n import LANGUAGES

            if action == "set_master_language":
                if d.get("language") not in LANGUAGES:
                    raise DomainError("INVALID_LANGUAGE", "Idioma no disponible.")
                self.user.locale = self.language = d["language"]
                self.say(self.t("language_saved"))
                self.home()
            else:
                self.say(
                    self.t("admin_language"),
                    [
                        [self.button(name, "set_master_language", language=key)]
                        for key, name in LANGUAGES.items()
                    ],
                )
            return
        from .console_saas import dispatch as saas_dispatch

        if saas_dispatch(self, action, d):
            return
        tid, eid = d.get("tid"), d.get("id")
        if action == "home":
            self.home()
        elif action == "admin":
            self.admin()
        elif action == "master_check":
            self.owner()
            capability = self.r.manager.capabilities()
            self.say(capability["message"] + (self.t("ui_dee82cc957") if not capability["enabled"] else ""))
        elif action == "workspace":
            self.workspace(tid)
        elif action == "new_workspace":
            self.ask("workspace_name", self.t("ui_182239eaa0"))
        elif action == "help":
            self.say(self.t("ui_fddd00f8fc"))
        elif action == "new_bot":
            self.ctx(tid, "configure")
            self.ask("bot_name", self.t("ui_0cfb8d9e14"), tid=tid)
        elif action == "bot":
            self.bot_menu(tid, eid)
        elif action == "settings":
            self.settings(tid, eid)
        elif action == "texts":
            self.entity(m.ManagedBot, tid, eid, "configure")
            self.say(
                self.t("ui_160bab02ef"),
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
                self.t(
                    "ui_2941dd7b25", p0=self.caption(FIELD_LABELS.get(field, field)), p1=str(current)[:1500]
                ),
                **d,
            )
        elif action == "photo":
            self.entity(m.ManagedBot, tid, eid, "configure")
            self.ask("photo", self.t("ui_1de0f3b980"), **d)
        elif action == "channel":
            bot = self.entity(m.ManagedBot, tid, eid, "configure")
            self.say(
                self.t("ui_ae3e57808f"),
                [
                    [{"text": self.t("ui_238c54ad69"), "url": self.r.channels.connect_link(bot)}],
                    [self.button(self.t("ui_fd393ff98d"), "verify_channels", tid=tid, id=eid)],
                ],
            )
        elif action == "verify_channels":
            bot = self.entity(m.ManagedBot, tid, eid, "configure")
            channels = list(self.db.scalars(select(m.Channel).where(m.Channel.bot_id == bot.id)))
            for channel in channels:
                self.r.channels.verify(self.db, bot, channel)
            self.say("\n".join(f"{x.title}: {x.status}" for x in channels) or self.t("ui_4a34e7e770"))
        elif action == "plans":
            self.entity(m.ManagedBot, tid, eid)
            plans = list(self.db.scalars(select(m.Plan).where(m.Plan.bot_id == eid).limit(80)))
            self.say(
                self.t("ui_d73d157040"),
                [[self.button(p.name, "detail", tid=tid, resource="plans", id=p.id)] for p in plans]
                + [[self.button(self.t("ui_6e957e2354"), "new_plan", tid=tid, id=eid)]],
            )
        elif action == "new_plan":
            self.entity(m.ManagedBot, tid, eid, "configure")
            self.ask("plan_name", self.t("ui_b162ddab2e"), tid=tid, bid=eid)
        elif action == "plan_channel":
            self.create_plan({**d, "channel_id": eid})
        elif action == "price":
            self.entity(m.Plan, tid, eid, "configure")
            self.ask(
                "price",
                self.t("ui_5449339399"),
                **d,
            )
        elif action == "plan_toggle":
            row = self.entity(m.Plan, tid, eid, "configure")
            row.active = not row.active
            audit(self.db, tid, self.user.id, "PLAN_CONFIGURED", eid)
            self.say(self.t("ui_b8ad035f75") if row.active else self.t("ui_f183215e53"))
        elif action == "publish":
            bot = self.entity(m.ManagedBot, tid, eid, "configure")
            result = self.r.provisioner.publish(self.db, bot, self.user.id)
            labels = {
                "webhook": self.t("ui_f366f3f9d4"),
                "support_and_policies": self.t("ui_ba4270a01a"),
                "plan": self.t("ui_3aa941210f"),
                "payment_method": "Stars",
                "channel_permissions": self.t("ui_3134bc7741"),
            }
            missing = [labels.get(k, k) for k, v in result["checks"].items() if not v]
            self.say(
                self.t("ui_ae9c996e99") if result["ready"] else self.t("ui_bd1f309cd6") + "\n".join(missing)
            )
        elif action == "repair":
            bot = self.entity(m.ManagedBot, tid, eid, "configure")
            enqueue(
                self.db, "PROVISION", tid, {}, f"native-repair:{bot.id}:{self.update['update_id']}", bot.id
            )
            self.say(self.t("ui_b1a584b2ea"))
        elif action == "stats":
            self.ctx(tid)
            values = calculate_analytics(self.db, tid)
            self.say(
                self.t(
                    "ui_d343e701b4",
                    p0=values["contacts"],
                    p1=values["new_clients"],
                    p2=values["active_subscriptions"],
                    p3=values["pending_receipts"],
                    p4=values["conversion_percent"],
                    p5=values["revenue_minor"],
                )
            )
        elif action == "records":
            self.ctx(tid)
            self.say(
                self.t("ui_f45745c7a1"),
                [[self.button(label, "list", tid=tid, resource=res)] for res, label in RES_LABELS.items()],
            )
        elif action == "list":
            self.list_records(d)
        elif action == "detail":
            self.detail(d)
        elif action == "reply":
            self.entity(m.Conversation, tid, eid, "support")
            self.ask("reply", self.t("ui_476509665c"), **d)
        elif action == "note":
            self.entity(m.Contact, tid, eid, "support")
            self.ask("note", self.t("ui_d0ec90ce99"), **d)
        elif action == "receipt_image":
            row = self.entity(m.BankReceipt, tid, eid, "payments")
            # Decrypt only during delivery. The outbox holds a reference, never image bytes.
            self.say(self.t("ui_8b3fd404e4"), markup={"remove_keyboard": True}).payload = {
                "chat_id": self.actor["id"],
                "receipt_id": row.id,
                "viewer_id": self.actor["id"],
                "caption": self.t("ui_1a92b3d907"),
                "service_message": True,
            }
        elif action == "review":
            self.entity(m.BankReceipt, tid, eid, "payments")
            self.ask("review", self.t("ui_7d4d0bdd1d"), **d)
        elif action == "review_confirm":
            row = self.entity(m.BankReceipt, tid, eid, "payments")
            payment = get_scoped(self.db, m.Payment, row.payment_id, tid)
            bot = get_scoped(self.db, m.ManagedBot, payment.bot_id, tid)
            self.r.receipts.review(
                self.db, bot, row, self.user.id, d["decision"], d["note"], d.get("accept_duplicate", False)
            )
            self.say(self.t("ui_33c12ac706"))
        elif action == "refund":
            row = self.entity(m.PaymentCharge, tid, eid, "payments")
            self.say(
                self.t("ui_b4063a14ee", p0=row.amount_minor, p1=row.currency),
                [[self.button(self.t("ui_2c76fd9a05"), "refund_confirm", **d)]],
            )
        elif action == "refund_confirm":
            row = self.entity(m.PaymentCharge, tid, eid, "payments")
            payment = get_scoped(self.db, m.Payment, row.payment_id, tid)
            bot = get_scoped(self.db, m.ManagedBot, payment.bot_id, tid)
            if not row.refunded_at:
                self.r.payments.providers[payment.provider].refund(self.db, bot, payment, row)
                self.r.payments.refunded_event(self.db, bot, {"telegram_payment_charge_id": row.charge_id})
                audit(self.db, tid, self.user.id, "REFUND_REQUESTED", eid)
            self.say(self.t("ui_5aa3c084f9"))
        elif action == "team_add":
            self.ctx(tid, "team")
            self.ask(
                "team",
                self.t("ui_eaca0caa4f"),
                tid=tid,
            )
        elif action == "team_remove":
            member = self.entity(m.TenantMember, tid, eid, "team")
            if member.role == "OWNER":
                raise DomainError("OWNER_PROTECTED", "No se puede retirar al propietario.")
            member.active = False
            audit(self.db, tid, self.user.id, "TEAM_MEMBER_REMOVED", eid)
            self.say(self.t("ui_7f8b2e2013"))
        elif action == "billing":
            self.ctx(tid, "billing")
            plans = self.db.scalars(select(m.SaaSPlan).where(m.SaaSPlan.active.is_(True)))
            self.say(
                self.t("ui_67ee24434b"),
                [
                    [
                        self.button(
                            self.t(
                                "ui_e5ce07356d", p0=p.name, p1=p.prices.get("XTR", self.t("ui_6c0890281b"))
                            ),
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
                self.t("ui_901226ffad"),
                [[{"text": self.t("ui_a02185f367"), "url": invoice.checkout_url}]],
            )
        elif action in {"campaign", "automation"}:
            self.entity(m.ManagedBot, tid, eid, "sales" if action == "campaign" else "configure")
            self.ask(
                action,
                self.t("ui_101d0950b1") if action == "campaign" else self.t("ui_7b08c54989"),
                tid=tid,
                bid=eid,
            )
        elif action == "campaign_start":
            row = self.entity(m.Campaign, tid, eid, "sales")
            self.say(
                self.t("ui_5729e3bd27", p0=row.name, p1=row.text[:2000]),
                [[self.button(self.t("ui_939dbdae15"), "campaign_confirm", **d)]],
            )
        elif action == "campaign_confirm":
            row = self.entity(m.Campaign, tid, eid, "sales")
            self.r.campaigns.start(self.db, row)
            audit(self.db, tid, self.user.id, "CAMPAIGN_START", eid)
            self.say(self.t("ui_e5003d1479"))
        elif action == "campaign_pause":
            row = self.entity(m.Campaign, tid, eid, "sales")
            if row.status != "COMPLETED":
                row.status = "PAUSED"
            self.say(self.t("ui_0efc143111") + row.status)
        elif action == "automation_toggle":
            row = self.entity(m.AutomationRule, tid, eid, "configure")
            row.active = not row.active
            audit(self.db, tid, self.user.id, "AUTOMATION_CONFIGURED", eid)
            self.say(self.t("ui_21310cfee5") if row.active else self.t("ui_2d464981a8"))
        elif action == "owner_list":
            self.owner_list(d)
        elif action == "owner_detail":
            self.owner_detail(d)
        elif action == "ticket_reply":
            self.owner()
            self.ask("ticket_reply", self.t("ui_91673c23d9"), **d)
        elif action in {"tenant_suspend", "tenant_extend", "saas_price"}:
            self.owner()
            prompts = {
                "tenant_suspend": self.t("ui_757e7b714c"),
                "tenant_extend": self.t("ui_2637e9e48b"),
                "saas_price": self.t("ui_7ffe3151d2"),
            }
            self.ask(action, prompts[action], **d)
        elif action == "tenant_confirm":
            self.owner()
            tenant = self.db.get(m.Tenant, eid)
            if d["operation"] == "suspend":
                tenant.status, tenant.suspended_at = "SUSPENDED", m.now()
                tenant.admin_suspended_at = m.now()
            else:
                self.r.ledger.grant_access(self.db, tenant, d["days"], self.user.id)
            audit(
                self.db,
                eid,
                self.user.id,
                "TELEGRAM_TENANT_" + d["operation"].upper(),
                eid,
                {"reason": d.get("reason"), "days": d.get("days")},
            )
            self.say(self.t("ui_c43c3b68b2"))
        else:
            raise DomainError("UNKNOWN_ACTION", "Esta opción ya no está disponible. Abre /start.")

    def answer(self, text, message):
        from .console_saas import answer as saas_answer

        if saas_answer(self, text, message):
            return
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
                self.t("ui_1d82a0d93a"),
                tid=tid,
                name=text,
            )
        elif flow == "bot_username":
            self.ctx(tid, "configure")
            body = BotCreate(name=d["name"], username=text.lstrip("@"))
            result = self.r.manager.request_creation(self.db, tid, self.user, body.name, body.username)
            self.state().data = {}
            self.say(
                self.t("ui_87c806ea25"),
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
            self.say(self.t("ui_bf25dd557c"))
        elif flow == "photo":
            bot = self.entity(m.ManagedBot, tid, eid, "configure")
            photo = message.get("photo", [])
            file_id = photo[-1]["file_id"] if photo else message.get("document", {}).get("file_id")
            if not file_id:
                raise ValueError()
            data = self.r.clients.master().download(file_id, self.r.settings.max_upload_bytes)
            self.r.provisioner.photo(self.db, bot, data)
            self.state().data = {}
            self.say(self.t("ui_b093486b8e"))
        elif flow.startswith("plan_"):
            self.entity(m.ManagedBot, tid, d["bid"], "configure")
            if flow == "plan_name":
                if not 1 <= len(text) <= 100:
                    raise ValueError()
                self.ask("plan_days", self.t("ui_7eb3af2fa0"), **d, name=text)
            elif flow == "plan_days":
                days = int(text)
                if not 1 <= days <= 3650:
                    raise ValueError()
                self.ask("plan_price", self.t("ui_6454473998"), **d, days=days)
            elif flow == "plan_price":
                price = int(text)
                if not 1 <= price <= 10000:
                    raise ValueError()
                self.ask(
                    "plan_renew",
                    self.t("ui_7a60f3a8f4"),
                    **d,
                    price=price,
                )
            else:
                if text.lower() not in {"sí", "si", "no", "yes", "sim", "não", "nao"}:
                    raise ValueError()
                recurring = text.lower() in {"sí", "si", "yes", "sim"}
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
                    self.t("ui_b3d27ae7e5"),
                    [
                        [self.button(c.title, "plan_channel", **d, recurring=recurring, id=c.id)]
                        for c in channels
                    ]
                    + [
                        [
                            self.button(
                                self.t("ui_f55e0ec28b"), "plan_channel", **d, recurring=recurring, id=None
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
            self.say(self.t("ui_4f0aa24a46"))
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
            self.say(self.t("ui_1fb05be40b"))
        elif flow == "note":
            self.entity(m.Contact, tid, eid, "support")
            if not 1 <= len(text) <= 2000:
                raise ValueError()
            self.db.add(m.InternalNote(tenant_id=tid, contact_id=eid, author_id=self.user.id, text=text))
            self.state().data = {}
            self.say(self.t("ui_60c3c3602d"))
        elif flow == "review":
            receipt = self.entity(m.BankReceipt, tid, eid, "payments")
            if not 5 <= len(text) <= 500:
                raise ValueError()
            self.state().data = {}
            warning = receipt.suspicious and d["decision"] == "APPROVE"
            self.say(
                self.t("ui_61f400df33", p0=d["decision"], p1=text)
                + (self.t("ui_875aaa7522") if warning else ""),
                [
                    [
                        self.button(
                            self.t("ui_340553986a") if warning else self.t("ui_836e14df94"),
                            "review_confirm",
                            **d,
                            note=text,
                            accept_duplicate=warning,
                        )
                    ]
                ],
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
            self.say(self.t("ui_38e9bd3a1f"))
        elif flow in {"campaign", "automation"}:
            self.entity(m.ManagedBot, tid, d["bid"], "sales" if flow == "campaign" else "configure")
            TextSave(value=text)
            if not text:
                raise ValueError()
            tenants.feature(self.db, tid, "campaigns" if flow == "campaign" else "automations")
            if flow == "campaign":
                row = m.Campaign(
                    tenant_id=tid,
                    bot_id=d["bid"],
                    name=self.t("ui_6a2693a2fc") + date(m.now()),
                    text=text,
                    segment={},
                )
            else:
                tenants.check_entity_limit(self.db, tid, "automations", m.AutomationRule)
                row = m.AutomationRule(
                    tenant_id=tid,
                    bot_id=d["bid"],
                    name=self.t("ui_e80081e7a4"),
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
            self.say(self.t("ui_004ed97211"))
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
                self.t("ui_71acd99484") + text,
                f"ticket-reply:{eid}:{self.update['update_id']}",
            )
            ticket.status = "ANSWERED"
            audit(self.db, None, self.user.id, "SUPPORT_TICKET_ANSWERED", eid)
            self.state().data = {}
            self.say(self.t("ui_1fb05be40b"))
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
                self.say(self.t("ui_a50715f097"))
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
                    self.t("ui_2cc34f66e4")
                    + (
                        self.t("ui_7485baa288", p0=details["days"])
                        if "days" in details
                        else self.t("ui_7b4919a546") + text
                    ),
                    [[self.button(self.t("ui_217cc273b5"), "tenant_confirm", id=eid, **details)]],
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
        self.say(self.t("ui_300673ea40"))

    def list_records(self, d):
        if self.bot:
            from .console_business import records

            return records(self, d)
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
            buttons.append(
                [self.button(self.t("ui_17fd6b8557"), "list", tid=tid, resource=res, after=rows[7].id)]
            )
        if res == "team":
            buttons.append([self.button(self.t("ui_abca487850"), "team_add", tid=tid)])
        self.say(
            self.caption(RES_LABELS.get(res, res))
            + (self.t("ui_ee6b79c573") if not rows else self.t("ui_c6511757a1")),
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
            "name": self.t("ui_562bb15757"),
            "first_name": self.t("ui_562bb15757"),
            "username": self.t("ui_63614ffde2"),
            "created_at": self.t("ui_1bba71a511"),
            "updated_at": self.t("ui_8b0062fa48"),
            "status": self.t("ui_98e5acddb6"),
            "text": self.t("ui_d2af31712e"),
            "description": self.t("ui_ee00b96fff"),
            "amount_minor": self.t("ui_0ed3deb925"),
            "amount_xtr": "Stars",
            "currency": self.t("ui_d6919eba9d"),
            "expires_at": self.t("ui_0fb4618723"),
            "current_period_end": self.t("ui_b29e0a896f"),
            "trial_ends_at": self.t("ui_7d8ea9f63f"),
            "starts_at": "Inicio",
            "role": self.t("ui_fb9f51fe92"),
            "active": self.t("ui_723858144b"),
            "auto_renew": self.t("ui_7aa4c52172"),
            "duration_days": self.t("ui_4ea54faa94"),
            "recurring": "Recurrente",
            "last_error_code": self.t("ui_4fc874c44c"),
            "run_at": "Programado",
            "attempts": self.t("ui_3a32ca0d5d"),
            "kind": "Tipo",
            "action": self.t("ui_212e06c386"),
            "stage": "Etapa",
            "subject": self.t("ui_49cffbf85a"),
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
                value = self.t("ui_7392158895") if value else self.t("ui_1ea442a134")
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
            self.say(self.t("ui_fad8976f20", p0=price.amount_minor if price else self.t("ui_6c0890281b")))
            buttons += [
                [
                    self.button(self.t("ui_6918ce851a"), "price", **d),
                    self.button(
                        self.t("ui_7ef1cd2d34") if row.active else self.t("ui_8e38c2571d"), "plan_toggle", **d
                    ),
                ]
            ]
        elif res == "contacts":
            buttons += [[self.button(self.t("ui_555fe228de"), "note", **d)]]
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
                "\n\n".join(f"{x.direction}: {x.text[:450]}" for x in reversed(messages))
                or self.t("ui_a89c6b90fb")
            )
            buttons += [[self.button(self.t("ui_4d0c997ac7"), "reply", **d)]]
        elif res == "receipts":
            buttons += [[self.button(self.t("ui_c66894eaff"), "receipt_image", **d)]]
            for label, decision in [
                ("Aprobar", "APPROVE"),
                ("Rechazar", "REJECT"),
                (self.t("ui_5af6139fd1"), "REQUEST_NEW"),
                (self.t("ui_c82f472089"), "SUSPICIOUS"),
            ]:
                buttons.append([self.button(label, "review", **d, decision=decision)])
        elif res == "charges" and not row.refunded_at:
            buttons += [[self.button(self.t("ui_7d97958d69"), "refund", **d)]]
        elif res == "team" and row.role != "OWNER":
            buttons += [[self.button(self.t("ui_5a21a58609"), "team_remove", **d)]]
        elif res == "campaigns":
            buttons += [
                [
                    self.button(self.t("ui_4371521949"), "campaign_start", **d),
                    self.button(self.t("ui_cd25ee5b1d"), "campaign_pause", **d),
                ]
            ]
        elif res == "automations":
            buttons += [
                [
                    self.button(
                        self.t("ui_7ef1cd2d34") if row.active else self.t("ui_8e38c2571d"),
                        "automation_toggle",
                        **d,
                    )
                ]
            ]
        self.say(self.describe(row), buttons)

    def admin(self):
        self.owner()
        audit(self.db, None, self.user.id, "TELEGRAM_PLATFORM_VIEWED")
        rows = [
            [self.button(self.t("ui_340317c5fc"), "platform_dashboard")],
            [self.button(self.t("ui_83fb2f2268"), "platform_finance")],
            [self.button(self.t("ui_e38033fedf"), "owner_list", resource="tenants", status="TRIAL")],
        ]
        rows += [
            [self.button(label, "owner_list", resource=res)]
            for res, label in {
                "tenants": self.t("ui_2b17081bee"),
                "users": self.t("ui_ea53e76c4a"),
                "bots": self.t("ui_46c7714c73"),
                "jobs": self.t("ui_4bb3897f18"),
                "audit": self.t("ui_4a6f1afd1a"),
                "support": self.t("ui_b06aabeb8e"),
                "saas": self.t("ui_c8f7c87d4b"),
            }.items()
        ]
        rows.append([self.button(self.t("ui_65e5fa97d0"), "master_check")])
        self.say(self.t("ui_50b6359219"), rows)

    def owner_list(self, d):
        self.owner()
        model = OWNER_RESOURCES[d["resource"]]
        query = select(model)
        if d.get("status") and hasattr(model, "status"):
            query = query.where(model.status == d["status"])
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
                [
                    self.button(
                        self.t("ui_17fd6b8557"),
                        "owner_list",
                        resource=d["resource"],
                        status=d.get("status"),
                        after=rows[7].id,
                    )
                ]
            )
        self.say(self.t("ui_533d8437e1") + (self.t("ui_ee6b79c573") if not rows else ""), buttons)

    def owner_detail(self, d):
        self.owner()
        row = self.db.get(OWNER_RESOURCES[d["resource"]], d["id"])
        if not row:
            raise DomainError("NOT_FOUND", "Registro no disponible.")
        buttons = []
        if d["resource"] == "tenants":
            buttons += [
                [self.button(self.t("ui_00fe4fe3ac"), "workspace", tid=row.id)],
                [self.button(self.t("ui_72f47df8c3"), "tenant_suspend", id=row.id)],
                [self.button(self.t("ui_016c1e250b"), "tenant_extend", id=row.id)],
            ]
        elif d["resource"] == "bots":
            buttons += [[self.button(self.t("ui_b28640d7df"), "bot", tid=row.tenant_id, id=row.id)]]
        elif d["resource"] == "saas":
            buttons += [[self.button(self.t("ui_77bbf98bcc"), "saas_terms", id=row.id)]]
        elif d["resource"] == "support":
            buttons += [[self.button(self.t("ui_2a1b0bdc1f"), "ticket_reply", id=row.id)]]
        audit(
            self.db,
            None,
            self.user.id,
            "TELEGRAM_PLATFORM_RECORD_VIEWED",
            row.id,
            {"resource": d["resource"]},
        )
        self.say(self.describe(row), buttons)
