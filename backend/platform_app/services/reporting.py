"""Cash-basis reports, immutable membership history and bot-scoped aggregates.

Gross is dated at capture; refunds at refund recognition. Net excludes processor
fees, taxes and SaaS invoices. Amounts in different currencies are never added.
"""

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import select, func, distinct
from .. import models as m
from ..errors import DomainError
from .common import enqueue, send, audit
from .tenants import reserve_limit


def bounds(period, timezone_name="UTC", timestamp=None):
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise DomainError(
            "INVALID_TIMEZONE", "Indica una zona horaria válida, por ejemplo America/La_Paz."
        ) from None
    current = datetime.fromtimestamp(m.now() if timestamp is None else timestamp, timezone.utc).astimezone(
        zone
    )
    today = current.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        start, end = today, current + timedelta(seconds=1)
    elif period == "7d":
        start, end = today - timedelta(days=6), current + timedelta(seconds=1)
    elif period == "month":
        start, end = today.replace(day=1), current + timedelta(seconds=1)
    elif period == "previous_month":
        end = today.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
    else:
        raise DomainError("INVALID_PERIOD", "Selecciona un periodo válido.")
    return int(start.timestamp()), int(end.timestamp())


def active_cohort(bot, timestamp):
    """One latest immutable state per paid subscription, evaluated at a boundary."""
    latest = (
        select(
            m.Subscription.contact_id,
            m.SubscriptionHistory.after.label("state"),
            func.row_number()
            .over(
                partition_by=m.SubscriptionHistory.subscription_id,
                order_by=(m.SubscriptionHistory.created_at.desc(), m.SubscriptionHistory.revision.desc()),
            )
            .label("position"),
        )
        .join(m.Subscription, m.Subscription.id == m.SubscriptionHistory.subscription_id)
        .where(
            m.Subscription.tenant_id == bot.tenant_id,
            m.Subscription.bot_id == bot.id,
            m.Subscription.payment_id.is_not(None),
            m.SubscriptionHistory.tenant_id == bot.tenant_id,
            m.SubscriptionHistory.created_at < timestamp,
        )
        .subquery()
    )
    return (
        select(latest.c.contact_id)
        .where(
            latest.c.position == 1,
            latest.c.state["status"].as_string() == "ACTIVE",
            latest.c.state["expires_at"].as_integer() > timestamp,
        )
        .distinct()
    )


