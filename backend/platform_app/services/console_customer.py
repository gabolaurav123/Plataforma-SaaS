"""Branded customer journeys, independent language and durable checkout requests."""

from sqlalchemy import select
from .. import models as m
from ..errors import DomainError
from . import tenants, crm, payment_methods
from .common import emit, enqueue
from .texts import bot_text, customer_variables
from .business import entity, money
from .i18n import LANGUAGES
from .payments import MANUAL_PROVIDERS


def contact(ui, attribution_code=None):
    if getattr(ui, "_contact", None):
        return ui._contact
    tenants.entitlement(ui.db, ui.bot.tenant_id, writable=False)
    if ui.bot.status in {"OWNERSHIP_CHANGED", "DISCONNECTED", "CONNECTION_ERROR"}:
        raise DomainError("BOT_UNAVAILABLE", ui.t("not_ready"))
    if not ui.bot.published and not ui.business_role():
        raise DomainError("BOT_NOT_READY", ui.t("not_ready"))
    previous = ui.db.scalar(
        select(m.Contact.id).where(
            m.Contact.bot_id == ui.bot.id, m.Contact.telegram_user_id == ui.actor["id"]
        )
    )
    ui._contact = person = crm.upsert_contact(ui.db, ui.bot, ui.actor, attribution_code)
    if not previous:
        config = ui.db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == ui.bot.id))
        if not ui.actor.get("language_code"):
            person.locale = config.preferences.get("language", "es") if config else "es"
        emit(ui.db, ui.bot.tenant_id, "USER_JOINED", "user-joined:" + person.id, ui.bot.id, person.id)
        from .notifications import notify

        notify(ui.db, ui.r, ui.bot, "new_user", "👤 " + person.first_name, "new-user:" + person.id)
    ui.language = person.locale
    return person


def home(ui):
    person = contact(ui)
    rows = [
        [ui.button(ui.t("view_plans"), "plans")],
        [ui.button(ui.t("membership"), "memberships"), ui.button(ui.t("renew"), "plans")],
        [ui.button(ui.t("support"), "support"), ui.button(ui.t("policies"), "policies")],
        [ui.button(ui.t("customer_language"), "language")],
        [ui.button(ui.t("opt_out"), "stop")],
    ]
    if ui.business_role():
        rows.insert(0, [ui.button(ui.t("admin"), "biz:home")])
    ui.say(
        bot_text(
            ui.db,
            ui.bot,
            "WELCOME",
            locale=person.locale,
            name=person.first_name,
            username=person.username or "",
        ),
        rows,
    )


def message(ui, message):
    text = message.get("text", "").strip()
    code = text.split(maxsplit=1)[1] if text.startswith("/start ") else None
    person = contact(ui, code)
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
        if code and code.startswith("gift_"):
            sub = ui.r.invitations.redeem(ui.db, ui.bot, person, code[5:])
            ui.say(
                bot_text(
                    ui.db,
                    ui.bot,
                    "SUBSCRIPTION_ACTIVE",
                    locale=person.locale,
                    **customer_variables(ui.db, ui.bot, person, sub),
                )
            )
        else:
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
        state = ui.state().data
        query = select(m.Payment).where(
            m.Payment.bot_id == ui.bot.id,
            m.Payment.tenant_id == ui.bot.tenant_id,
            m.Payment.contact_id == person.id,
            m.Payment.provider.in_(MANUAL_PROVIDERS),
            m.Payment.status.in_(["PENDING", "RECEIPT_SUBMITTED"]),
        )
        if state.get("receipt_payment_id"):
            query = query.where(m.Payment.id == state["receipt_payment_id"])
        pending = list(ui.db.scalars(query.limit(9)))
        file_id = message["photo"][-1]["file_id"] if message.get("photo") else message["document"]["file_id"]
        if len(pending) == 1:
            queue_receipt(ui, pending[0], file_id)
        elif pending:
            ui.say(
                ui.t("choose_receipt_payment"),
                [
                    [
                        ui.button(
                            money(row.amount_minor, row.currency) + " · " + row.id[:8],
                            "receipt_attach",
                            id=row.id,
                            file_id=file_id,
                        )
                    ]
                    for row in pending
                ],
            )
        else:
            from .inbox import receive

            receive(ui, person, message)
    else:
        from .inbox import receive

        receive(ui, person, message)


def queue_receipt(ui, payment, file_id):
    person = contact(ui)
    if (
        payment.contact_id != person.id
        or payment.bot_id != ui.bot.id
        or payment.provider not in MANUAL_PROVIDERS
    ):
        raise DomainError("NOT_FOUND", ui.t("no_pending_transfer"), 404)
    enqueue(
        ui.db,
        "SUBMIT_RECEIPT",
        ui.bot.tenant_id,
        {"payment_id": payment.id, "file_id": file_id, "viewer_id": person.telegram_user_id},
        f"customer-receipt:{ui.bot.id}:{ui.update['update_id']}",
        ui.bot.id,
    )
    ui.state().data = {}
    ui.say(ui.t("receipt_queued"))


