import pytest
from sqlalchemy import select, func
from platform_app import models as m
from platform_app.errors import DomainError
from platform_app.services import reporting, refunds, business
from platform_app.services.notifications import schedule_summaries, deliver_summary
from platform_app.services.tenants import upsert_user
from conftest import bot_parts
from test_commercial_core import create_charge


def test_cash_reports_keep_captures_and_partial_refunds_in_their_actual_periods(env, monkeypatch):
    timestamp = m.now()
    bot, _, _ = bot_parts(env)
    with env["r"].db.system() as db:
        charge = create_charge(db, env, amount=10000)
        charge.created_at = timestamp - 100
        first = refunds.record(db, env["r"], bot, charge, 2500, "refund-a", env["ua"])
        first.created_at = timestamp - 10
        assert refunds.record(db, env["r"], bot, charge, 2500, "refund-a", env["ua"]).id == first.id
        old = reporting.snapshot(db, bot, timestamp - 110, timestamp - 90)["revenues"][0]
        assert (old["gross_minor"], old["refund_minor"], old["net_minor"]) == (10000, 0, 10000)
        recent = reporting.snapshot(db, bot, timestamp - 20, timestamp + 1)["revenues"][0]
        assert (recent["gross_minor"], recent["refund_minor"], recent["net_minor"]) == (0, 2500, -2500)
        refunds.record(db, env["r"], bot, charge, 7500, "refund-b", env["ua"])
        whole = reporting.snapshot(db, bot, timestamp - 110, timestamp + 1)["revenues"][0]
        assert (whole["gross_minor"], whole["refund_minor"], whole["net_minor"]) == (10000, 10000, 0)
        assert charge.refunded_at
        with pytest.raises(DomainError):
            refunds.record(db, env["r"], bot, charge, 1, "refund-c", env["ua"])


def test_currency_and_bot_boundaries_in_reports_and_csv(env):
    bot, _, _ = bot_parts(env)
    other, _, _ = bot_parts(env, "b")
    with env["r"].db.system() as db:
        create_charge(db, env, amount=10000, reference="usd")
        create_charge(db, env, amount=80, currency="XTR", reference="stars")
        data = reporting.snapshot(db, bot, m.now() - 10, m.now() + 1)
        assert {row["currency"]: row["gross_minor"] for row in data["revenues"]} == {"USD": 10000, "XTR": 80}
        assert reporting.snapshot(db, other, m.now() - 10, m.now() + 1)["revenues"] == []
        actor = db.get(m.PlatformUser, env["ua"])
        report = env["r"].reports.request(db, bot, actor, m.now() - 10, m.now() + 1)
        env["r"].reports.generate(db, bot, report)
        text = env["r"].reports.read(report).decode("utf-8-sig")
        assert "USD,10000" in text and "XTR,80" in text
        assert "900002" not in text and "ciphertext" not in text
        report.expires_at = m.now() - 1
        with pytest.raises(DomainError):
            env["r"].reports.read(report)


def test_manual_access_is_idempotent_free_and_preserves_history(env):
    bot, person, plan = bot_parts(env)
    with env["r"].db.system() as db:
        sub = business.grant_subscription(db, bot, person, plan, env["ua"], 10, "Promoción", "manual-test")
        same = business.grant_subscription(db, bot, person, plan, env["ua"], 10, "Promoción", "manual-test")
        assert sub.id == same.id and sub.origin == "MANUAL" and sub.payment_id is None
        assert db.scalar(select(func.count()).select_from(m.PaymentCharge)) == 0
        business.manage_subscription(
            db, bot, sub, env["ua"], "GIFT_DAYS", "gift-extra", days=2, reason="Cortesía"
        )
        changes = list(
            db.scalars(
                select(m.SubscriptionHistory)
                .where(m.SubscriptionHistory.subscription_id == sub.id)
                .order_by(m.SubscriptionHistory.revision)
            )
        )
        assert [x.revision for x in changes] == [1, 2]
        assert changes[1].after["expires_at"] - changes[0].after["expires_at"] == 2 * 86400


def test_reports_never_invent_churn_for_imported_history(env):
    bot, person, plan = bot_parts(env)
    with env["r"].db.system() as db:
        sub = business.grant_subscription(db, bot, person, plan, env["ua"], 10, "Migración", "historical")
        entry = db.scalar(
            select(m.SubscriptionHistory).where(m.SubscriptionHistory.subscription_id == sub.id)
        )
        entry.action = "MIGRATED"
        data = reporting.snapshot(db, bot, m.now() - 86400, m.now() + 1)
        assert data["churn_percent"] is None and data["history_coverage_from"] == entry.created_at


def test_scheduled_summaries_are_unique_and_can_be_disabled_before_send(env):
    bot, _, _ = bot_parts(env)
    with env["r"].db.system() as db:
        config = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
        config.preferences = {
            "timezone": "America/La_Paz",
            "notifications": {"daily": True, "weekly": True, "monthly": True},
        }
        schedule_summaries(db)
        schedule_summaries(db)
        jobs = list(db.scalars(select(m.Job).where(m.Job.kind == "BUSINESS_SUMMARY", m.Job.bot_id == bot.id)))
        assert len(jobs) == 3
        daily = next(x for x in jobs if x.payload["category"] == "daily")
        assert daily.payload["ends_at"] - daily.payload["starts_at"] == 86400
        deliver_summary(db, env["r"], bot, daily)
        assert (
            db.scalar(
                select(func.count()).select_from(m.Job).where(m.Job.dedup_key.like("summary-delivery:%"))
            )
            == 1
        )
        config.preferences = {"notifications": {"weekly": False}}
        deliver_summary(db, env["r"], bot, next(x for x in jobs if x.payload["category"] == "weekly"))
        assert (
            db.scalar(
                select(func.count()).select_from(m.Job).where(m.Job.dedup_key.like("summary-delivery:%"))
            )
            == 1
        )


def test_custom_team_roles_cannot_escalate_or_cross_bot(env):
    bot, _, _ = bot_parts(env)
    with env["r"].db.system() as db:
        user = upsert_user(db, {"id": 404, "first_name": "Support"})
        row = business.set_admin(db, bot, env["ua"], 404, "CUSTOM", ["read", "support", "team"])
        assert row.bot_id == bot.id
        with pytest.raises(DomainError, match="permisos"):
            business.set_admin(db, bot, user.id, 202, "ADMIN")
        assert (
            db.scalar(select(func.count()).select_from(m.BotAdmin).where(m.BotAdmin.bot_id == env["bb"])) == 0
        )


def test_dst_period_is_local_calendar_day_not_fixed_24_hours():
    from datetime import datetime, timezone

    stamp = int(datetime(2026, 3, 8, 12, tzinfo=timezone.utc).timestamp())
    start, _ = reporting.bounds("today", "America/New_York", stamp)
    assert datetime.fromtimestamp(start, timezone.utc).hour == 5
