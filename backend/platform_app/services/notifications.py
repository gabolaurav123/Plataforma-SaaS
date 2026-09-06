"""Business notifications travel through the business bot and recheck recipients."""

from sqlalchemy import select
from .. import models as m
from ..security import ROLES
from .common import send, enqueue


def admins(db, bot, permission="read"):
    tenant = db.get(m.Tenant, bot.tenant_id)
    owner = db.get(m.PlatformUser, tenant.owner_user_id)
    result = {owner.id: owner}
    for member, user in db.execute(
        select(m.BotAdmin, m.PlatformUser)
        .join(m.PlatformUser, m.PlatformUser.id == m.BotAdmin.user_id)
        .where(
            m.BotAdmin.bot_id == bot.id, m.BotAdmin.tenant_id == bot.tenant_id, m.BotAdmin.active.is_(True)
        )
    ):
        if permission in (
            set(member.permissions) if member.role == "CUSTOM" else ROLES.get(member.role, set())
        ):
            result[user.id] = user
    return list(result.values())


def notify(db, runtime, bot, category, text, key, permission="read", action=None, data=None):
    from .console import Console
    from .i18n import message

    config = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
    preferences = config.preferences.get("notifications", {}) if config else {}
    if not preferences.get(category, category in {"new_sale", "new_receipt", "payment_failed"}):
        return
    for user in admins(db, bot, permission):
        markup = None
        if action:
            ui = Console(runtime, db, bot, {"update_id": 0}, {"id": user.telegram_user_id})
            ui.render_admin = True
            markup = {"inline_keyboard": [[ui.button("👁 " + bot.name, action, **(data or {}))]]}
        send(
            db,
            bot,
            user.telegram_user_id,
            message(text, user.locale),
            f"notify:{key}:{user.id}",
            reply_markup=markup,
            service_message=True,
            admin_permission=permission,
            viewer_id=user.telegram_user_id,
        )


def customer(db, bot, person, key, dedup, subscription=None, payment=None):
    from .texts import bot_text, customer_variables

    values = customer_variables(db, bot, person, subscription, payment)
    return send(
        db,
        bot,
        person.telegram_user_id,
        bot_text(db, bot, key, locale=person.locale, **values),
        dedup,
        service_message=True,
    )


def summary_text(db, bot, data, language="es"):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from .business import money
    from .i18n import t

    config = db.scalar(
        select(m.BotSettings).where(m.BotSettings.bot_id == bot.id, m.BotSettings.tenant_id == bot.tenant_id)
    )
    preferences = config.preferences if config else {}
    zone = ZoneInfo(preferences.get("timezone", "UTC"))
    pattern = {"DMY": "%d/%m/%Y", "MDY": "%m/%d/%Y", "YMD": "%Y-%m-%d"}.get(
        preferences.get("date_format"), "%d/%m/%Y"
    ) + " %H:%M %Z"

    def date(value):
        return datetime.fromtimestamp(value, timezone.utc).astimezone(zone).strftime(pattern)

    text = t(
        "summary_title", language, name=bot.name, start=date(data["starts_at"]), end=date(data["ends_at"])
    )
    groups = {
        "current_state": [
            "users_total",
            "users_active_7d",
            "users_without_active_subscription",
            "subscriptions_active",
            "subscriptions_expiring_7d",
            "receipts_pending",
            "payments_pending",
        ],
        "period_metrics": [
            "users_new",
            "renewals",
            "renewal_share_percent",
            "cancellations",
            "invitations_used",
            "conversion_percent",
            "growth_percent",
            "churn_percent",
        ],
    }
    for title, keys in groups.items():
        text += (
            "\n\n"
            + t(title, language)
            + "\n"
            + "\n".join(
                f"{t(key, language)}: {data[key] if data[key] is not None else 'N/D'}" for key in keys
            )
        )
    for row in data["revenues"]:
        text += "\n\n" + t(
            "money_totals",
            language,
            gross=money(row["gross_minor"], row["currency"]),
            refund=money(row["refund_minor"], row["currency"]),
            net=money(row["net_minor"], row["currency"]),
            average=money(row["average_sale_minor"], row["currency"]),
        )
    text += (
        "\n\n"
        + t("mrr_label", language)
        + ": "
        + (", ".join(money(row["amount_minor"], row["currency"]) for row in data["mrr"]) or "0")
    )
    return text + "\n\n" + t("report_basis", language)


def schedule_summaries(db, after=None, batch=None):
    """Page businesses; enqueue only the last complete local period per preference."""
    from datetime import datetime, timezone, timedelta
    from zoneinfo import ZoneInfo

    batch = m.now() // 3600 if batch is None else batch
    query = (
        select(m.ManagedBot, m.BotSettings)
        .join(m.BotSettings, m.BotSettings.bot_id == m.ManagedBot.id)
        .where(
            m.ManagedBot.published.is_(True),
            m.ManagedBot.status.not_in(
                ["DISCONNECTED", "SUSPENDED", "CONNECTION_ERROR", "OWNERSHIP_CHANGED"]
            ),
        )
    )
    if after:
        query = query.where(m.ManagedBot.id > after)
    rows = list(db.execute(query.order_by(m.ManagedBot.id).limit(100)))
    for bot, config in rows:
        preferences = config.preferences.get("notifications", {})
        local = datetime.fromtimestamp(m.now(), timezone.utc).astimezone(
            ZoneInfo(config.preferences.get("timezone", "UTC"))
        )
        end = local.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end, month_end = end - timedelta(days=end.weekday()), end.replace(day=1)
        periods = {
            "daily": (end - timedelta(days=1), end),
            "weekly": (week_end - timedelta(days=7), week_end),
            "monthly": ((month_end - timedelta(days=1)).replace(day=1), month_end),
        }
        for category, (start, finish) in periods.items():
            if preferences.get(category):
                enqueue(
                    db,
                    "BUSINESS_SUMMARY",
                    bot.tenant_id,
                    {
                        "category": category,
                        "starts_at": int(start.timestamp()),
                        "ends_at": int(finish.timestamp()),
                    },
                    f"summary:{bot.id}:{category}:{int(finish.timestamp())}",
                    bot.id,
                )
    if len(rows) == 100:
        enqueue(
            db,
            "SUMMARY_SCAN",
            None,
            {"after": rows[-1][0].id, "batch": batch},
            f"summary-scan:{batch}:{rows[-1][0].id}",
        )


def deliver_summary(db, runtime, bot, job):
    from .reporting import snapshot

    config = db.scalar(
        select(m.BotSettings).where(m.BotSettings.bot_id == bot.id, m.BotSettings.tenant_id == bot.tenant_id)
    )
    if not config or not config.preferences.get("notifications", {}).get(job.payload["category"]):
        return
    data = snapshot(db, bot, job.payload["starts_at"], job.payload["ends_at"])
    for user in admins(db, bot, "stats"):
        send(
            db,
            bot,
            user.telegram_user_id,
            summary_text(db, bot, data, user.locale),
            f"summary-delivery:{job.id}:{user.id}",
            viewer_id=user.telegram_user_id,
            admin_permission="stats",
            service_message=True,
        )