def prices(ui, plan):
    rows = list(
        ui.db.scalars(
            select(m.PlanPrice).where(
                m.PlanPrice.plan_id == plan.id, m.PlanPrice.tenant_id == ui.bot.tenant_id
            )
        )
    )
    result = []
    for row in rows:
        if plan.product_kind == "DIGITAL" and row.provider != "TELEGRAM_STARS":
            continue
        if row.provider not in payment_methods.PROVIDERS:
            continue
        method = payment_methods.get(ui.db, ui.bot, row.provider)
        enabled = (
            method.enabled
            if method
            else bool(
                ui.db.scalar(
                    select(m.ProviderConfig.id).where(
                        m.ProviderConfig.tenant_id == ui.bot.tenant_id,
                        m.ProviderConfig.provider == row.provider,
                        m.ProviderConfig.enabled.is_(True),
                    )
                )
            )
        )
        if enabled and row.provider == "CRYPTO_MANUAL":
            from .crypto_wallets import wallets

            enabled = bool(wallets(ui.db, ui.bot, row.currency))
        if enabled:
            result.append(row)
    return result


def dispatch(ui, action, d):
    person = contact(ui)
    bot, db = ui.bot, ui.db
    if action in {"home", "cancel"}:
        ui.state().data = {}
        home(ui)
    elif action == "plans":
        query = select(m.Plan).where(
            m.Plan.bot_id == bot.id,
            m.Plan.tenant_id == bot.tenant_id,
            m.Plan.active.is_(True),
            m.Plan.visible.is_(True),
            m.Plan.archived_at.is_(None),
        )
        page = max(0, min(int(d.get("page", 0)), 10000))
        plans = list(db.scalars(query.order_by(m.Plan.sort_order, m.Plan.id).offset(page * 8).limit(9)))
        rows = [[ui.button(plan.name, "plan", id=plan.id)] for plan in plans[:8]]
        if len(plans) > 8:
            rows.append([ui.button(ui.t("next"), "plans", page=page + 1)])
        ui.say(bot_text(db, bot, "PLAN_LIST", locale=person.locale) if rows else ui.t("empty"), rows)
    elif action == "plan":
        plan = entity(db, m.Plan, d["id"], bot)
        if not plan.active or plan.archived_at:
            raise DomainError("PLAN_UNAVAILABLE", ui.t("empty"))
        rows = [
            [
                ui.button(
                    ui.t(
                        "pay_with",
                        method=ui.t("crypto_label")
                        if price.provider == "CRYPTO_MANUAL"
                        else payment_methods.PROVIDERS[price.provider],
                        amount=money(price.amount_minor, price.currency),
                    ),
                    "buy",
                    id=plan.id,
                    provider=price.provider,
                    currency=price.currency,
                )
            ]
            for price in prices(ui, plan)
        ]
        value = (
            f"📦 {plan.name}\n{plan.description}\n"
            + ui.t("plan_duration", days=plan.duration_days)
            + "\n"
            + "\n".join("• " + str(x) for x in plan.benefits)
        )
        value += (
            "\n"
            + ui.t("automatic_renewal" if plan.recurring else "manual_renewal")
            + "\n"
            + ui.t("payment_terms")
        )
        ui.say(value, [[ui.button(ui.t("policies"), "policies")]] + rows)
    elif action == "buy":
        plan = entity(db, m.Plan, d["id"], bot)
        provider, currency = d.get("provider", "TELEGRAM_STARS"), d.get("currency", "XTR")
        if not any((price.provider, price.currency) == (provider, currency) for price in prices(ui, plan)):
            raise DomainError("PRICE_UNAVAILABLE", ui.t("empty"))
        if provider == "CRYPTO_MANUAL" and not d.get("wallet_id"):
            from .crypto_wallets import wallets

            ui.say(
                ui.t("crypto_choose_network"),
                [
                    [
                        ui.button(
                            w["asset"] + " · " + w["network"] + " · …" + w["address"][-6:],
                            "buy",
                            **d,
                            wallet_id=w["id"],
                        )
                    ]
                    for w in wallets(db, bot, currency)
                ],
            )
            return
        payment = ui.r.payments.create(
            db,
            bot,
            person,
            plan.id,
            provider,
            currency,
            f"native:{bot.id}:{person.id}:{ui.update['update_id']}",
            defer_checkout=True,
            wallet_id=d.get("wallet_id"),
        )
        emit(db, bot.tenant_id, "PLAN_SELECTED", f"plan-selected:{payment.id}", bot.id, person.id)
        ui.say(ui.t("checkout_queued"))
    elif action in {"receipt_for", "receipt_attach"}:
        payment = entity(db, m.Payment, d["id"], bot)
        if (
            payment.contact_id != person.id
            or payment.provider not in MANUAL_PROVIDERS
            or payment.status not in {"PENDING", "RECEIPT_SUBMITTED"}
        ):
            raise DomainError("NOT_FOUND", ui.t("no_pending_transfer"), 404)
        if action == "receipt_attach":
            queue_receipt(ui, payment, d["file_id"])
        else:
            ui.state().data = {"receipt_payment_id": payment.id}
            ui.say(bot_text(db, bot, "RECEIPT_REQUEST", locale=person.locale))
    elif action == "policies":
        config = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
        rows = [[ui.button(ui.t(key), "policy", key=key)] for key in ["terms", "privacy", "refund"]]
        ui.say(ui.t("policies"), rows)
    elif action == "policy":
        if d["key"] not in {"terms", "privacy", "refund"}:
            raise DomainError("NOT_FOUND", ui.t("empty"))
        config = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
        ui.say(ui.t(d["key"]) + "\n" + (config.policies.get(d["key"]) or ui.t("empty")))
    elif action == "memberships":
        query = select(m.Subscription).where(
            m.Subscription.bot_id == bot.id,
            m.Subscription.tenant_id == bot.tenant_id,
            m.Subscription.contact_id == person.id,
        )
        if d.get("after"):
            query = query.where(m.Subscription.id > d["after"])
        subs = list(db.scalars(query.order_by(m.Subscription.id).limit(9)))
        lines, buttons = [], []
        for sub in subs[:8]:
            values = customer_variables(db, bot, person, sub)
            active = sub.status == "ACTIVE" and sub.expires_at > m.now()
            lines.append(
                ui.t(
                    "membership_line",
                    plan=values["plan"],
                    status=ui.t("active" if active else "inactive"),
                    end=values["expiration_date"],
                )
            )
            if active and sub.channel_snapshot:
                buttons.append([ui.button("📺 " + values["plan"], "access", id=sub.id)])
            if active and sub.initial_charge_id:
                buttons.append(
                    [
                        ui.button(
                            ui.t("cancel_renewal" if sub.auto_renew else "enable_renewal"),
                            "renewal",
                            id=sub.id,
                            canceled=sub.auto_renew,
                        )
                    ]
                )
            buttons.append([ui.button(ui.t("renew") + " · " + values["plan"], "plan", id=sub.plan_id)])
        if len(subs) > 8:
            buttons.append([ui.button(ui.t("next"), "memberships", after=subs[7].id)])
        ui.say("\n".join(lines) or ui.t("no_membership"), buttons)
    elif action in {"access", "renewal", "renewal_confirm"}:
        sub = entity(db, m.Subscription, d["id"], bot)
        if sub.contact_id != person.id:
            raise DomainError("NOT_FOUND", ui.t("no_membership"), 404)
        if action == "access":
            if sub.status != "ACTIVE" or sub.expires_at <= m.now():
                raise DomainError("EXPIRED", ui.t("inactive"))
            enqueue(
                db,
                "GRANT_ACCESS",
                bot.tenant_id,
                {"subscription_id": sub.id},
                f"native-access:{sub.id}:{ui.update['update_id']}",
                bot.id,
            )
            ui.say(ui.t("access_queued"))
        elif action == "renewal":
            ui.say(ui.t("renewal_confirm"), [[ui.button(ui.t("confirm"), "renewal_confirm", **d)]])
        else:
            if not sub.initial_charge_id:
                raise DomainError("NOT_RECURRING", ui.t("manual_renewal"))
            enqueue(
                db,
                "CANCEL_CUSTOMER_RENEWAL",
                bot.tenant_id,
                {
                    "subscription_id": sub.id,
                    "canceled": bool(d["canceled"]),
                    "viewer_id": person.telegram_user_id,
                    "actor_id": str(person.telegram_user_id),
                },
                f"customer-renewal:{sub.id}:{ui.update['update_id']}",
                bot.id,
            )
            ui.say(ui.t("change_queued"))
    elif action == "stop":
        person.opted_out = True
        ui.say(ui.t("opt_out_saved"))
    elif action in {"language", "language_save"}:
        if action == "language_save":
            if d["language"] not in LANGUAGES:
                raise DomainError("INVALID_LANGUAGE", ui.t("empty"))
            person.locale = ui.language = d["language"]
            ui.say(ui.t("language_saved"))
        else:
            ui.say(
                ui.t("customer_language"),
                [[ui.button(label, "language_save", language=key)] for key, label in LANGUAGES.items()],
            )
    elif action == "support":
        config = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
        ui.say(
            bot_text(db, bot, "SUPPORT", locale=person.locale),
            [[{"text": ui.t("support"), "url": "https://t.me/" + config.support_username.lstrip("@")}]]
            if config.support_username
            else [],
        )
    else:
        raise DomainError("UNKNOWN_ACTION", ui.t("error"))
