"""Master-bot account, BotFather connection and platform billing dialogs."""

from decimal import Decimal, InvalidOperation
from sqlalchemy import select, func
from .. import models as m
from ..errors import DomainError
from . import tenants
from .billing_ledger import trial_remaining, setting, set_setting, set_rate
from .common import audit, enqueue


def date(timestamp):
    from .console import date as fmt

    return fmt(timestamp)


def revenue_summary(data, language):
    from .i18n import t
    from .business import money

    return "\n".join(
        t(
            "saas_revenue_line",
            language,
            currency=currency,
            sales=money(values.get("sales_minor", values["gross_minor"]), currency),
            refunds=money(values.get("refunds_minor", 0), currency),
            net=money(values["gross_minor"], currency),
        )
        for currency, values in sorted(data.get("currencies", {}).items())
    ) or t("ui_b304de23d5", language)


def usage_summary(usage, language):
    from .i18n import t

    limits = usage.get("limits", {})
    return t(
        "saas_usage_summary",
        language,
        measured=date(usage.get("measured_at")),
        month=usage.get("quota_month_utc", "—"),
        bots=usage.get("bots", 0),
        bots_limit=limits.get("bots", "—"),
        contacts=usage.get("contacts", 0),
        contacts_limit=limits.get("active_contacts", "—"),
        admins=usage.get("admins", 0),
        admins_limit=limits.get("admins", "—"),
        campaigns=usage.get("campaigns", 0),
        campaigns_limit=limits.get("campaigns_month", "—"),
        exports=usage.get("exports", 0),
        exports_limit=limits.get("exports_month", "—"),
    )


def invoice_summary(invoice, language="es"):
    from .i18n import t
    from .billing_ledger import PlatformLedger

    data = invoice.breakdown or {}
    text = t(
        "saas_invoice_summary",
        language,
        number=invoice.number,
        state=invoice.status,
        plan=data.get("plan_name", "—"),
        start=date(data.get("starts_at")),
        end=date(data.get("ends_at")),
        fixed=invoice.fixed_minor / 100,
        rate=data.get("commission_bps", 0) / 100,
        commission=f"USD {invoice.commission_minor / 100:.2f}"
        if invoice.commission_minor is not None
        else "N/D",
        adjustment=(invoice.adjustment_minor or 0) / 100,
        paid=(invoice.paid_minor or 0) / 100,
        total=f"USD {(invoice.fixed_minor + invoice.commission_minor + (invoice.adjustment_minor or 0)) / 100:.2f}"
        if invoice.commission_minor is not None
        else "N/D",
        due=f"USD {PlatformLedger.outstanding(invoice) / 100:.2f}"
        if invoice.commission_minor is not None
        else "N/D",
        deadline=date(invoice.due_at),
    )
    text += "\n\n" + revenue_summary(data, language)
    if data.get("usage"):
        text += "\n\n" + usage_summary(data["usage"], language)
    text += "\n\n" + t("saas_billing_basis", language)
    if invoice.commission_minor is None:
        text += "\n" + t("invoice_rate_notice", language)
    return text


def owner_tenant(ui, tid):
    ui.ctx(tid, "billing")
    tenant = ui.db.get(m.Tenant, tid)
    if tenant.owner_user_id != ui.user.id:
        raise DomainError("OWNER_REQUIRED", "La cuenta SaaS pertenece al propietario del negocio.", 403)
    return tenant


