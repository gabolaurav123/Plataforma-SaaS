"""Daily administration lives in the customer's own bot, behind bot-scoped roles."""

from datetime import datetime
from sqlalchemy import select, func, exists
from .. import models as m
from ..errors import DomainError
from ..security import ROLES
from . import business as b
from .common import enqueue, audit
from .i18n import LANGUAGES
from .reporting import bounds

MODELS = {
    "contacts": m.Contact,
    "subscriptions": m.Subscription,
    "plans": m.Plan,
    "payments": m.Payment,
    "receipts": m.BankReceipt,
    "channels": m.Channel,
    "invitations": m.AccessOffer,
    "campaigns": m.Campaign,
    "conversations": m.Conversation,
    "team": m.BotAdmin,
    "reports": m.Report,
    "automations": m.AutomationRule,
    "audit": m.AuditLog,
    "charges": m.PaymentCharge,
    "provider_events": m.ProviderEvent,
}
PERMISSIONS = {
    "payments": "payments",
    "receipts": "payments",
    "charges": "payments",
    "provider_events": "payments",
    "team": "team",
    "invitations": "subscriptions",
    "channels": "channels",
    "reports": "export",
    "campaigns": "sales",
    "automations": "configure",
    "audit": "configure",
    "conversations": "support",
}
LABELS = {
    "contacts": "users",
    "campaigns": "broadcasts",
    "conversations": "inbox",
    "automations": "automation",
    "charges": "payments",
    "provider_events": "payments",
}


def context(ui, permission="read"):
    if not ui.bot:
        raise DomainError("CHILD_BOT_REQUIRED", "Abre tu propio bot para administrar el negocio.")
    result = ui.ctx(ui.bot.tenant_id, permission)
    ui.render_admin = True
    ui.language = ui.user.locale
    return result


def settings(ui):
    return ui.db.scalar(
        select(m.BotSettings).where(
            m.BotSettings.bot_id == ui.bot.id, m.BotSettings.tenant_id == ui.bot.tenant_id
        )
    )


def home(ui):
    role = context(ui).role
    ui.state().data = {}
    menu = [
        ("dashboard", "dashboard", "stats"),
        ("users", "list", "read"),
        ("subscriptions", "list", "read"),
        ("plans", "list", "read"),
        ("payments", "list", "payments"),
        ("methods", "methods", "payment_config"),
        ("channels", "list", "channels"),
        ("invitations", "list", "subscriptions"),
        ("broadcasts", "list", "sales"),
        ("messages", "templates", "configure"),
        ("languages", "languages", "read"),
        ("stats", "stats", "stats"),
        ("reports", "reports", "export"),
        ("settings", "settings_menu", "configure"),
        ("team", "list", "team"),
        ("receipts", "list", "payments"),
        ("inbox", "list", "support"),
        ("automation", "list", "configure"),
        ("audit", "list", "configure"),
        ("help", "help", "read"),
    ]
    resources = {
        "users": "contacts",
        "broadcasts": "campaigns",
        "inbox": "conversations",
        "automation": "automations",
    }
    buttons = [[ui.button(ui.t("checklist"), "checklist")]] if "configure" in role.permissions else []
    visible = []
    for label, action, permission in menu:
        if permission in role.permissions:
            visible.append(ui.button(ui.t(label), action, resource=resources.get(label, label)))
    buttons += [visible[index : index + 2] for index in range(0, len(visible), 2)]
    buttons += [
        [ui.button(ui.t("preview"), "preview")],
        [
            {
                "text": ui.t("ui_2ad9d2c41c"),
                "url": "https://t.me/" + ui.r.settings.master_bot_username.lstrip("@"),
            }
        ],
    ]
    ui.say(
        ui.t("admin_mode")
        + ui.t("ui_bc5ae47b3c", p0=ui.bot.name, p1=ui.bot.username, p2=role)
        + ui.t("select"),
        buttons,
    )


def message(ui, message):
    context(ui)
    text = message.get("text", "").strip()
    if text.startswith(("/start", "/admin", "/cancel", "/menu")):
        home(ui)
    elif ui.state().data.get("flow", "").startswith("biz:"):
        answer(ui, text, message)
    elif ui.state().data.get("business"):
        ui.answer(text, message)
    else:
        home(ui)


def record_query(ui, resource, filters=None):
    context(ui, PERMISSIONS.get(resource, "read"))
    if resource not in MODELS:
        raise DomainError("NOT_FOUND", "Apartado no disponible.")
    model = MODELS[resource]
    query = select(model).where(model.tenant_id == ui.bot.tenant_id)
    if resource == "provider_events":
        query = query.where(m.ProviderEvent.account_key == ui.bot.id)
    elif resource == "receipts":
        query = query.join(m.Payment, m.Payment.id == m.BankReceipt.payment_id).where(
            m.Payment.bot_id == ui.bot.id
        )
    elif resource == "audit":
        # Business audit records carry a bot ID in context or reference an entity of this bot.
        bot_entities = (
            select(m.Subscription.id)
            .where(m.Subscription.bot_id == ui.bot.id)
            .union_all(
                select(m.Payment.id).where(m.Payment.bot_id == ui.bot.id),
                select(m.Plan.id).where(m.Plan.bot_id == ui.bot.id),
                select(m.Contact.id).where(m.Contact.bot_id == ui.bot.id),
                select(m.Channel.id).where(m.Channel.bot_id == ui.bot.id),
                select(m.BotAdmin.id).where(m.BotAdmin.bot_id == ui.bot.id),
                select(m.AccessOffer.id).where(m.AccessOffer.bot_id == ui.bot.id),
            )
        )
        query = query.where(
            (m.AuditLog.entity_id == ui.bot.id)
            | m.AuditLog.entity_id.in_(bot_entities)
            | (m.AuditLog.data["bot_id"].as_string() == ui.bot.id)
        )
    else:
        query = query.where(model.bot_id == ui.bot.id)
    f = filters or {}
    if f.get("contact_id") and hasattr(model, "contact_id"):
        b.entity(ui.db, m.Contact, f["contact_id"], ui.bot)
        query = query.where(model.contact_id == f["contact_id"])
    if f.get("status") and hasattr(model, "status"):
        query = query.where(model.status == f["status"])
    if resource == "contacts":
        active = exists(
            select(m.Subscription.id).where(
                m.Subscription.contact_id == m.Contact.id,
                m.Subscription.bot_id == ui.bot.id,
                m.Subscription.status == "ACTIVE",
                m.Subscription.expires_at > m.now(),
            )
        )
        if f.get("segment") == "active":
            query = query.where(active)
        elif f.get("segment") == "without":
            query = query.where(~active)
        elif f.get("segment") == "expiring":
            query = query.where(
                exists(
                    select(m.Subscription.id).where(
                        m.Subscription.contact_id == m.Contact.id,
                        m.Subscription.bot_id == ui.bot.id,
                        m.Subscription.status == "ACTIVE",
                        m.Subscription.expires_at.between(m.now() + 1, m.now() + 7 * 86400),
                    )
                )
            )
        elif f.get("segment") == "never_bought":
            query = query.where(
                ~exists(
                    select(m.Payment.id).where(
                        m.Payment.contact_id == m.Contact.id,
                        m.Payment.bot_id == ui.bot.id,
                        m.Payment.status == "APPROVED",
                    )
                )
            )
        if f.get("search"):
            term = f["search"][:100].replace("%", "\\%").replace("_", "\\_")
            query = query.where(
                m.Contact.first_name.ilike("%" + term + "%", escape="\\")
                | m.Contact.username.ilike("%" + term.lstrip("@") + "%", escape="\\")
                | (m.Contact.telegram_user_id == int(term) if term.isdigit() else False)
            )
        if f.get("plan_id"):
            query = query.where(
                exists(
                    select(m.Subscription.id).where(
                        m.Subscription.contact_id == m.Contact.id,
                        m.Subscription.bot_id == ui.bot.id,
                        m.Subscription.plan_id == f["plan_id"],
                        m.Subscription.status == "ACTIVE",
                        m.Subscription.expires_at > m.now(),
                    )
                )
            )
    if resource == "subscriptions":
        if f.get("origin"):
            query = query.where(m.Subscription.origin == f["origin"])
        if f.get("segment") == "expiring":
            query = query.where(
                m.Subscription.status == "ACTIVE",
                m.Subscription.expires_at.between(m.now() + 1, m.now() + 7 * 86400),
            )
    return query


