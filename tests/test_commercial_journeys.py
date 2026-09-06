"""End-to-end business menu journeys; Telegram and payment delivery are simulated."""

import pytest
from sqlalchemy import select, func
from platform_app import models as m
from platform_app.errors import DomainError
from platform_app.services import (
    background,
    business,
    console_business,
    console_campaigns,
    console_saas,
    console_templates,
    reporting,
)
from platform_app.services.billing_ledger import setting
from platform_app.services.console import Console
from platform_app.services.crm import upsert_contact
from platform_app.services.i18n import t
from platform_app.services.texts import bot_text
from platform_app.worker import Worker
from test_workflows import success_event


@pytest.mark.parametrize("language", ["es", "en", "pt"])
def test_campaign_composer_preview_confirm_and_actual_delivery(env, language):
    r = env["r"]
    with r.db.system() as db:
        bot = db.get(m.ManagedBot, env["ba"])
        db.get(m.PlatformUser, env["ua"]).locale = language
        opted_out = upsert_contact(db, bot, {"id": 909009, "first_name": "Opted out"})
        opted_out.opted_out = True
        ui = Console(r, db, bot, {"update_id": 810001}, {"id": 101})
        console_business.context(ui, "sales")
        console_campaigns.dispatch(ui, "campaign", {})
        console_business.answer(ui, "Launch", {})
        console_business.answer(ui, "", {"photo": [{"file_id": "test-photo"}], "caption": "Hello {name}"})
        row = db.scalar(select(m.Campaign).where(m.Campaign.bot_id == bot.id))
        console_campaigns.dispatch(ui, "campaign_buttons", {"id": row.id})
        console_business.answer(ui, "Details | https://example.com/offer", {})
        console_campaigns.dispatch(ui, "campaign_preview", {"id": row.id})
        job = db.scalar(select(m.Job).where(m.Job.kind == "CAMPAIGN_PREVIEW"))
        background.process(r, db, job, bot)
        db.flush()
        preview = db.scalar(select(m.Job).where(m.Job.dedup_key == "campaign-preview-confirm:" + job.id))
        assert preview.payload["text"] == t("campaign_preview_notice", language, count=1)
        button = db.scalar(select(m.ConsoleButton).where(m.ConsoleButton.action == "biz:campaign_confirm"))
        assert button.telegram_user_id == 101
        console_campaigns.dispatch(ui, "campaign_confirm", button.data)
        db.flush()
        assert row.status == "RUNNING"
        r.campaigns.expand(db, row)
        db.flush()
        recipients = list(
            db.scalars(select(m.CampaignRecipient).where(m.CampaignRecipient.campaign_id == row.id))
        )
        assert len(recipients) == row.audience_count == 1
        job = db.scalar(select(m.Job).where(m.Job.dedup_key.like("campaign-recipient:" + row.id + ":%")))
        Worker(r).process_send(db, job, bot)
        assert recipients[0].status == "SENT"
        sent = [
            params
            for bid, method, params in env["fake"].calls
            if bid == bot.telegram_bot_id and method == "sendPhoto"
        ]
        assert len(sent) == 1 and sent[0]["chat_id"] == 900001
        assert sent[0]["caption"] == "Hello Client 0"
        assert sent[0]["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://example.com/offer"
        with pytest.raises(DomainError, match="confirmada"):
            console_campaigns.dispatch(ui, "campaign_confirm", button.data)


@pytest.mark.parametrize("language", ["es", "en", "pt"])
def test_template_edit_restore_and_publish_with_default_welcome(env, language):
    r = env["r"]
    with r.db.system() as db:
        bot, other = db.get(m.ManagedBot, env["ba"]), db.get(m.ManagedBot, env["bb"])
        ui = Console(r, db, bot, {"update_id": 810002}, {"id": 101})
        console_business.context(ui, "configure")
        previous = bot_text(db, bot, "WELCOME", locale=language, name="Alex")
        other_text = bot_text(db, other, "WELCOME", locale=language, name="Alex")
        console_templates.dispatch(ui, "template_edit", {"key": "WELCOME", "locale": language})
        console_templates.answer(ui, "template_value", dict(ui.state().data), "Custom {name}, {bot_name}")
        db.flush()
        assert bot_text(db, bot, "WELCOME", locale=language, name="Alex") == "Custom Alex, " + bot.name
        assert bot_text(db, other, "WELCOME", locale=language, name="Alex") == other_text
        console_templates.dispatch(ui, "template_restore", {"key": "WELCOME", "locale": language})
        db.flush()
        assert bot_text(db, bot, "WELCOME", locale=language, name="Alex") == previous
        assert r.provisioner.readiness(db, bot)["checks"]["welcome"]


@pytest.mark.parametrize(
    "method,fields",
    [
        (
            "BANK_TRANSFER",
            {
                "banco": "Example Bank",
                "titular": "Example Company",
                "cuenta": "DEMO-000",
                "moneda": "USD",
                "instrucciones": "Include invoice number",
            },
        ),
        (
            "CRYPTO",
            {
                "activo": "USDT",
                "red": "DEMO-NETWORK",
                "direccion": "PUBLIC-EXAMPLE-NOT-A-WALLET",
                "instrucciones": "Use the configured network",
            },
        ),
    ],
)
def test_saas_settlement_instructions_wizard_and_owner_boundary(env, method, fields):
    with env["r"].db.system() as db:
        ui = Console(env["r"], db, None, {"update_id": 810003}, {"id": 101})
        console_saas.dispatch(ui, "billing_method_edit", {"method": method})
        for value in fields.values():
            console_saas.answer(ui, value, {})
        assert setting(db, "billing_methods")[method] == {**fields, "enabled": True}
        assert not ui.state().data
        outsider = Console(env["r"], db, None, {"update_id": 810004}, {"id": 202})
        with pytest.raises(DomainError):
            console_saas.dispatch(outsider, "billing_method_edit", {"method": method})


def test_vip_tag_sends_one_localized_owner_notification(env):
    with env["r"].db.system() as db:
        bot = db.get(m.ManagedBot, env["ba"])
        person = db.scalar(select(m.Contact).where(m.Contact.bot_id == bot.id))
        config = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
        config.preferences = {"notifications": {"vip": True}}
        db.get(m.PlatformUser, env["ua"]).locale = "en"
        ui = Console(env["r"], db, bot, {"update_id": 810005}, {"id": 101})
        for update_id in [810005, 810006]:
            ui.update["update_id"] = update_id
            ui.state().data = {"flow": "biz:tags", "business": True, "id": person.id}
            console_business.answer(ui, "VIP", {})
        notices = list(db.scalars(select(m.Job).where(m.Job.dedup_key.like("notify:vip:%"))))
        assert len(notices) == 1
        assert notices[0].bot_id == bot.id and notices[0].payload["chat_id"] == 101
        assert notices[0].payload["text"] == t("vip_notice", "en", name=person.first_name)
        assert (
            db.scalar(
                select(func.count()).select_from(m.ContactTag).where(m.ContactTag.contact_id == person.id)
            )
            == 1
        )


def test_paid_cohort_churn_uses_historical_cancel_and_reactivation(env, monkeypatch):
    stamp = m.now()
    with env["r"].db.system() as db:
        bot = db.get(m.ManagedBot, env["ba"])
        person = db.scalar(select(m.Contact).where(m.Contact.bot_id == bot.id))
        plan = db.scalar(select(m.Plan).where(m.Plan.bot_id == bot.id))
        payment = env["r"].payments.create(db, bot, person, plan.id, "TELEGRAM_STARS", "XTR", "cohort")
        env["r"].payments.confirm_stars(db, bot, person.telegram_user_id, success_event(payment))
        sub = db.scalar(select(m.Subscription).where(m.Subscription.payment_id == payment.id))
        first = db.scalar(
            select(m.SubscriptionHistory).where(m.SubscriptionHistory.subscription_id == sub.id)
        )
        first.created_at = stamp - 100
        monkeypatch.setattr(m, "now", lambda: stamp + 10)
        business.manage_subscription(db, bot, sub, env["ua"], "CANCEL", "cohort-cancel", reason="Requested")
        db.flush()
        for entry in db.scalars(
            select(m.SubscriptionHistory).where(m.SubscriptionHistory.action == "CANCEL")
        ):
            entry.created_at = stamp + 10
        assert reporting.snapshot(db, bot, stamp, stamp + 20)["churn_percent"] == 100
        monkeypatch.setattr(m, "now", lambda: stamp + 30)
        business.manage_subscription(
            db, bot, sub, env["ua"], "REACTIVATE", "cohort-reactivate", reason="Resolved"
        )
        db.flush()
        for entry in db.scalars(
            select(m.SubscriptionHistory).where(m.SubscriptionHistory.action == "REACTIVATE")
        ):
            entry.created_at = stamp + 30
        assert reporting.snapshot(db, bot, stamp, stamp + 40)["churn_percent"] == 0
        assert reporting.snapshot(db, bot, stamp, stamp + 20)["churn_percent"] == 100