def workspace(ui, tid):
    ui.ctx(tid)
    tenant, sub, plan = tenants.entitlement(ui.db, tid, writable=False)
    remaining = trial_remaining(sub)
    text = ui.t("ui_bd59ce9793", p0=tenant.name, p1=plan.name, p2=sub.status)
    if sub.status == "TRIAL":
        text += ui.t("ui_0d23c5ab80", p0=remaining["days"], p1=remaining["hours"])
    rows = []
    if not sub.trial_starts_at and not ui.user.trial_used_at and not sub.cycle_started_at:
        rows.append([ui.button(ui.t("ui_303acc5bdc"), "trial_activate", tid=tid)])
    for bot in ui.db.scalars(
        select(m.ManagedBot).where(m.ManagedBot.tenant_id == tid).order_by(m.ManagedBot.created_at).limit(30)
    ):
        rows.append([ui.button("🤖 @" + bot.username, "connection_menu", tid=tid, id=bot.id)])
    rows += [
        [ui.button(ui.t("ui_cd6fc18cba"), "connect_token", tid=tid)],
        [ui.button(ui.t("ui_ab559422f5"), "billing", tid=tid)],
        [ui.button(ui.t("ui_f18f127b2f"), "connection_help", tid=tid)],
    ]
    audit(ui.db, tid, ui.user.id, "TELEGRAM_WORKSPACE_VIEWED", tid)
    ui.say(text + ui.t("ui_9f3648bbb7"), rows)


def billing(ui, tid, prepared=False):
    ui.ctx(tid, "billing")
    if not prepared:
        enqueue(
            ui.db,
            "SAAS_SUMMARY",
            tid,
            {"viewer_id": ui.actor["id"], "update_id": ui.update["update_id"]},
            f"saas-summary:{tid}:{ui.actor['id']}:{ui.update['update_id']}",
        )
        ui.say(ui.t("saas_summary_queued"))
        return
    _, sub, plan = tenants.entitlement(ui.db, tid, writable=False)
    left = trial_remaining(sub)
    text = ui.t(
        "ui_7cfe980e93",
        p0=plan.name,
        p1=plan.fixed_usd_minor / 100,
        p2=plan.commission_bps / 100,
        p3=sub.status,
    )
    if sub.status == "TRIAL":
        text += ui.t("ui_0d23c5ab80", p0=left["days"], p1=left["hours"])
    if sub.cycle_started_at:
        text += ui.t("ui_7291eac1c1", p0=date(sub.cycle_started_at), p1=date(sub.current_period_end))
        cycle = ui.db.scalar(
            select(m.BillingCycle).where(
                m.BillingCycle.tenant_id == tid, m.BillingCycle.starts_at == sub.cycle_started_at
            )
        )
        if cycle:
            data = ui.r.ledger.breakdown(ui.db, cycle)
            text += "\n" + revenue_summary(data, ui.language)
            text += ui.t("ui_732040bbac", p0=cycle.fixed_usd_minor / 100)
            if data["commission_usd_minor"] is not None:
                text += ui.t("ui_7ca527beee", p0=data["commission_usd_minor"] / 100)
            else:
                text += ui.t("ui_4b667ee7b5") + ", ".join(data["missing_rates"])
    text += ui.t("ui_6a0f01c5a8", p0=ui.r.ledger.balance(ui.db, tid) / 100)
    if sub.pending_plan_id:
        text += ui.t("ui_5576f4187b") + ui.db.get(m.SaaSPlan, sub.pending_plan_id).name
    from .billing_ledger import usage_snapshot

    text += "\n\n" + usage_summary(usage_snapshot(ui.db, tid), ui.language)
    rows = [[ui.button(ui.t("ui_2fc3433b01"), "platform_invoices", tid=tid)]]
    for option in ui.db.scalars(
        select(m.SaaSPlan).where(m.SaaSPlan.active.is_(True)).order_by(m.SaaSPlan.fixed_usd_minor)
    ):
        rows.append(
            [
                ui.button(
                    ui.t(
                        "ui_b4ceef9a69",
                        p0=option.name,
                        p1=option.fixed_usd_minor / 100,
                        p2=option.commission_bps / 100,
                    ),
                    "platform_plan",
                    tid=tid,
                    id=option.id,
                )
            ]
        )
    rows += [
        [ui.button(ui.t("ui_fe24c9a8f7"), "platform_cancel", tid=tid)],
        [ui.button(ui.t("ui_92de7fea08"), "workspace", tid=tid)],
    ]
    ui.say(text, rows)