def records(ui, d):
    res = d["resource"]
    query = record_query(ui, res, d.get("filters"))
    model = MODELS[res]
    if d.get("after"):
        query = query.where(model.id > d["after"])
    rows = list(ui.db.scalars(query.order_by(model.id).limit(9)))
    buttons = [[ui.button(ui.label(row), "detail", resource=res, id=row.id)] for row in rows[:8]]
    if len(rows) > 8:
        buttons.append(
            [ui.button(ui.t("next"), "list", resource=res, after=rows[7].id, filters=d.get("filters", {}))]
        )
    creates = {
        "plans": "plan_new",
        "channels": "channel",
        "invitations": "invite_new",
        "campaigns": "campaign",
        "team": "team_new",
        "automations": "automation",
    }
    creation_permissions = {
        "plans": "configure",
        "channels": "channels",
        "invitations": "subscriptions",
        "campaigns": "sales",
        "team": "team",
        "automations": "configure",
    }
    if res in creates and creation_permissions[res] in ui.business_role().permissions:
        buttons.append([ui.button(ui.t("new"), creates[res], tid=ui.bot.tenant_id, id=ui.bot.id)])
    if res in {"contacts", "subscriptions", "payments", "receipts"}:
        buttons.append([ui.button(ui.t("ui_e9d7121d24"), "filters", resource=res)])
    if res == "payments":
        buttons.append([ui.button(ui.t("ui_1bb0a4e79f"), "list", resource="provider_events")])
    label = LABELS.get(res, res)
    ui.say(ui.t(label) + ("\n" + ui.t("empty") if not rows else ""), buttons)


def plan_detail(ui, plan):
    context(ui)
    prices = list(
        ui.db.scalars(
            select(m.PlanPrice).where(
                m.PlanPrice.plan_id == plan.id, m.PlanPrice.tenant_id == ui.bot.tenant_id
            )
        )
    )
    text = ui.t("ui_780b2bad8c", p0=plan.name, p1=plan.description, p2=plan.duration_days) + "\n".join(
        f"{x.provider}: {b.money(x.amount_minor, x.currency)}" for x in prices
    )
    text += ui.t(
        "ui_fe2ba13be4",
        p0=plan.active,
        p1=plan.visible,
        p2=bool(plan.archived_at),
        p3=plan.recurring,
        p4=len(b.plan_channels(ui.db, plan)),
    )
    fields = {
        "name": ui.t("ui_562bb15757"),
        "description": ui.t("ui_ee00b96fff"),
        "duration_days": ui.t("ui_d5a804455b"),
        "benefits": ui.t("ui_81ed84007e"),
        "purchase_message": ui.t("ui_ef02fbd26e"),
        "sort_order": ui.t("ui_997dfc14fb"),
        "product_kind": ui.t("ui_9f093c955f"),
    }
    rows = (
        [[ui.button(label, "plan_field", id=plan.id, field=field)] for field, label in fields.items()]
        if "configure" in ui.business_role().permissions
        else []
    )
    rows += [
        [ui.button(ui.t("ui_0e128d2caf"), "plan_price", id=plan.id)],
        [ui.button(ui.t("ui_e125d78231"), "plan_channels", id=plan.id)],
        [
            ui.button(ui.t("ui_894651580d"), "plan_flag", id=plan.id, field="active"),
            ui.button(ui.t("ui_d2fdf1c25d"), "plan_flag", id=plan.id, field="visible"),
        ],
        [ui.button(ui.t("ui_7aa4c52172"), "plan_flag", id=plan.id, field="recurring")],
        [
            ui.button(ui.t("ui_88f77287cb"), "plan_duplicate", id=plan.id),
            ui.button(ui.t("ui_f35f9141f4"), "plan_archive", id=plan.id),
        ],
    ]
    ui.say(text, rows if "configure" in ui.business_role().permissions else [])