def snapshot(db, bot, starts_at, ends_at):
    if not 0 <= starts_at < ends_at or ends_at - starts_at > 367 * 86400:
        raise DomainError("INVALID_PERIOD", "El reporte admite un periodo máximo de un año.")
    tid, bid, now = bot.tenant_id, bot.id, m.now()

    def scope(model):
        return (model.tenant_id == tid, model.bot_id == bid)

    def period(model):
        return (*scope(model), model.created_at >= starts_at, model.created_at < ends_at)

    def count(model, *criteria):
        return db.scalar(select(func.count()).select_from(model).where(*scope(model), *criteria)) or 0

    contacts = db.execute(
        select(
            func.count(m.Contact.id),
            func.count(m.Contact.id).filter(
                m.Contact.created_at >= starts_at, m.Contact.created_at < ends_at
            ),
            func.count(m.Contact.id).filter(m.Contact.last_seen_at >= now - 7 * 86400),
            func.count(m.Contact.id).filter(m.Contact.created_at < starts_at),
        ).where(*scope(m.Contact))
    ).one()
    subscription_counts = dict(
        db.execute(
            select(m.Subscription.status, func.count())
            .where(*scope(m.Subscription))
            .group_by(m.Subscription.status)
        ).all()
    )
    active = count(m.Subscription, m.Subscription.status == "ACTIVE", m.Subscription.expires_at > now)
    active_contacts = (
        db.scalar(
            select(func.count(distinct(m.Subscription.contact_id))).where(
                *scope(m.Subscription), m.Subscription.status == "ACTIVE", m.Subscription.expires_at > now
            )
        )
        or 0
    )

    # Separate aggregates prevent multiplying captures by their partial refunds.
    gross = list(
        db.execute(
            select(
                m.PaymentCharge.provider,
                m.PaymentCharge.currency,
                func.sum(m.PaymentCharge.amount_minor).label("gross_minor"),
                func.count().label("charges"),
            )
            .where(*period(m.PaymentCharge))
            .group_by(m.PaymentCharge.provider, m.PaymentCharge.currency)
        ).mappings()
    )
    refunds = list(
        db.execute(
            select(
                m.PaymentRefund.provider,
                m.PaymentRefund.currency,
                func.sum(m.PaymentRefund.amount_minor).label("refund_minor"),
                func.count().label("refunds"),
            )
            .where(*period(m.PaymentRefund))
            .group_by(m.PaymentRefund.provider, m.PaymentRefund.currency)
        ).mappings()
    )
    grouped = {}
    for row in [*gross, *refunds]:
        key = (row["provider"], row["currency"])
        item = grouped.setdefault(
            key,
            {
                "provider": key[0],
                "currency": key[1],
                "gross_minor": 0,
                "refund_minor": 0,
                "charges": 0,
                "refunds": 0,
            },
        )
        item.update(dict(row))
    methods = sorted(grouped.values(), key=lambda x: (x["provider"], x["currency"]))
    totals = {}
    for item in methods:
        item["net_minor"] = item["gross_minor"] - item["refund_minor"]
        total = totals.setdefault(
            item["currency"],
            {
                "currency": item["currency"],
                "gross_minor": 0,
                "refund_minor": 0,
                "net_minor": 0,
                "charges": 0,
                "refunds": 0,
            },
        )
        for key in ("gross_minor", "refund_minor", "net_minor", "charges", "refunds"):
            total[key] += item[key]
    for row in totals.values():
        row["average_sale_minor"] = round(row["gross_minor"] / row["charges"], 2) if row["charges"] else 0
        row["net_per_registered_user_minor"] = round(row["net_minor"] / contacts[0], 2) if contacts[0] else 0
    plans = [
        dict(x)
        for x in db.execute(
            select(
                m.Plan.id,
                m.Plan.name,
                m.PaymentCharge.currency,
                func.count().label("sales"),
                func.sum(m.PaymentCharge.amount_minor).label("gross_minor"),
            )
            .join(m.Payment, m.Payment.plan_id == m.Plan.id)
            .join(m.PaymentCharge, m.PaymentCharge.payment_id == m.Payment.id)
            .where(*scope(m.Plan), *scope(m.Payment), *period(m.PaymentCharge))
            .group_by(m.Plan.id, m.Plan.name, m.PaymentCharge.currency)
            .order_by(func.count().desc(), m.Plan.id)
            .limit(20)
        ).mappings()
    ]
    buyers = (
        db.scalar(
            select(func.count(distinct(m.Payment.contact_id)))
            .join(m.PaymentCharge, m.PaymentCharge.payment_id == m.Payment.id)
            .where(*scope(m.Payment), *scope(m.PaymentCharge), m.PaymentCharge.refunded_at.is_(None))
        )
        or 0
    )
    purchases = (
        select(
            m.PaymentCharge.created_at,
            func.row_number()
            .over(
                partition_by=(m.Payment.contact_id, m.Payment.plan_id),
                order_by=(m.PaymentCharge.created_at, m.PaymentCharge.id),
            )
            .label("purchase_number"),
        )
        .join(m.Payment, m.Payment.id == m.PaymentCharge.payment_id)
        .where(*scope(m.PaymentCharge), *scope(m.Payment))
        .subquery()
    )
    renewals = (
        db.scalar(
            select(func.count())
            .select_from(purchases)
            .where(
                purchases.c.created_at >= starts_at,
                purchases.c.created_at < ends_at,
                purchases.c.purchase_number > 1,
            )
        )
        or 0
    )
    charges = sum(x["charges"] for x in totals.values())
    pending_receipts = (
        db.scalar(
            select(func.count())
            .select_from(m.BankReceipt)
            .join(m.Payment, m.Payment.id == m.BankReceipt.payment_id)
            .where(m.BankReceipt.tenant_id == tid, *scope(m.Payment), m.BankReceipt.status == "PENDING")
        )
        or 0
    )
    historical = dict(
        db.execute(
            select(m.SubscriptionHistory.action, func.count())
            .join(m.Subscription, m.Subscription.id == m.SubscriptionHistory.subscription_id)
            .where(
                *scope(m.Subscription),
                m.SubscriptionHistory.tenant_id == tid,
                m.SubscriptionHistory.created_at >= starts_at,
                m.SubscriptionHistory.created_at < ends_at,
            )
            .group_by(m.SubscriptionHistory.action)
        ).all()
    )
    mrr = [
        dict(x)
        for x in db.execute(
            select(m.Payment.currency, func.sum(m.Payment.amount_minor).label("amount_minor"))
            .join(m.Subscription, m.Subscription.payment_id == m.Payment.id)
            .where(
                *scope(m.Payment),
                *scope(m.Subscription),
                m.Payment.recurring.is_(True),
                m.Payment.provider == "TELEGRAM_STARS",
                m.Subscription.status == "ACTIVE",
                m.Subscription.auto_renew.is_(True),
                m.Subscription.expires_at > now,
            )
            .group_by(m.Payment.currency)
        ).mappings()
    ]
    channels = [
        dict(x)
        for x in db.execute(
            select(m.Channel.title, func.count(m.ChannelInvite.id).label("joins"))
            .join(m.ChannelInvite, m.ChannelInvite.channel_id == m.Channel.id)
            .where(
                *scope(m.Channel),
                m.ChannelInvite.tenant_id == tid,
                m.ChannelInvite.used_at >= starts_at,
                m.ChannelInvite.used_at < ends_at,
            )
            .group_by(m.Channel.id, m.Channel.title)
            .order_by(func.count().desc())
            .limit(20)
        ).mappings()
    ]
    invites = (
        db.scalar(
            select(func.count())
            .select_from(m.AccessRedemption)
            .join(m.AccessOffer, m.AccessOffer.id == m.AccessRedemption.offer_id)
            .where(
                *scope(m.AccessOffer),
                m.AccessRedemption.tenant_id == tid,
                m.AccessRedemption.created_at >= starts_at,
                m.AccessRedemption.created_at < ends_at,
            )
        )
        or 0
    )
    # Imported records have no reconstructible history before the migration.
    coverage = db.scalar(
        select(func.max(m.SubscriptionHistory.created_at))
        .join(m.Subscription, m.Subscription.id == m.SubscriptionHistory.subscription_id)
        .where(*scope(m.Subscription), m.SubscriptionHistory.action == "MIGRATED")
    )
    cohort_size = churned = churn = None
    if coverage is None or starts_at > coverage:
        initial, final = active_cohort(bot, starts_at), active_cohort(bot, ends_at)
        cohort_size = db.scalar(select(func.count()).select_from(initial.subquery())) or 0
        churned = db.scalar(select(func.count()).select_from(initial.except_(final).subquery())) or 0
        churn = round(churned * 100 / cohort_size, 2) if cohort_size else None
    return {
        "starts_at": starts_at,
        "ends_at": ends_at,
        "current_snapshot_at": now,
        "users_total": contacts[0],
        "users_new": contacts[1],
        "users_active_7d": contacts[2],
        "growth_percent": round(contacts[1] * 100 / contacts[3], 2) if contacts[3] else None,
        "users_without_active_subscription": contacts[0] - active_contacts,
        "subscriptions_active": active,
        "subscriptions_expiring_7d": count(
            m.Subscription,
            m.Subscription.status == "ACTIVE",
            m.Subscription.expires_at > now,
            m.Subscription.expires_at <= now + 7 * 86400,
        ),
        "subscriptions_expired": count(m.Subscription, m.Subscription.expires_at <= now),
        "subscriptions_by_status": subscription_counts,
        "subscriptions_new": count(
            m.Subscription, m.Subscription.created_at >= starts_at, m.Subscription.created_at < ends_at
        ),
        "payments_pending": count(m.Payment, m.Payment.status.in_(["PENDING", "RECEIPT_SUBMITTED"])),
        "receipts_pending": pending_receipts,
        "buyers": buyers,
        "conversion_percent": round(buyers * 100 / contacts[0], 2) if contacts[0] else 0,
        "revenues": sorted(totals.values(), key=lambda x: x["currency"]),
        "payment_methods": methods,
        "plans": plans,
        "channels": channels,
        "mrr": mrr,
        "renewals": renewals,
        "renewal_share_percent": round(renewals * 100 / charges, 2) if charges else 0,
        "churn_percent": churn,
        "paid_cohort_start": cohort_size,
        "paid_cohort_lost": churned,
        "history_coverage_from": coverage,
        "cancellations": historical.get("CANCEL", 0),
        "invitations_used": invites,
    }