def invoice_view(ui, invoice, platform=False):
    if platform:
        ui.owner()
    else:
        ui.ctx(invoice.tenant_id, "billing")
    text = invoice_summary(invoice, ui.language)
    rows = []
    if platform:
        rows += [
            [ui.button(ui.t("ui_2ebe8a44d3"), "invoice_adjust", id=invoice.id)],
            [ui.button(ui.t("ui_2fae6b0900"), "invoice_rates", id=invoice.id)],
        ]
    elif ui.r.ledger.outstanding(invoice) > 0 and invoice.status != "NEEDS_RATE":
        methods = setting(ui.db, "billing_methods")
        for method, label in [("BANK_TRANSFER", ui.t("ui_f2752fb04c")), ("CRYPTO", ui.t("ui_7af7a2be50"))]:
            if methods.get(method, {}).get("enabled"):
                rows.append(
                    [
                        ui.button(
                            label, "settlement_method", tid=invoice.tenant_id, id=invoice.id, method=method
                        )
                    ]
                )
        if not rows:
            text += ui.t("ui_44adcb1e8a")
    history = list(
        ui.db.scalars(
            select(m.PlatformSettlement)
            .where(m.PlatformSettlement.invoice_id == invoice.id)
            .order_by(m.PlatformSettlement.created_at.desc())
            .limit(8)
        )
    )
    if history:
        text += ui.t("ui_1a67f8860c") + "\n".join(
            f"{x.method} · USD {x.amount_usd_minor / 100:.2f} · {x.status}" for x in history
        )
    ui.say(text, rows)