def detail(ui, d):
    res, eid = d["resource"], d["id"]
    query = record_query(ui, res).where(MODELS[res].id == eid)
    row = ui.db.scalar(query)
    if not row:
        raise DomainError("NOT_FOUND", "Registro no disponible.")
    if res == "plans":
        return plan_detail(ui, row)
    if res == "campaigns":
        from .console_campaigns import detail as campaign_detail

        return campaign_detail(ui, row)
    if res == "subscriptions":
        plan, person = ui.db.get(m.Plan, row.plan_id), ui.db.get(m.Contact, row.contact_id)
        date = ui.date
        text = ui.t(
            "ui_cd3f4d9ab5",
            p0=person.first_name,
            p1=person.username or "—",
            p2=person.telegram_user_id,
            p3=plan.name,
            p4=row.status,
            p5=row.origin,
            p6=date(row.starts_at),
            p7=date(row.expires_at),
            p8=max(0, (row.expires_at - m.now()) // 86400),
        )
        can_finance = bool(ui.business_role().permissions & {"payments", "stats"})
        if row.payment_id and can_finance:
            payment = ui.db.get(m.Payment, row.payment_id)
            text += f"\n{payment.provider} · {b.money(payment.amount_minor, payment.currency)}"
        elif not row.payment_id:
            text += ui.t("ui_2371c7c6d6")
        changes = list(
            ui.db.scalars(
                select(m.SubscriptionHistory)
                .where(m.SubscriptionHistory.subscription_id == row.id)
                .order_by(m.SubscriptionHistory.revision.desc())
                .limit(5)
            )
        )
        text += ui.t("ui_a42b9bf9e9") + "\n".join(
            f"{date(x.created_at)} {x.action}: {x.reason}" for x in changes
        )
        buttons = [
            [ui.button(label, "subscription_action", id=eid, action=action)]
            for action, label in [
                ("EXTEND", ui.t("ui_f944c163de")),
                ("RENEW", ui.t("ui_0c92592dde")),
                ("GIFT_DAYS", ui.t("ui_adc6e09d37")),
                ("CANCEL", ui.t("ui_bb9dbb406d")),
                ("SUSPEND", ui.t("ui_72f47df8c3")),
                ("REACTIVATE", ui.t("ui_44f9bcc469")),
                ("CHANGE_PLAN", ui.t("ui_be141d718a")),
            ]
        ]
        ui.say(text, buttons if "subscriptions" in ui.business_role().permissions else [])
    elif res == "invitations":
        link = ui.r.invitations.link(ui.bot, row)
        channels = list(
            ui.db.scalars(
                select(m.Channel.title).where(
                    m.Channel.tenant_id == ui.bot.tenant_id,
                    m.Channel.bot_id == ui.bot.id,
                    m.Channel.id.in_(row.channel_ids),
                )
            )
        )
        ui.say(
            ui.t(
                "ui_623ae6a865",
                p0=link,
                p1=row.uses,
                p2=row.max_uses,
                p3=row.duration_days,
                p4=row.active,
                p5=row.note,
                p6=ui.date(row.expires_at),
                p7=ui.date(row.created_at),
                p8=row.actor_id,
                p9=", ".join(channels) or "—",
            ),
            [
                [ui.button(ui.t("ui_827530dd70"), "invite_toggle", id=eid)],
                [ui.button(ui.t("ui_7148fc85af"), "invite_history", id=eid)],
            ],
        )
    elif res == "team":
        person = ui.db.get(m.PlatformUser, row.user_id)
        ui.say(
            ui.t(
                "ui_d51ddf5f9d",
                p0=person.first_name,
                p1=person.username or "—",
                p2=row.role,
                p3=", ".join(row.permissions or ROLES.get(row.role, [])),
            ),
            [
                [
                    ui.button(ui.t("ui_2f774e1044"), "team_new"),
                    ui.button(ui.t("ui_5a21a58609"), "team_disable", id=eid),
                ]
            ],
        )
    elif res == "contacts":
        gross = dict(
            ui.db.execute(
                select(m.PaymentCharge.currency, func.sum(m.PaymentCharge.amount_minor))
                .join(m.Payment, m.Payment.id == m.PaymentCharge.payment_id)
                .where(m.Payment.contact_id == row.id, m.Payment.bot_id == ui.bot.id)
                .group_by(m.PaymentCharge.currency)
            ).all()
        )
        refunds = dict(
            ui.db.execute(
                select(m.PaymentRefund.currency, func.sum(m.PaymentRefund.amount_minor))
                .join(m.Payment, m.Payment.id == m.PaymentRefund.payment_id)
                .where(m.Payment.contact_id == row.id, m.Payment.bot_id == ui.bot.id)
                .group_by(m.PaymentRefund.currency)
            ).all()
        )
        totals = [(currency, amount - refunds.get(currency, 0)) for currency, amount in gross.items()]
        tags = list(
            ui.db.scalars(
                select(m.Tag.name)
                .join(m.ContactTag, m.ContactTag.tag_id == m.Tag.id)
                .where(m.ContactTag.contact_id == row.id, m.Tag.tenant_id == ui.bot.tenant_id)
            )
        )
        financial = (
            ui.t("ui_da1254a91b")
            + (", ".join(b.money(amount, currency) for currency, amount in totals) or "0")
            if ui.business_role().permissions & {"payments", "stats"}
            else ""
        )
        buttons = [
            [ui.button(ui.t("subscriptions"), "list", resource="subscriptions", filters={"contact_id": eid})]
        ]
        if "payments" in ui.business_role().permissions:
            buttons.append(
                [ui.button(ui.t("payments"), "list", resource="payments", filters={"contact_id": eid})]
            )
        if "subscriptions" in ui.business_role().permissions:
            buttons.append([ui.button(ui.t("ui_dc30db150a"), "grant_new", contact_id=eid)])
        if "support" in ui.business_role().permissions:
            buttons += [
                [ui.button(ui.t("ui_f7d88a8e20"), "note", tid=ui.bot.tenant_id, id=eid)],
                [ui.button(ui.t("ui_140fe22b91"), "contact_tags", id=eid)],
            ]
        ui.say(ui.describe(row) + financial + ui.t("ui_5e5ec188b4") + ", ".join(tags), buttons)
    elif res == "channels":
        ui.say(
            ui.describe(row),
            [[ui.button(ui.t("ui_50e7acc820"), "verify_channels", tid=ui.bot.tenant_id, id=ui.bot.id)]],
        )
    elif res == "reports":
        ui.say(
            ui.t("ui_e63521cd74", p0=row.id[:8], p1=row.status),
            [[ui.button(ui.t("ui_17a000019b"), "report_download", id=row.id)]]
            if row.status == "READY"
            else [],
        )
    elif res == "payments":
        charges = list(
            ui.db.scalars(
                select(m.PaymentCharge)
                .where(
                    m.PaymentCharge.bot_id == ui.bot.id,
                    m.PaymentCharge.tenant_id == ui.bot.tenant_id,
                    m.PaymentCharge.payment_id == row.id,
                )
                .order_by(m.PaymentCharge.created_at.desc())
                .limit(20)
            )
        )
        ui.say(
            ui.t(
                "ui_97f305089c",
                p0=b.money(row.amount_minor, row.currency),
                p1=row.provider,
                p2=row.status,
                p3=ui.date(row.created_at),
            ),
            [
                [
                    ui.button(
                        b.money(charge.amount_minor, charge.currency) + " · " + ui.date(charge.created_at),
                        "detail",
                        resource="charges",
                        id=charge.id,
                    )
                ]
                for charge in charges
            ],
        )
    elif res == "charges":
        refunds = list(
            ui.db.scalars(
                select(m.PaymentRefund)
                .where(
                    m.PaymentRefund.charge_id == row.id,
                    m.PaymentRefund.tenant_id == ui.bot.tenant_id,
                    m.PaymentRefund.bot_id == ui.bot.id,
                )
                .order_by(m.PaymentRefund.created_at)
            )
        )
        remaining = row.amount_minor - sum(x.amount_minor for x in refunds)
        text = ui.t(
            "ui_2e43abe84e",
            p0=b.money(row.amount_minor, row.currency),
            p1=row.provider,
            p2=ui.date(row.created_at),
            p3=b.money(remaining, row.currency),
        )
        text += ui.t("ui_e4dcc603e1") + (
            "\n".join(
                f"{ui.date(x.created_at)} · {b.money(x.amount_minor, x.currency)} · {x.reference} · {x.reason}"
                for x in refunds[-8:]
            )
            or "0"
        )
        ui.say(
            text,
            [
                [
                    ui.button(
                        ui.t("ui_df139d8928") if row.provider == "BANK_TRANSFER" else ui.t("ui_ab226e805f"),
                        "charge_refund",
                        id=row.id,
                    )
                ]
            ]
            if remaining > 0
            else [],
        )
    elif res == "provider_events":
        ui.say(
            ui.t(
                "ui_8cc8c0ea28",
                p0=row.provider,
                p1=row.external_id,
                p2=row.status,
                p3=ui.date(row.created_at),
            ),
            [[ui.button(ui.t("ui_6133ac78fb"), "provider_reconcile", id=row.id)]]
            if row.status in {"FAILED", "REVIEW_REQUIRED"}
            else [],
        )
    elif res == "audit":
        ui.say(ui.describe(row))
    else:
        ui.detail({**d, "tid": ui.bot.tenant_id})


def dispatch(ui, action, d):
    context(ui)
    bid, tid = ui.bot.id, ui.bot.tenant_id
    if action == "campaign" or action.startswith("campaign_"):
        from .console_campaigns import dispatch as campaign_dispatch

        return campaign_dispatch(ui, action, d)
    if action in {"home", "admin", "cancel", "back"}:
        home(ui)
    elif action == "preview":
        from .console_customer import home as customer_home

        ui.render_admin = False
        ui.state().data = {}
        customer_home(ui)
    elif action in {"dashboard", "stats", "stats_period"}:
        context(ui, "stats")
        period = d.get("period", "month")
        if action == "stats":
            ui.say(
                ui.t("stats"),
                [
                    [ui.button(label, "stats_period", period=key)]
                    for key, label in [
                        ("today", ui.t("ui_55133d4e6e")),
                        ("7d", ui.t("ui_bb16b73fa6")),
                        ("month", ui.t("ui_a10168ba1c")),
                        ("previous_month", ui.t("ui_52ee5f657f")),
                    ]
                ],
            )
            return
        start, end = bounds(period, settings(ui).preferences.get("timezone", "UTC"))
        enqueue(
            ui.db,
            "DASHBOARD",
            tid,
            {"viewer_id": ui.actor["id"], "starts_at": start, "ends_at": end},
            f"dashboard:{bid}:{ui.update['update_id']}",
            bid,
        )
        ui.say(ui.t("ui_5d5802aec7"))
    elif action == "list":
        records(ui, d)
    elif action == "detail":
        detail(ui, d)
    elif action == "filters":
        resource = d["resource"]
        rows = [[ui.button(ui.t("ui_bd02b9a7d7"), "list", resource=resource)]]
        if resource == "contacts":
            rows += [
                [ui.button(label, "list", resource=resource, filters={"segment": key})]
                for key, label in [
                    ("active", ui.t("ui_8a933e044a")),
                    ("without", ui.t("ui_5b50af8895")),
                    ("expiring", ui.t("ui_682e4d9e00")),
                    ("never_bought", ui.t("ui_4bc296eeb5")),
                ]
            ]
            rows += [[ui.button(ui.t("ui_74adda1f31"), "contact_search")]]
            rows += [[ui.button(ui.t("ui_c282199b2b"), "contact_plan_filter")]]
        elif resource == "subscriptions":
            rows += [
                [ui.button(label, "list", resource=resource, filters={"status": key})]
                for key, label in [
                    ("ACTIVE", "Activas"),
                    ("EXPIRED", "Vencidas"),
                    ("CANCELLED", "Canceladas"),
                    ("SUSPENDED", "Suspendidas"),
                ]
            ]
            rows += [
                [
                    ui.button(
                        ui.t("ui_c2866fe464"), "list", resource=resource, filters={"origin": "invite_link"}
                    )
                ],
                [
                    ui.button(
                        ui.t("ui_d22dcf2e9b"), "list", resource=resource, filters={"segment": "expiring"}
                    )
                ],
            ]
        else:
            rows += [
                [ui.button(key, "list", resource=resource, filters={"status": key})]
                for key in ["PENDING", "APPROVED", "REJECTED"]
            ]
        ui.say(ui.t("ui_d30cf0cfea"), rows)
    elif action == "contact_search":
        ui.ask("biz:contact_search", ui.t("ui_7d1b7d9be1"))
    elif action == "contact_plan_filter":
        plans = list(
            ui.db.scalars(
                select(m.Plan)
                .where(m.Plan.bot_id == bid, m.Plan.tenant_id == tid)
                .order_by(m.Plan.id)
                .where(m.Plan.id > d.get("after", ""))
                .limit(9)
            )
        )
        rows = [
            [ui.button(p.name, "list", resource="contacts", filters={"plan_id": p.id})] for p in plans[:8]
        ]
        if len(plans) > 8:
            rows.append([ui.button(ui.t("next"), "contact_plan_filter", after=plans[7].id)])
        ui.say(ui.t("plans"), rows)
    elif action == "contact_tags":
        context(ui, "support")
        b.entity(ui.db, m.Contact, d["id"], ui.bot)
        ui.ask("biz:tags", ui.t("ui_a3fb598cec"), id=d["id"])
    elif action == "provider_reconcile":
        context(ui, "payments")
        row = ui.db.scalar(
            record_query(ui, "provider_events").where(m.ProviderEvent.id == d["id"]).with_for_update()
        )
        if not row or row.status not in {"FAILED", "REVIEW_REQUIRED"} or not row.payload_ciphertext:
            raise DomainError(
                "EVENT_UNAVAILABLE", "El evento no está disponible para una nueva comprobación."
            )
        row.status = "PENDING"
        enqueue(
            ui.db,
            "PROVIDER_EVENT",
            tid,
            {"event_id": row.id, "viewer_id": ui.actor["id"]},
            f"provider-reconcile:{row.id}:{ui.update['update_id']}",
            bid,
        )
        audit(ui.db, tid, ui.user.id, "PROVIDER_EVENT_RECHECK_REQUESTED", row.id, {"bot_id": bid})
        ui.say(ui.t("ui_ec306f70d8"))
    elif action in {"charge_refund", "charge_refund_confirm"}:
        context(ui, "payments")
        charge = b.entity(ui.db, m.PaymentCharge, d["id"], ui.bot)
        refunded = (
            ui.db.scalar(
                select(func.sum(m.PaymentRefund.amount_minor)).where(m.PaymentRefund.charge_id == charge.id)
            )
            or 0
        )
        remaining = charge.amount_minor - refunded
        if remaining <= 0:
            return detail(ui, {"resource": "charges", "id": charge.id})
        if action == "charge_refund":
            if charge.provider == "BANK_TRANSFER":
                ui.ask(
                    "biz:bank_refund",
                    ui.t("ui_e0757e6bc4") + charge.currency + ui.t("ui_a94f745d4e"),
                    id=charge.id,
                )
            else:
                ui.say(
                    ui.t("ui_d5d63bad38") + b.money(remaining, charge.currency) + ui.t("ui_d21d088519"),
                    [[ui.button(ui.t("ui_2c76fd9a05"), "charge_refund_confirm", id=charge.id)]],
                )
        elif charge.provider == "BANK_TRANSFER":
            from .refunds import record

            record(ui.db, ui.r, ui.bot, charge, d["amount"], d["reference"], ui.user.id, d["reason"])
            detail(ui, {"resource": "charges", "id": charge.id})
        else:
            enqueue(
                ui.db,
                "REFUND_PAYMENT",
                tid,
                {"charge_id": charge.id, "viewer_id": ui.actor["id"]},
                f"refund-request:{charge.id}",
                bid,
            )
            ui.say(ui.t("ui_eff4701a31"))
    elif action == "plan_new":
        context(ui, "configure")
        ui.ask("biz:new_plan", ui.t("ui_c3d3bde02a"))
    elif action == "plan_field":
        context(ui, "configure")
        plan = b.entity(ui.db, m.Plan, d["id"], ui.bot)
        field = d["field"]
        if field == "product_kind":
            ui.say(
                ui.t("ui_ad52fd2663"),
                [
                    [ui.button(label, "plan_kind", id=plan.id, value=kind)]
                    for kind, label in [
                        ("DIGITAL", ui.t("ui_016a47d628")),
                        ("PHYSICAL", ui.t("ui_4e50ea9483")),
                        ("OFFLINE_SERVICE", ui.t("ui_6ed4641fe9")),
                    ]
                ],
            )
        else:
            ui.ask("biz:plan_field", ui.t("ui_ec42386dd7", p0=field), **d)
    elif action in {"plan_kind", "plan_flag", "plan_duplicate", "plan_archive"}:
        context(ui, "configure")
        plan = b.entity(ui.db, m.Plan, d["id"], ui.bot)
        if action == "plan_kind":
            b.save_plan(ui.db, ui.bot, ui.user.id, {"product_kind": d["value"]}, plan)
        elif action == "plan_flag":
            if d["field"] not in {"active", "visible", "recurring"}:
                raise DomainError("INVALID_FIELD", "Campo no válido.")
            b.save_plan(ui.db, ui.bot, ui.user.id, {d["field"]: not getattr(plan, d["field"])}, plan)
        elif action == "plan_duplicate":
            plan = b.duplicate_plan(ui.db, ui.bot, plan, ui.user.id)
        else:
            plan.archived_at, plan.active, plan.visible = m.now(), False, False
            audit(ui.db, tid, ui.user.id, "PLAN_ARCHIVED", plan.id)
        plan_detail(ui, plan)
    elif action == "plan_price":
        context(ui, "configure")
        ui.say(
            ui.t("ui_aa81fd5fb3"),
            [
                [ui.button(label, "price_currency", id=d["id"], provider=key)]
                for key, label in [
                    ("TELEGRAM_STARS", "Telegram Stars"),
                    ("BANK_TRANSFER", ui.t("ui_4ed786ebd4")),
                    ("STRIPE", "Stripe"),
                    ("PAYPAL", "PayPal"),
                ]
            ],
        )
    elif action == "price_currency":
        context(ui, "configure")
        if d["provider"] == "TELEGRAM_STARS":
            ui.ask("biz:price", ui.t("ui_3651a93138"), **d, currency="XTR")
        else:
            ui.say(
                ui.t("ui_cf2563451a"),
                [
                    [ui.button(currency, "price_amount", **d, currency=currency)]
                    for currency in ["USD", "EUR", "BOB", "MXN", "BRL", "PEN", "COP", "ARS", "CLP", "GBP"]
                ],
            )
    elif action == "price_amount":
        context(ui, "configure")
        ui.ask("biz:price", ui.t("ui_10dc87abb5") + d["currency"] + ":", **d)
    elif action in {"plan_channels", "plan_channel_toggle"}:
        context(ui, "configure")
        plan = b.entity(ui.db, m.Plan, d["id"], ui.bot)
        selected = b.plan_channels(ui.db, plan)
        if action == "plan_channel_toggle":
            cid = d["channel_id"]
            selected = [x for x in selected if x != cid] if cid in selected else selected + [cid]
            b.save_channels(ui.db, ui.bot, plan, selected, ui.user.id)
        channels = list(
            ui.db.scalars(
                select(m.Channel).where(m.Channel.bot_id == bid, m.Channel.tenant_id == tid).limit(30)
            )
        )
        ui.say(
            ui.t("ui_336d23d99f"),
            [
                [
                    ui.button(
                        ("✅ " if c.id in selected else "⬜ ") + c.title,
                        "plan_channel_toggle",
                        id=plan.id,
                        channel_id=c.id,
                    )
                ]
                for c in channels
            ],
        )
    elif action == "subscription_action":
        context(ui, "subscriptions")
        b.entity(ui.db, m.Subscription, d["id"], ui.bot)
        if d["action"] in {"EXTEND", "RENEW", "GIFT_DAYS"}:
            ui.ask("biz:subscription_days", ui.t("ui_9a83846d18"), **d)
        elif d["action"] == "CHANGE_PLAN":
            plans = list(
                ui.db.scalars(
                    select(m.Plan).where(m.Plan.bot_id == bid, m.Plan.archived_at.is_(None)).limit(40)
                )
            )
            ui.say(
                ui.t("ui_3e5dac6074"),
                [
                    [
                        ui.button(
                            p.name, "subscription_confirm", **d, plan_id=p.id, reason=ui.t("ui_d50da7400c")
                        )
                    ]
                    for p in plans
                ],
            )
        else:
            ui.ask("biz:subscription_reason", ui.t("ui_4a00a6a4ca"), **d)
    elif action == "subscription_confirm":
        context(ui, "subscriptions")
        sub = b.entity(ui.db, m.Subscription, d["id"], ui.bot)
        b.manage_subscription(
            ui.db,
            ui.bot,
            sub,
            ui.user.id,
            d["action"],
            f"telegram:{bid}:{ui.update['update_id']}",
            days=d.get("days"),
            plan_id=d.get("plan_id"),
            reason=d.get("reason", ""),
        )
        detail(ui, {"resource": "subscriptions", "id": sub.id})
    elif action in {"grant_new", "grant_plan", "grant_confirm"}:
        context(ui, "subscriptions")
        person = b.entity(ui.db, m.Contact, d["contact_id"], ui.bot)
        if action == "grant_new":
            plans = list(
                ui.db.scalars(
                    select(m.Plan)
                    .where(
                        m.Plan.bot_id == bid,
                        m.Plan.tenant_id == tid,
                        m.Plan.archived_at.is_(None),
                        m.Plan.id > d.get("after", ""),
                    )
                    .order_by(m.Plan.id)
                    .limit(9)
                )
            )
            rows = [[ui.button(p.name, "grant_plan", contact_id=person.id, plan_id=p.id)] for p in plans[:8]]
            if len(plans) > 8:
                rows.append([ui.button(ui.t("next"), "grant_new", contact_id=person.id, after=plans[7].id)])
            ui.say(ui.t("ui_09bfe9f654"), rows)
        elif action == "grant_plan":
            b.entity(ui.db, m.Plan, d["plan_id"], ui.bot)
            ui.ask("biz:grant_days", ui.t("ui_9a83846d18"), **d)
        else:
            plan = b.entity(ui.db, m.Plan, d["plan_id"], ui.bot)
            sub = b.grant_subscription(
                ui.db,
                ui.bot,
                person,
                plan,
                ui.user.id,
                d["days"],
                d["reason"],
                f"manual:{bid}:{ui.update['update_id']}",
            )
            detail(ui, {"resource": "subscriptions", "id": sub.id})
    elif action == "invite_new":
        context(ui, "subscriptions")
        plans = list(
            ui.db.scalars(select(m.Plan).where(m.Plan.bot_id == bid, m.Plan.archived_at.is_(None)).limit(40))
        )
        ui.say(ui.t("ui_9087c1e5b9"), [[ui.button(p.name, "invite_plan", id=p.id)] for p in plans])
    elif action == "invite_plan":
        context(ui, "subscriptions")
        ui.ask("biz:invite", ui.t("ui_6bc9a517bf"), plan_id=d["id"])
    elif action in {"invite_channels", "invite_channel_toggle", "invite_create"}:
        context(ui, "subscriptions")
        plan = b.entity(ui.db, m.Plan, d["plan_id"], ui.bot)
        selected = d.get("channel_ids", b.plan_channels(ui.db, plan))
        if action == "invite_create":
            offer = ui.r.invitations.create(
                ui.db,
                ui.bot,
                ui.user.id,
                plan.id,
                d["days"],
                d["uses"],
                d["expires_at"],
                d.get("note", ""),
                selected,
            )
            ui.db.flush()
            detail(ui, {"resource": "invitations", "id": offer.id})
            return
        if action == "invite_channel_toggle":
            cid = d.pop("channel_id")
            selected = [x for x in selected if x != cid] if cid in selected else selected + [cid]
        values = {**d, "channel_ids": selected}
        channels = list(
            ui.db.scalars(
                select(m.Channel).where(
                    m.Channel.tenant_id == tid,
                    m.Channel.bot_id == bid,
                    m.Channel.id.in_(b.plan_channels(ui.db, plan)),
                )
            )
        )
        rows = [
            [
                ui.button(
                    ("✅ " if c.id in selected else "⬜ ") + c.title,
                    "invite_channel_toggle",
                    **values,
                    channel_id=c.id,
                )
            ]
            for c in channels
        ]
        rows.append([ui.button(ui.t("ui_e586de2fbc"), "invite_create", **values)])
        ui.say(ui.t("ui_07ba25b943"), rows)
    elif action == "invite_history":
        context(ui, "subscriptions")
        offer = b.entity(ui.db, m.AccessOffer, d["id"], ui.bot)
        query = (
            select(m.AccessRedemption, m.Contact)
            .join(m.Contact, m.Contact.id == m.AccessRedemption.contact_id)
            .where(
                m.AccessRedemption.tenant_id == tid,
                m.AccessRedemption.offer_id == offer.id,
                m.Contact.bot_id == bid,
                m.AccessRedemption.id > d.get("after", ""),
            )
        )
        rows = list(ui.db.execute(query.order_by(m.AccessRedemption.id).limit(9)))
        buttons = (
            [[ui.button(ui.t("next"), "invite_history", id=offer.id, after=rows[7][0].id)]]
            if len(rows) > 8
            else []
        )
        ui.say(
            ui.t("ui_b3d92217ef")
            + (
                "\n".join(
                    f"{ui.date(red.created_at)} · {person.first_name} (@{person.username or '—'}) · {person.telegram_user_id}"
                    for red, person in rows[:8]
                )
                or ui.t("empty")
            ),
            buttons,
        )
    elif action == "invite_toggle":
        context(ui, "subscriptions")
        offer = b.entity(ui.db, m.AccessOffer, d["id"], ui.bot)
        offer.active = not offer.active
        audit(ui.db, tid, ui.user.id, "INVITATION_CHANGED", offer.id, {"active": offer.active})
        detail(ui, {"resource": "invitations", "id": offer.id})
    elif action in {"languages", "admin_language", "default_language"}:
        if action == "languages":
            ui.say(
                ui.t("languages"),
                [
                    [ui.button(ui.t("admin_language"), "admin_language")],
                    [ui.button(ui.t("default_language"), "default_language")],
                ],
            )
        else:
            ui.say(
                ui.t("select"),
                [
                    [ui.button(label, "language_save", language=key, target=action)]
                    for key, label in LANGUAGES.items()
                ],
            )
    elif action == "language_save":
        if d["language"] not in LANGUAGES:
            raise DomainError("INVALID_LANGUAGE", "Idioma no soportado.")
        if d["target"] == "default_language":
            context(ui, "configure")
            row = settings(ui)
            row.preferences = {**row.preferences, "language": d["language"]}
        else:
            ui.user.locale = ui.language = d["language"]
        ui.say(ui.t("language_saved"))
    elif action == "reports":
        context(ui, "export")
        ui.say(
            ui.t("reports"),
            [
                [ui.button(label, "report_request", period=key)]
                for key, label in [
                    ("today", ui.t("ui_55133d4e6e")),
                    ("7d", ui.t("ui_bb16b73fa6")),
                    ("month", ui.t("ui_a10168ba1c")),
                    ("previous_month", ui.t("ui_52ee5f657f")),
                ]
            ]
            + [
                [ui.button(ui.t("ui_33b2578969"), "report_custom")],
                [ui.button(ui.t("ui_ee2bc96713"), "list", resource="reports")],
            ],
        )
    elif action == "report_custom":
        context(ui, "export")
        ui.ask("biz:report_period", ui.t("ui_dc5df7685c"))
    elif action == "report_request":
        context(ui, "export")
        start, end = bounds(d["period"], settings(ui).preferences.get("timezone", "UTC"))
        ui.r.reports.request(ui.db, ui.bot, ui.user, start, end)
        ui.say(ui.t("report_queued"))
    elif action == "report_download":
        context(ui, "export")
        row = b.entity(ui.db, m.Report, d["id"], ui.bot)
        if row.status != "READY" or row.expires_at <= m.now():
            raise DomainError("REPORT_EXPIRED", "El reporte caducó. Genera uno nuevo.")
        from .common import send

        send(
            ui.db,
            ui.bot,
            ui.actor["id"],
            ui.t("ui_7ff35f0ced"),
            f"report-download:{row.id}:{ui.update['update_id']}",
            report_id=row.id,
            viewer_id=ui.actor["id"],
            service_message=True,
        )
    elif action == "settings_menu":
        context(ui, "configure")
        ui.say(
            ui.t("settings"),
            [
                [ui.button(ui.t("ui_d0233d6a24"), "settings", tid=tid, id=bid)],
                [ui.button(ui.t("ui_aaaba064e3"), "photo", tid=tid, id=bid)],
                [ui.button(ui.t("ui_43b228654b"), "preference", field="timezone")],
                [ui.button(ui.t("ui_39d54e1a49"), "preference", field="date_format")],
                [ui.button(ui.t("ui_3551ca3347"), "notifications")],
                [ui.button(ui.t("ui_dfee336770"), "languages")],
            ],
        )
    elif action == "preference":
        context(ui, "configure")
        ui.ask(
            "biz:preference",
            ui.t("ui_1aa187550f") if d["field"] == "timezone" else ui.t("ui_32b6efc666"),
            field=d["field"],
        )
    elif action == "checklist":
        row = settings(ui)
        plan_count = ui.db.scalar(
            select(func.count()).select_from(m.Plan).where(m.Plan.bot_id == bid, m.Plan.active.is_(True))
        )
        channel_count = ui.db.scalar(
            select(func.count())
            .select_from(m.Channel)
            .where(m.Channel.bot_id == bid, m.Channel.status == "CONNECTED")
        )
        method_count = ui.db.scalar(
            select(func.count())
            .select_from(m.BotPaymentMethod)
            .where(m.BotPaymentMethod.bot_id == bid, m.BotPaymentMethod.enabled.is_(True))
        )
        checks = [
            (ui.t("ui_d8171a3c63"), ui.bot.status not in {"DISCONNECTED", "PROVISIONING_FAILED"}),
            (ui.t("ui_cd20eb864b"), channel_count > 0),
            (ui.t("ui_5c451c14a5"), plan_count > 0),
            (ui.t("ui_71695c21b6"), method_count > 0),
            (ui.t("ui_be9374267e"), bool(row)),
            ("Idioma", bool(row.preferences.get("language"))),
            ("Publicado", ui.bot.published),
        ]
        ui.say(
            ui.t("ui_9ba422565b") + "\n".join(("✅ " if value else "⚠️ ") + label for label, value in checks),
            [
                [ui.button(ui.t("ui_4907281581"), "channel", tid=tid, id=bid)],
                [ui.button(ui.t("ui_962cc91aa1"), "plan_new")],
                [ui.button(ui.t("ui_87f86c9166"), "methods")],
                [ui.button(ui.t("ui_7398551db8"), "settings", tid=tid, id=bid)],
                [ui.button(ui.t("ui_7b30e6bee5"), "default_language")],
                [ui.button(ui.t("ui_2a16b4b4c8"), "publish", tid=tid, id=bid)],
            ],
        )
    elif action in {"methods", "method_edit", "method_toggle", "method_field"}:
        from .console_payments import dispatch as payment_dispatch

        payment_dispatch(ui, action, d)
    elif action in {"templates", "template_select", "template_edit", "template_restore"}:
        from .console_templates import dispatch as template_dispatch

        template_dispatch(ui, action, d)
    elif action in {"notifications", "notification_toggle"}:
        context(ui, "configure")
        row = settings(ui)
        preferences = dict(row.preferences)
        notifications = dict(preferences.get("notifications", {}))
        labels = {
            "new_sale": ui.t("ui_b17e2d61f1"),
            "new_user": ui.t("ui_d32ea0ea3e"),
            "new_receipt": ui.t("ui_68268f3e43"),
            "cancelled": ui.t("ui_fb02cd914b"),
            "payment_failed": ui.t("ui_6258023058"),
            "vip": ui.t("ui_19c9a8553f"),
            "daily": ui.t("ui_a6fe6d4a43"),
            "weekly": ui.t("ui_ad43ae2f55"),
            "monthly": ui.t("ui_9c0fdb8e59"),
        }
        if action == "notification_toggle":
            if d["key"] not in labels:
                raise DomainError("INVALID_SETTING", "Preferencia no disponible.")
            notifications[d["key"]] = not notifications.get(
                d["key"], d["key"] in {"new_sale", "new_receipt", "payment_failed"}
            )
            row.preferences = {**preferences, "notifications": notifications}
            audit(ui.db, tid, ui.user.id, "NOTIFICATIONS_CONFIGURED", bid)
        ui.say(
            ui.t("ui_8cfe76a625"),
            [
                [
                    ui.button(
                        (
                            "✅ "
                            if notifications.get(key, key in {"new_sale", "new_receipt", "payment_failed"})
                            else "⬜ "
                        )
                        + label,
                        "notification_toggle",
                        key=key,
                    )
                ]
                for key, label in labels.items()
            ],
        )
    elif action in {"team_new", "team_role", "team_custom", "team_custom_toggle", "team_disable"}:
        context(ui, "team")
        if action == "team_new":
            ui.ask("biz:team_user", ui.t("ui_603739e617"))
        elif action == "team_role":
            b.set_admin(
                ui.db,
                ui.bot,
                ui.user.id,
                d["telegram_id"],
                d["role"],
                d.get("permissions"),
                platform_owner=ui.actor["id"] in ui.r.settings.owner_ids,
            )
            ui.say(ui.t("saved"))
        elif action in {"team_custom", "team_custom_toggle"}:
            selected = d.get("permissions", ["read"])
            if action == "team_custom_toggle":
                key = d["permission"]
                selected = [x for x in selected if x != key] if key in selected else selected + [key]
            selected = sorted(set(selected) | {"read"})
            rows = [
                [
                    ui.button(
                        ("✅ " if key in selected else "⬜ ") + key,
                        "team_custom_toggle",
                        telegram_id=d["telegram_id"],
                        permissions=selected,
                        permission=key,
                    )
                ]
                for key in sorted(ROLES["ADMIN"] - {"read"})
            ]
            rows.append(
                [
                    ui.button(
                        ui.t("ui_473aed05f7"),
                        "team_role",
                        telegram_id=d["telegram_id"],
                        role="CUSTOM",
                        permissions=selected,
                    )
                ]
            )
            ui.say(ui.t("ui_7cc6d15c23"), rows)
        else:
            member = b.entity(ui.db, m.BotAdmin, d["id"], ui.bot)
            if member.user_id == ui.db.get(m.Tenant, tid).owner_user_id:
                raise DomainError("OWNER_PROTECTED", "No puedes retirar al propietario.")
            member.active = False
            audit(ui.db, tid, ui.user.id, "BOT_ADMIN_REMOVED", member.id, {"bot_id": bid})
            ui.say(ui.t("saved"))
    elif action == "help":
        ui.say(ui.t("ui_f8ed7dc055"))
    else:
        # Explicit compatibility allowlist: master/owner actions cannot execute in a child bot.
        allowed = {
            "settings",
            "field",
            "texts",
            "photo",
            "channel",
            "verify_channels",
            "publish",
            "repair",
            "note",
            "reply",
            "receipt_image",
            "review",
            "review_confirm",
            "refund",
            "refund_confirm",
            "campaign",
            "campaign_start",
            "campaign_confirm",
            "campaign_pause",
            "automation",
            "automation_toggle",
        }
        if action not in allowed:
            raise DomainError("UNKNOWN_ACTION", "Abre /start para actualizar las opciones.")
        permission = (
            "payments"
            if action.startswith(("review", "receipt", "refund"))
            else "support"
            if action in {"note", "reply"}
            else "sales"
            if action.startswith("campaign")
            else "channels"
            if action in {"channel", "verify_channels"}
            else "configure"
        )
        context(ui, permission)
        if action in {"publish", "verify_channels"}:
            enqueue(
                ui.db,
                "PUBLISH" if action == "publish" else "VERIFY_CHANNELS",
                tid,
                {"viewer_id": ui.actor["id"], "actor_id": ui.user.id},
                f"{action}:{bid}:{ui.update['update_id']}",
                bid,
            )
            ui.say(ui.t("ui_27614b5893"))
        else:
            ui.dispatch(action, {**d, "tid": tid, "id": d.get("id", bid)})


def answer(ui, text, message):
    context(ui)
    state = dict(ui.state().data)
    flow = state.pop("flow")[4:]
    state.pop("business", None)
    tid = ui.bot.tenant_id
    if flow.startswith("campaign_"):
        from .console_campaigns import answer as campaign_answer

        return campaign_answer(ui, flow, state, text, message)
    if flow == "new_plan":
        context(ui, "configure")
        plan = b.save_plan(ui.db, ui.bot, ui.user.id, {"name": text, "active": False})
        ui.state().data = {}
        plan_detail(ui, plan)
    elif flow == "plan_field":
        context(ui, "configure")
        plan = b.entity(ui.db, m.Plan, state["id"], ui.bot)
        field = state["field"]
        if field not in {
            "name",
            "description",
            "duration_days",
            "benefits",
            "purchase_message",
            "sort_order",
        }:
            raise DomainError("INVALID_FIELD", "Campo no disponible.")
        value = (
            int(text)
            if field in {"duration_days", "sort_order"}
            else [x.strip() for x in text.splitlines() if x.strip()]
            if field == "benefits"
            else text
        )
        b.save_plan(ui.db, ui.bot, ui.user.id, {field: value}, plan)
        ui.state().data = {}
        plan_detail(ui, plan)
    elif flow == "price":
        context(ui, "configure")
        plan = b.entity(ui.db, m.Plan, state["id"], ui.bot)
        b.price(ui.db, ui.bot, plan, state["provider"], state["currency"], text, ui.user.id)
        ui.state().data = {}
        plan_detail(ui, plan)
    elif flow in {"subscription_days", "subscription_reason", "grant_days"}:
        context(ui, "subscriptions")
        if flow in {"subscription_days", "grant_days"}:
            value, reason = text.split(maxsplit=1)
            state.update(days=int(value), reason=reason[:500])
        else:
            state["reason"] = text[:500]
        if len(state["reason"]) < 3:
            raise DomainError("REASON_REQUIRED", "Indica un motivo para el historial.")
        ui.state().data = {}
        ui.say(
            ui.t("ui_b9851c7113"),
            [
                [
                    ui.button(
                        ui.t("ui_fe09335615"),
                        "grant_confirm" if flow == "grant_days" else "subscription_confirm",
                        **state,
                    )
                ]
            ],
        )
    elif flow == "invite":
        context(ui, "subscriptions")
        parts = text.split(maxsplit=3)
        days, uses, valid_days = map(int, parts[:3])
        ui.state().data = {}
        dispatch(
            ui,
            "invite_channels",
            {
                "plan_id": state["plan_id"],
                "days": days,
                "uses": uses,
                "expires_at": m.now() + valid_days * 86400,
                "note": parts[3] if len(parts) > 3 else "",
            },
        )
    elif flow == "contact_search":
        ui.state().data = {}
        records(ui, {"resource": "contacts", "filters": {"search": text[:100]}})
    elif flow == "tags":
        context(ui, "support")
        person = b.entity(ui.db, m.Contact, state["id"], ui.bot)
        names = list(dict.fromkeys(x.strip() for x in text.split(",") if x.strip())) if text != "-" else []
        if len(names) > 10 or any(len(x) > 40 for x in names):
            raise DomainError("INVALID_TAGS", "Usa hasta 10 etiquetas de máximo 40 caracteres.")
        old = list(
            ui.db.scalars(
                select(m.ContactTag).where(
                    m.ContactTag.contact_id == person.id, m.ContactTag.tenant_id == tid
                )
            )
        )
        was_vip = any(ui.db.get(m.Tag, link.tag_id).name.casefold() == "vip" for link in old)
        for link in old:
            ui.db.delete(link)
        ui.db.flush()
        for name in names:
            tag = ui.db.scalar(select(m.Tag).where(m.Tag.tenant_id == tid, m.Tag.name == name))
            if not tag:
                tag = m.Tag(id=m.uid(), tenant_id=tid, name=name)
                ui.db.add(tag)
                ui.db.flush()
            ui.db.add(m.ContactTag(tenant_id=tid, contact_id=person.id, tag_id=tag.id))
        audit(ui.db, tid, ui.user.id, "CONTACT_TAGS_CHANGED", person.id, {"after": names})
        if not was_vip and any(name.casefold() == "vip" for name in names):
            from .notifications import notify

            notify(
                ui.db,
                ui.r,
                ui.bot,
                "vip",
                {"key": "vip_notice", "values": {"name": person.first_name}},
                f"vip:{person.id}:{ui.update['update_id']}",
                "read",
                "detail",
                {"resource": "contacts", "id": person.id},
            )
        ui.state().data = {}
        ui.say(ui.t("saved"))
    elif flow == "bank_refund":
        context(ui, "payments")
        charge = b.entity(ui.db, m.PaymentCharge, state["id"], ui.bot)
        amount, reference, reason = text.split(maxsplit=2)
        value = b.amount_minor(amount, charge.currency)
        if len(reference) > 200 or len(reason) < 3:
            raise DomainError("INVALID_REFUND", "Revisa la referencia y el motivo.")
        ui.state().data = {}
        ui.say(
            ui.t("ui_4e5a0f2f0f")
            + b.money(value, charge.currency)
            + ui.t("ui_97431e865d")
            + reference
            + ui.t("ui_38f5f5f9fa")
            + reason,
            [
                [
                    ui.button(
                        ui.t("ui_0834eb5909"),
                        "charge_refund_confirm",
                        id=charge.id,
                        amount=value,
                        reference=reference,
                        reason=reason[:500],
                    )
                ]
            ],
        )
    elif flow == "team_user":
        context(ui, "team")
        telegram_id = int(text)
        if telegram_id <= 0:
            raise ValueError()
        ui.state().data = {}
        ui.say(
            ui.t("ui_b0f6ff610e"),
            [
                [ui.button(role, "team_role", telegram_id=telegram_id, role=role)]
                for role in ["ADMIN", "SUPPORT", "FINANCE", "MODERATOR", "READ_ONLY"]
            ]
            + [[ui.button(ui.t("ui_7c5d0619a4"), "team_custom", telegram_id=telegram_id)]],
        )
    elif flow == "preference":
        context(ui, "configure")
        field = state["field"]
        if field == "timezone":
            bounds("today", text)
        elif field != "date_format" or text not in {"DMY", "MDY", "YMD"}:
            raise DomainError("INVALID_DATE_FORMAT", "Usa DMY, MDY o YMD.")
        row = settings(ui)
        row.preferences = {**row.preferences, field: text}
        ui.state().data = {}
        ui.say(ui.t("saved"))
    elif flow == "report_period":
        context(ui, "export")
        from zoneinfo import ZoneInfo
        from datetime import timedelta

        left, right = text.split()
        zone = ZoneInfo(settings(ui).preferences.get("timezone", "UTC"))
        start = datetime.strptime(left, "%Y-%m-%d").replace(tzinfo=zone)
        end = datetime.strptime(right, "%Y-%m-%d").replace(tzinfo=zone) + timedelta(days=1)
        ui.r.reports.request(ui.db, ui.bot, ui.user, int(start.timestamp()), int(end.timestamp()))
        ui.state().data = {}
        ui.say(ui.t("report_queued"))
    elif flow.startswith("method_"):
        from .console_payments import answer as payment_answer

        payment_answer(ui, flow, state, text, message)
    elif flow.startswith("template"):
        from .console_templates import answer as template_answer

        template_answer(ui, flow, state, text)
    else:
        raise DomainError("UNKNOWN_FORM", "Abre /start para continuar.")