def csv_cell(value):
    if isinstance(value, (int, float)):
        return value
    value = str(value)
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


class ReportService:
    def __init__(self, runtime):
        self.r = runtime

    def request(self, db, bot, actor, starts_at, ends_at):
        if not 0 <= starts_at < ends_at or ends_at - starts_at > 367 * 86400:
            raise DomainError("INVALID_PERIOD", "El periodo máximo es de un año.")
        reserve_limit(db, bot.tenant_id, "exports_month", period=datetime.now(timezone.utc).strftime("%Y-%m"))
        report = m.Report(
            id=m.uid(),
            tenant_id=bot.tenant_id,
            bot_id=bot.id,
            actor_id=actor.id,
            starts_at=starts_at,
            ends_at=ends_at,
            expires_at=m.now() + 7 * 86400,
        )
        db.add(report)
        db.flush()
        enqueue(db, "REPORT", bot.tenant_id, {"report_id": report.id}, "report:" + report.id, bot.id)
        audit(
            db,
            bot.tenant_id,
            actor.id,
            "REPORT_REQUESTED",
            report.id,
            {"starts_at": starts_at, "ends_at": ends_at},
        )
        return report

    def generate(self, db, bot, report):
        if report.status == "READY":
            return
        from .console import Console

        actor = db.get(m.PlatformUser, report.actor_id)
        ui = Console(self.r, db, bot, {"update_id": 0}, {"id": actor.telegram_user_id})
        ui.ctx(bot.tenant_id, "export")
        data = snapshot(db, bot, report.starts_at, report.ends_at)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["section", "metric", "reference", "currency", "value"])
        for key, value in data.items():
            if not isinstance(value, (list, dict)):
                writer.writerow(["summary", key, "", "", "N/A" if value is None else value])
        writer.writerow(
            ["definition", "net", "captures minus refunds in period; before fees/taxes/SaaS", "", ""]
        )
        writer.writerow(
            [
                "definition",
                "renewal_share_percent",
                "repeat paid purchases of same plan / all paid purchases",
                "",
                "",
            ]
        )
        writer.writerow(
            [
                "definition",
                "churn_percent",
                "paid customers active at start with no active paid subscription at end",
                "",
                "",
            ]
        )
        for section in ("revenues", "payment_methods", "plans", "channels", "mrr"):
            for row in data[section]:
                for key, value in row.items():
                    writer.writerow(
                        [
                            section,
                            key,
                            csv_cell(
                                row.get("id", row.get("name", row.get("provider", row.get("title", ""))))
                            ),
                            row.get("currency", ""),
                            csv_cell(value),
                        ]
                    )
        query = (
            select(m.PaymentCharge, m.Payment, m.Contact)
            .join(m.Payment, m.Payment.id == m.PaymentCharge.payment_id)
            .join(m.Contact, m.Contact.id == m.Payment.contact_id)
            .where(
                m.PaymentCharge.tenant_id == bot.tenant_id,
                m.PaymentCharge.bot_id == bot.id,
                m.Payment.bot_id == bot.id,
                m.Contact.bot_id == bot.id,
                m.PaymentCharge.created_at >= report.starts_at,
                m.PaymentCharge.created_at < report.ends_at,
            )
            .order_by(m.PaymentCharge.created_at, m.PaymentCharge.id)
        )
        index = 0
        for charge, payment, person in db.execute(query.execution_options(yield_per=500)):
            index += 1
            self._check_size(index, stream)
            writer.writerow(["capture", charge.created_at, charge.id, charge.currency, charge.amount_minor])
            writer.writerow(
                [
                    "customer",
                    charge.id,
                    str(person.telegram_user_id),
                    payment.provider,
                    csv_cell(person.username or person.first_name),
                ]
            )
        refunds = (
            select(m.PaymentRefund)
            .where(
                m.PaymentRefund.tenant_id == bot.tenant_id,
                m.PaymentRefund.bot_id == bot.id,
                m.PaymentRefund.created_at >= report.starts_at,
                m.PaymentRefund.created_at < report.ends_at,
            )
            .order_by(m.PaymentRefund.created_at, m.PaymentRefund.id)
        )
        for refund in db.scalars(refunds.execution_options(yield_per=500)):
            index += 1
            self._check_size(index, stream)
            writer.writerow(
                ["refund", refund.created_at, refund.charge_id, refund.currency, -refund.amount_minor]
            )
            writer.writerow(
                [
                    "refund_reference",
                    refund.id,
                    csv_cell(refund.reference),
                    refund.provider,
                    csv_cell(refund.reason),
                ]
            )
        writer.writerow(["metadata", "bot", bot.id, "", csv_cell(bot.username)])
        writer.writerow(
            ["metadata", "status_counts", "", "", json.dumps(data["subscriptions_by_status"], sort_keys=True)]
        )
        report.summary = data
        report.content_ciphertext = self.r.vault.encrypt(
            stream.getvalue(), f"{bot.tenant_id}:{report.id}:report"
        )
        report.status = "READY"
        from .i18n import t

        send(
            db,
            bot,
            actor.telegram_user_id,
            t("report_ready", actor.locale),
            "report-delivery:" + report.id,
            report_id=report.id,
            viewer_id=actor.telegram_user_id,
            service_message=True,
        )

    @staticmethod
    def _check_size(index, stream):
        if index > 50000 or stream.tell() > 8 * 1024 * 1024:
            raise DomainError(
                "REPORT_TOO_LARGE", "El reporte es demasiado grande. Solicita periodos más cortos."
            )

    def read(self, report):
        if report.status != "READY" or report.expires_at <= m.now():
            raise DomainError("REPORT_EXPIRED", "El reporte caducó. Genera uno nuevo.")
        return self.r.vault.decrypt(
            report.content_ciphertext, f"{report.tenant_id}:{report.id}:report"
        ).encode("utf-8-sig")