def dispatch(ui, action, d):
    if ui.bot:
        return False
    tid, eid = d.get("tid"), d.get("id")
    if action == "workspace":
        workspace(ui, tid)
    elif action == "new_workspace":
        ui.ask("saas_workspace", ui.t("ui_3036726cc4"))
    elif action == "trial_activate":
        tenant = owner_tenant(ui, tid)
        ui.r.ledger.activate_trial(ui.db, tenant, ui.user)
        workspace(ui, tid)
    elif action in {"connect_token", "replace_token"}:
        owner_tenant(ui, tid)
        tenants.entitlement(ui.db, tid)
        ui.ask(
            "saas_token",
            ui.t("ui_c7882bd0a9"),
            tid=tid,
            replace_bot_id=eid if action == "replace_token" else None,
            sensitive=True,
        )
    elif action in {"connect_confirm", "connect_cancel"}:
        owner_tenant(ui, tid)
        attempt = ui.entity(m.ConnectionAttempt, tid, eid, "billing")
        if action == "connect_cancel":
            ui.r.connections.cancel(ui.db, attempt, ui.user)
            ui.say(ui.t("ui_091f5af955"))
        else:
            bot = ui.r.connections.confirm(ui.db, eid, tid, ui.user)
            ui.say(
                ui.t("ui_ea0a97f6e5"),
                [[{"text": ui.t("ui_accbc07b1a") + bot.username, "url": "https://t.me/" + bot.username}]],
            )
    elif action == "connection_menu":
        bot = ui.entity(m.ManagedBot, tid, eid)
        ui.say(
            ui.t("ui_dc87d8b50f", p0=bot.username, p1=bot.telegram_bot_id, p2=bot.status),
            [
                [{"text": ui.t("ui_9c2d08cdfd"), "url": "https://t.me/" + bot.username + "?start=admin"}],
                [ui.button(ui.t("ui_c6d042cc22"), "replace_token", tid=tid, id=eid)],
                [ui.button(ui.t("ui_89130f77b7"), "disconnect_prompt", tid=tid, id=eid)],
                [ui.button(ui.t("ui_83e6b6a593"), "repair", tid=tid, id=eid)],
                [ui.button(ui.t("ui_92de7fea08"), "workspace", tid=tid)],
            ],
        )
    elif action == "disconnect_prompt":
        owner_tenant(ui, tid)
        ui.say(
            ui.t("ui_5ef2eb0549"), [[ui.button(ui.t("ui_0c9eb8dbc4"), "disconnect_confirm", tid=tid, id=eid)]]
        )
    elif action == "disconnect_confirm":
        bot = ui.entity(m.ManagedBot, tid, eid, "billing")
        ui.r.connections.disconnect(ui.db, bot, ui.user)
        ui.say(ui.t("ui_6f8897827f"))
    elif action in {"connection_help", "help"}:
        ui.say(ui.t("ui_ef40057b06"))
    elif action == "billing":
        billing(ui, tid)
    elif action == "platform_plan":
        owner_tenant(ui, tid)
        plan = ui.db.get(m.SaaSPlan, eid)
        if not plan or not plan.active:
            raise DomainError("NOT_FOUND", "Plan no disponible.")
        ui.say(
            ui.t("ui_0008417495", p0=plan.name, p1=plan.fixed_usd_minor / 100, p2=plan.commission_bps / 100),
            [[ui.button(ui.t("ui_839add3733"), "platform_plan_confirm", tid=tid, id=eid)]],
        )
    elif action == "platform_plan_confirm":
        owner_tenant(ui, tid)
        result = ui.r.ledger.select_plan(ui.db, tid, eid, ui.user)
        ui.say(
            (ui.t("ui_e2ea3a9315") if result["scheduled"] else ui.t("ui_1bc1d359df"))
            + date(result["effective_at"])
        )
        billing(ui, tid)
    elif action == "platform_cancel":
        owner_tenant(ui, tid)
        ui.say(
            ui.t("ui_40a27aafae"), [[ui.button(ui.t("ui_e38de60f7d"), "platform_cancel_confirm", tid=tid)]]
        )
    elif action == "platform_cancel_confirm":
        owner_tenant(ui, tid)
        sub = ui.db.scalar(
            select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == tid).with_for_update()
        )
        sub.cancelled_at = m.now()
        audit(
            ui.db,
            tid,
            ui.user.id,
            "SAAS_CANCELLATION_SCHEDULED",
            sub.id,
            {"effective_at": sub.current_period_end},
        )
        ui.say(ui.t("ui_186cac41fa"))
    elif action == "platform_invoices":
        ui.ctx(tid, "billing")
        query = select(m.PlatformInvoice).where(m.PlatformInvoice.tenant_id == tid)
        if d.get("after"):
            query = query.where(m.PlatformInvoice.id > d["after"])
        rows = list(ui.db.scalars(query.order_by(m.PlatformInvoice.id).limit(9)))
        buttons = [
            [ui.button(x.number[-16:] + " · " + x.status, "platform_invoice", tid=tid, id=x.id)]
            for x in rows[:8]
        ]
        if len(rows) > 8:
            buttons.append([ui.button(ui.t("ui_17fd6b8557"), "platform_invoices", tid=tid, after=rows[7].id)])
        ui.say(ui.t("ui_cb62dc4b5e") + (ui.t("ui_5287b483b3") if not rows else ""), buttons)
    elif action == "platform_invoice":
        invoice_view(ui, ui.entity(m.PlatformInvoice, tid, eid, "billing"))
    elif action == "settlement_method":
        owner_tenant(ui, tid)
        invoice = ui.entity(m.PlatformInvoice, tid, eid, "billing")
        config = setting(ui.db, "billing_methods").get(d["method"], {})
        if not config.get("enabled"):
            raise DomainError("METHOD_DISABLED", "Método no disponible.")
        instructions = "\n".join(f"{k}: {v}" for k, v in config.items() if k not in {"enabled"} and v)
        ui.say(
            instructions + ui.t("ui_887df4dbba", p0=ui.r.ledger.outstanding(invoice) / 100),
            [[ui.button(ui.t("ui_13d855b4c7"), "settlement_submit", **d)]],
        )
    elif action == "settlement_submit":
        owner_tenant(ui, tid)
        ui.ask("saas_amount", ui.t("ui_39ba83d8c9"), **d)
    elif action == "platform_finance":
        ui.owner()
        total = (
            ui.db.scalar(
                select(func.sum(m.PlatformSettlement.amount_usd_minor)).where(
                    m.PlatformSettlement.status == "APPROVED"
                )
            )
            or 0
        )
        pending = ui.db.scalar(
            select(func.count())
            .select_from(m.PlatformInvoice)
            .where(m.PlatformInvoice.status.in_(["PAYMENT_PENDING", "OVERDUE", "NEEDS_RATE"]))
        )
        ui.say(
            ui.t("ui_e0161a4c98", p0=total / 100, p1=pending),
            [
                [ui.button(ui.t("ui_5e185983b6"), "finance_list", resource="invoices")],
                [ui.button(ui.t("ui_357eaf7f92"), "finance_list", resource="settlements")],
                [ui.button(ui.t("ui_2855722d72"), "billing_methods")],
                [ui.button(ui.t("ui_0ab663183e"), "fx_settings")],
                [ui.button(ui.t("ui_1cb349623e"), "billing_grace")],
            ],
        )
    elif action == "platform_dashboard":
        ui.owner()
        enqueue(
            ui.db,
            "PLATFORM_DASHBOARD",
            None,
            {"viewer_id": ui.actor["id"]},
            f"platform-dashboard:{ui.update['update_id']}",
        )
        ui.say(ui.t("ui_48fb6aa3f9"))
    elif action == "saas_terms":
        ui.owner()
        plan = ui.db.get(m.SaaSPlan, eid)
        ui.ask(
            "saas_terms",
            ui.t("ui_69bf39552a", p0=plan.name, p1=plan.fixed_usd_minor / 100, p2=plan.commission_bps / 100),
            id=eid,
        )
    elif action == "saas_terms_confirm":
        ui.owner()
        plan = ui.db.get(m.SaaSPlan, eid)
        before = {"fixed_usd_minor": plan.fixed_usd_minor, "commission_bps": plan.commission_bps}
        plan.fixed_usd_minor, plan.commission_bps = d["fixed_usd_minor"], d["commission_bps"]
        audit(
            ui.db,
            None,
            ui.user.id,
            "SAAS_TERMS_CHANGED",
            plan.id,
            {
                "before": before,
                "after": {"fixed_usd_minor": plan.fixed_usd_minor, "commission_bps": plan.commission_bps},
                "reason": d["reason"],
            },
        )
        ui.say(ui.t("ui_5b6dba0100"))
    elif action == "billing_grace":
        ui.owner()
        ui.ask("saas_grace", ui.t("ui_f7f9fa14b0"))
    elif action == "finance_list":
        ui.owner()
        model = {"invoices": m.PlatformInvoice, "settlements": m.PlatformSettlement}[d["resource"]]
        query = select(model)
        if d.get("status"):
            query = query.where(model.status == d["status"])
        if d.get("after"):
            query = query.where(model.id > d["after"])
        rows = list(ui.db.scalars(query.order_by(model.id).limit(9)))
        buttons = [
            [ui.button(x.id[:8] + " · " + x.status, "finance_detail", resource=d["resource"], id=x.id)]
            for x in rows[:8]
        ]
        if len(rows) > 8:
            buttons.append(
                [
                    ui.button(
                        ui.t("ui_17fd6b8557"),
                        "finance_list",
                        resource=d["resource"],
                        status=d.get("status"),
                        after=rows[7].id,
                    )
                ]
            )
        buttons += [
            [ui.button(status, "finance_list", resource=d["resource"], status=status)]
            for status in (
                ["PAYMENT_PENDING", "OVERDUE", "NEEDS_RATE", "PAID"]
                if d["resource"] == "invoices"
                else ["PENDING", "APPROVED", "REJECTED"]
            )
        ]
        ui.say(ui.t("ui_71873019a2") + (ui.t("ui_ee6b79c573") if not rows else ""), buttons)
    elif action == "finance_detail":
        ui.owner()
        if d["resource"] == "invoices":
            invoice_view(ui, ui.db.get(m.PlatformInvoice, eid), True)
        else:
            row = ui.db.get(m.PlatformSettlement, eid)
            ui.say(
                ui.t(
                    "ui_86b8fce623",
                    p0=row.id[:8],
                    p1=row.method,
                    p2=row.reference,
                    p3=row.amount_usd_minor / 100,
                    p4=row.status,
                    p5=row.note,
                )
                + "\n".join(f"{key}: {value}" for key, value in row.evidence.items() if value),
                [[ui.button(ui.t("ui_4a6ec008ac"), "platform_receipt", id=eid)]]
                + (
                    [
                        [
                            ui.button(ui.t("ui_021c129c01"), "settlement_review", id=eid, approve=True),
                            ui.button(ui.t("ui_bee802da1b"), "settlement_review", id=eid, approve=False),
                        ]
                    ]
                    if row.status == "PENDING"
                    else []
                ),
            )
    elif action == "platform_receipt":
        ui.owner()
        row = ui.db.get(m.PlatformSettlement, eid)
        if not row.receipt_ciphertext:
            ui.say(ui.t("ui_26499f4e77"))
        else:
            enqueue(
                ui.db,
                "DELIVER_PLATFORM_RECEIPT",
                row.tenant_id,
                {"settlement_id": row.id, "viewer_id": ui.actor["id"]},
                f"platform-receipt:{eid}:{ui.update['update_id']}",
            )
            ui.say(ui.t("ui_68b5d8cd50"))
    elif action == "settlement_review":
        ui.owner()
        ui.ask("saas_review", ui.t("ui_03de1ffa78"), **d)
    elif action == "settlement_confirm":
        ui.owner()
        row = ui.db.get(m.PlatformSettlement, eid)
        ui.r.ledger.review(ui.db, row, ui.user.id, d["approve"], d["note"])
        ui.say(ui.t("ui_dea8511fd8"))
    elif action == "invoice_adjust":
        ui.owner()
        ui.ask("saas_adjust", ui.t("ui_97532e8f6a"), id=eid)
    elif action == "invoice_rates":
        ui.owner()
        invoice = ui.db.get(m.PlatformInvoice, eid)
        ui.r.ledger.resolve_rates(ui.db, ui.db.get(m.BillingCycle, invoice.cycle_id), ui.user.id)
        invoice_view(ui, invoice, True)
    elif action == "billing_methods":
        ui.owner()
        methods = setting(ui.db, "billing_methods")
        ui.say(
            ui.t("ui_26a4a8b2bd"),
            [
                [
                    ui.button(
                        ui.t("ui_fe18c98897")
                        + (
                            ui.t("ui_b618f50bd4")
                            if methods.get("BANK_TRANSFER", {}).get("enabled")
                            else ui.t("ui_b662925851")
                        ),
                        "billing_method_view",
                        method="BANK_TRANSFER",
                    )
                ],
                [
                    ui.button(
                        ui.t("ui_57766b9ace")
                        + (
                            ui.t("ui_b618f50bd4")
                            if methods.get("CRYPTO", {}).get("enabled")
                            else ui.t("ui_b662925851")
                        ),
                        "billing_method_view",
                        method="CRYPTO",
                    )
                ],
            ],
        )
    elif action in {"billing_method_view", "billing_method_disable"}:
        ui.owner()
        methods = setting(ui.db, "billing_methods")
        values = methods.get(d["method"], {})
        if action == "billing_method_disable":
            values["enabled"] = False
            set_setting(ui.db, "billing_methods", {**methods, d["method"]: values}, ui.user.id)
        ui.say(
            d["method"]
            + "\n"
            + ("\n".join(f"{key}: {value}" for key, value in values.items()) or ui.t("ui_8cbe82eda0")),
            [[ui.button(ui.t("ui_8a5a57f162"), "billing_method_edit", method=d["method"])]]
            + (
                [[ui.button(ui.t("ui_7ef1cd2d34"), "billing_method_disable", method=d["method"])]]
                if values.get("enabled")
                else []
            ),
        )
    elif action == "billing_method_edit":
        ui.owner()
        fields = (
            ["banco", "titular", "cuenta", "moneda", "instrucciones"]
            if d["method"] == "BANK_TRANSFER"
            else ["activo", "red", "direccion", "instrucciones"]
        )
        ui.ask(
            "saas_method",
            ui.t("ui_5dc31bd11a") + ui.t("billing_field_" + fields[0]) + ":",
            method=d["method"],
            fields=fields,
            index=0,
            values={},
        )
    elif action == "fx_settings":
        ui.owner()
        ui.ask("saas_fx", ui.t("ui_f2397b8403"))
    else:
        return False
    return True


def answer(ui, text, message):
    flow = ui.state().data.get("flow", "")
    if not flow.startswith("saas_"):
        return False
    d = {k: v for k, v in ui.state().data.items() if k not in {"flow", "sensitive"}}
    if flow == "saas_workspace":
        if not 2 <= len(text) <= 100:
            raise DomainError("INVALID_NAME", "Usa un nombre entre 2 y 100 caracteres.")
        tenant = tenants.create_tenant(ui.db, ui.user, text, ui.r.settings, activate_trial=False)
        ui.state().data = {}
        workspace(ui, tenant.id)
    elif flow == "saas_token":
        owner_tenant(ui, d["tid"])
        ui.r.connections.request(
            ui.db, d["tid"], ui.user, text, f"telegram:{ui.update['update_id']}", d.get("replace_bot_id")
        )
        enqueue(
            ui.db,
            "DELETE_MESSAGE",
            None,
            {"chat_id": ui.actor["id"], "message_id": message["message_id"]},
            f"secret-message:{ui.key}:{message['message_id']}",
        )
        ui.state().data = {}
        ui.say(ui.t("ui_888ea907df"))
    elif flow == "saas_amount":
        owner_tenant(ui, d["tid"])
        from .business import amount_minor

        value = amount_minor(text, "USD")
        invoice = ui.entity(m.PlatformInvoice, d["tid"], d["id"], "billing")
        if value > ui.r.ledger.outstanding(invoice):
            raise DomainError("EXCESS_PAYMENT", "El importe supera el saldo de esta factura.")
        config = setting(ui.db, "billing_methods").get(d["method"], {})
        evidence = {
            "network": config.get("red", ""),
            "asset": config.get("activo", ""),
            "destination": config.get("direccion", config.get("cuenta", "")),
        }
        ui.ask("saas_settlement", ui.t("ui_0c11b5e195"), **d, amount_usd_minor=value, evidence=evidence)
    elif flow == "saas_settlement":
        owner_tenant(ui, d["tid"])
        invoice = ui.entity(m.PlatformInvoice, d["tid"], d["id"], "billing")
        reference = text or message.get("caption", "")
        data = None
        if message.get("photo") or message.get("document"):
            file_id = (
                message["photo"][-1]["file_id"] if message.get("photo") else message["document"]["file_id"]
            )
            # Store only Telegram file identity; download and inspect outside the interactive queue.
            enqueue(
                ui.db,
                "SUBMIT_PLATFORM_RECEIPT",
                d["tid"],
                {
                    "invoice_id": invoice.id,
                    "actor_id": ui.user.id,
                    "file_id": file_id,
                    "method": d["method"],
                    "reference": reference[:240],
                    "amount_usd_minor": d["amount_usd_minor"],
                    "evidence": d["evidence"],
                    "viewer_id": ui.actor["id"],
                },
                f"platform-evidence:{ui.update['update_id']}",
            )
        else:
            ui.r.ledger.submit(
                ui.db,
                invoice,
                ui.user,
                d["method"],
                reference,
                d["amount_usd_minor"],
                data=data,
                evidence=d["evidence"],
            )
        ui.state().data = {}
        ui.say(ui.t("ui_a576ce1586"))
    elif flow == "saas_review":
        ui.owner()
        if len(text) < 3:
            raise DomainError("NOTE_REQUIRED", "Añade una nota para la auditoría.")
        ui.state().data = {}
        ui.say(
            ui.t("ui_bb5151dfcc"),
            [[ui.button(ui.t("ui_836e14df94"), "settlement_confirm", **d, note=text[:500])]],
        )
    elif flow == "saas_adjust":
        ui.owner()
        try:
            value, reason = text.split(maxsplit=1)
            number = Decimal(value)
            if not number.is_finite() or number.as_tuple().exponent < -2:
                raise ValueError()
            amount = int(number * 100)
        except (ValueError, InvalidOperation):
            raise DomainError(
                "INVALID_ADJUSTMENT", "Indica importe con máximo dos decimales y motivo."
            ) from None
        invoice = ui.db.get(m.PlatformInvoice, d["id"])
        ui.r.ledger.adjust(ui.db, invoice, amount, reason, ui.user.id, f"telegram:{ui.update['update_id']}")
        ui.state().data = {}
        invoice_view(ui, invoice, True)
    elif flow == "saas_method":
        ui.owner()
        if not 1 <= len(text) <= 1000:
            raise DomainError("INVALID_FIELD", "Introduce un dato entre 1 y 1000 caracteres.")
        values, index, fields = d["values"], d["index"], d["fields"]
        values[fields[index]] = text
        index += 1
        if index < len(fields):
            ui.ask(
                "saas_method",
                ui.t("ui_5dc31bd11a") + ui.t("billing_field_" + fields[index]) + ":",
                method=d["method"],
                fields=fields,
                index=index,
                values=values,
            )
        else:
            methods = setting(ui.db, "billing_methods")
            methods[d["method"]] = {**values, "enabled": True}
            set_setting(ui.db, "billing_methods", methods, ui.user.id)
            ui.state().data = {}
            ui.say(ui.t("ui_de5196ff47"))
    elif flow == "saas_fx":
        ui.owner()
        try:
            currency, value = text.split()
        except ValueError:
            raise DomainError("INVALID_RATE", "Envía moneda y tasa, separados por un espacio.") from None
        set_rate(ui.db, currency, value, ui.user.id)
        ui.state().data = {}
        ui.say(ui.t("ui_a670af1bbd"))
    elif flow == "saas_terms":
        ui.owner()
        fixed, commission, reason = text.split(maxsplit=2)
        fixed, commission = Decimal(fixed), Decimal(commission)
        if (
            not fixed.is_finite()
            or not commission.is_finite()
            or not 0 <= fixed <= 1000000
            or not 0 <= commission <= 100
            or fixed * 100 != int(fixed * 100)
            or commission * 100 != int(commission * 100)
            or len(reason) < 3
        ):
            raise DomainError(
                "INVALID_TERMS", "Revisa la cuota, el porcentaje y el motivo; usa máximo dos decimales."
            )
        ui.state().data = {}
        ui.say(
            ui.t("ui_183a5d0206", p0=fixed, p1=commission, p2=reason),
            [
                [
                    ui.button(
                        ui.t("ui_20c6e9949d"),
                        "saas_terms_confirm",
                        id=d["id"],
                        fixed_usd_minor=int(fixed * 100),
                        commission_bps=int(commission * 100),
                        reason=reason[:500],
                    )
                ]
            ],
        )
    elif flow == "saas_grace":
        ui.owner()
        days = int(text)
        if not 0 <= days <= 30:
            raise DomainError("INVALID_GRACE", "Indica entre 0 y 30 días.")
        set_setting(
            ui.db, "billing_policy", {**setting(ui.db, "billing_policy"), "grace_days": days}, ui.user.id
        )
        ui.state().data = {}
        ui.say(ui.t("ui_6dced01048"))
    return True
