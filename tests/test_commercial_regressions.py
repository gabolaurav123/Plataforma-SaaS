import io
import json
import re
import string

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from platform_app import models as m
from platform_app.errors import DomainError
from platform_app.ingress import create_ingress
from platform_app.services import business, console_business, console_saas, tenants
from platform_app.services.console import Console
from platform_app.services.i18n import CATALOG, t
from conftest import bot_parts
from test_commercial_core import activate, create_charge


def test_translation_placeholders_match_in_every_language():
    formatter = string.Formatter()
    for key, values in CATALOG.items():

        def fields(value):
            return sorted(
                (name, spec, conversion)
                for _, name, spec, conversion in formatter.parse(value)
                if name is not None
            )

        assert len(values) == 3, key
        assert all(fields(values[0]) == fields(value) for value in values[1:]), key
        assert all(value for value in values), key


def test_old_worker_environment_cannot_reintroduce_a_seven_day_trial():
    from platform_app.config import Settings

    assert Settings(trial_days="7").trial_days == 3


def test_invoice_summary_includes_real_usage_sales_and_amount_due(env):
    cycle_id = activate(env)
    with env["r"].db.system() as db:
        create_charge(db, env, amount=100000, currency="USD")
        invoice = env["r"].ledger.finalize(db, db.get(m.BillingCycle, cycle_id))
        summary = console_saas.invoice_summary(invoice)
        assert "SALDO A PAGAR: USD 70.00" in summary
        assert "1000.00 USD" in summary and "Comisión del plan: 4%" in summary
        assert "Bots: 1/3" in summary and "Contactos registrados: 1/10000" in summary
        assert invoice.breakdown["usage"]["bots"] == 1


def test_saas_summary_is_queued_and_keeps_reply_order(env):
    from platform_app.services.background import process

    with env["r"].db.system() as db:
        ui = Console(env["r"], db, None, {"update_id": 80808}, {"id": 101})
        console_saas.billing(ui, env["ta"])
        job = db.scalar(select(m.Job).where(m.Job.kind == "SAAS_SUMMARY"))
        assert job and job.lane == "background"
        process(env["r"], db, job, None)
        db.flush()
        replies = list(
            db.scalars(
                select(m.Job).where(m.Job.dedup_key.like("console:master:80808:%")).order_by(m.Job.sequence)
            )
        )
        assert len(replies) == 2
        assert "Preparando" in replies[0].payload["text"]
        assert "Recursos utilizados" in replies[1].payload["text"]


@pytest.mark.parametrize("language", ["es", "en", "pt"])
def test_every_business_home_button_has_a_working_localized_destination(env, language):
    runtime = env["r"]
    runtime.settings.deployment_mode = "telegram"
    with runtime.db.system() as db:
        user, bot = db.get(m.PlatformUser, env["ua"]), db.get(m.ManagedBot, env["ba"])
        user.locale = language
        ui = Console(runtime, db, bot, {"update_id": 600001}, {"id": user.telegram_user_id})
        console_business.home(ui)
        db.flush()
        buttons = list(
            db.scalars(
                select(m.ConsoleButton).where(
                    m.ConsoleButton.bot_key == bot.id,
                    m.ConsoleButton.telegram_user_id == user.telegram_user_id,
                )
            )
        )
        home_actions = [
            (button.action, dict(button.data))
            for button in buttons
            if button.action not in {"home", "biz:home", "__back", "biz:preview"}
        ]
        assert len(home_actions) >= 20
        for action, data in home_actions:
            console_business.dispatch(ui, action.removeprefix("biz:"), data)
        plan = db.scalar(select(m.Plan).where(m.Plan.bot_id == bot.id))
        console_business.detail(ui, {"resource": "plans", "id": plan.id})
        for provider in ["BANK_TRANSFER", "STRIPE", "PAYPAL", "TELEGRAM_STARS"]:
            console_business.dispatch(ui, "method_edit", {"provider": provider})
        db.flush()
        messages = list(db.scalars(select(m.Job).where(m.Job.dedup_key.like(f"console:{bot.id}:600001:%"))))
        assert len(messages) >= 20
        for job in messages:
            assert not re.search(r"ui_[0-9a-f]{10}", json.dumps(job.payload)), job.payload
            assert "{p0}" not in job.payload["text"]
        assert any(t("admin_mode", language) in job.payload["text"] for job in messages)


@pytest.mark.parametrize("language", ["es", "en", "pt"])
def test_master_billing_forms_use_the_selected_language(env, language):
    cycle_id = activate(env)
    with env["r"].db.system() as db:
        user = db.get(m.PlatformUser, env["ua"])
        user.locale = language
        ui = Console(env["r"], db, None, {"update_id": 600002}, {"id": user.telegram_user_id})
        console_saas.workspace(ui, env["ta"])
        console_saas.billing(ui, env["ta"], prepared=True)
        invoice = env["r"].ledger.finalize(db, db.get(m.BillingCycle, cycle_id))
        console_saas.invoice_view(ui, invoice)
        db.flush()
        jobs = list(db.scalars(select(m.Job).where(m.Job.dedup_key.like("console:master:600002:%"))))
        assert jobs and all(not re.search(r"ui_[0-9a-f]{10}", json.dumps(x.payload)) for x in jobs)
        assert any(
            {"es": "Tu cuenta SaaS", "en": "Your SaaS account", "pt": "Sua conta SaaS"}[language]
            in x.payload["text"]
            for x in jobs
        )


def test_admin_suspension_survives_verified_settlement_and_plan_selection(env):
    cycle_id = activate(env)
    with env["r"].db.system() as db:
        tenant, user = db.get(m.Tenant, env["ta"]), db.get(m.PlatformUser, env["ua"])
        invoice = env["r"].ledger.finalize(db, db.get(m.BillingCycle, cycle_id))
        settlement = env["r"].ledger.submit(
            db, invoice, user, "BANK_TRANSFER", "verified-bank-reference", 3000
        )
        db.flush()
        tenant.admin_suspended_at, tenant.status = m.now(), "SUSPENDED"
        env["r"].ledger.review(db, settlement, "root", True)
        assert invoice.status == "PAID" and tenant.status == "SUSPENDED"
        with pytest.raises(DomainError):
            tenants.entitlement(db, tenant.id)
        with pytest.raises(DomainError, match="suspendió"):
            env["r"].ledger.select_plan(db, tenant.id, db.get(m.BillingCycle, cycle_id).plan_id, user)


def test_free_extension_moves_the_current_cycle_and_creates_no_payment(env):
    cycle_id = activate(env)
    with env["r"].db.system() as db:
        cycle = db.get(m.BillingCycle, cycle_id)
        previous_end, previous_due = cycle.ends_at, cycle.due_at
        tenant = db.get(m.Tenant, env["ta"])
        env["r"].ledger.grant_access(db, tenant, 7, "root")
        sub = db.scalar(select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == tenant.id))
        assert sub.current_period_end == cycle.ends_at == previous_end + 7 * 86400
        assert cycle.due_at == previous_due + 7 * 86400
        assert (cycle.fixed_usd_minor, cycle.commission_bps) == (3000, 400)
        env["r"].ledger.advance(db, sub, previous_end)
        assert db.scalar(select(func.count()).select_from(m.PlatformInvoice)) == 0
        assert db.scalar(select(func.count()).select_from(m.PlatformSettlement)) == 0


def test_cancelled_trial_does_not_become_payment_pending(env, monkeypatch):
    with env["r"].db.system() as db:
        sub = db.scalar(select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == env["ta"]))
        sub.cancelled_at = m.now()
        monkeypatch.setattr(m, "now", lambda: sub.trial_ends_at + 1)
        env["r"].ledger.tick(db)
        assert sub.status == db.get(m.Tenant, env["ta"]).status == "CANCELLED"


def test_imported_or_background_identity_does_not_erase_a_username(env):
    with env["r"].db.system() as db:
        user = tenants.upsert_user(
            db, {"id": 505, "first_name": "Person", "username": "original", "language_code": "pt-BR"}
        )
        same = tenants.upsert_user(db, {"id": 505})
        assert same.id == user.id and same.username == "original" and same.locale == "pt"
        tenants.upsert_user(db, {"id": 505, "first_name": "Renamed", "username": "newname"})
        assert user.username == "newname"


def test_menu_updates_are_claimed_ahead_of_a_large_background_backlog(env):
    from platform_app.services.common import enqueue
    from platform_app.worker import Worker

    with env["r"].db.system() as db:
        db.add_all(
            [
                m.Job(
                    tenant_id=env["ta"],
                    bot_id=env["ba"],
                    kind="REPORT",
                    lane="background",
                    payload={},
                    dedup_key=f"bulk:{i}",
                    run_at=m.now() - 100,
                )
                for i in range(300)
            ]
        )
        target = enqueue(db, "UPDATE", env["ta"], {}, "interactive:update", env["ba"], lane="interactive")
        identifier = target.id
    assert Worker(env["r"], "interactive").claim() == identifier


def test_cross_payment_duplicate_proof_requires_explicit_bank_verification(env):
    bot, person, plan = bot_parts(env)
    data = io.BytesIO()
    Image.new("RGB", (32, 32), "green").save(data, format="PNG")
    with env["r"].db.system() as db:
        db.get(m.Plan, plan.id).product_kind = "PHYSICAL"
        first = env["r"].payments.create(db, bot, person, plan.id, "BANK_TRANSFER", "MXN", "proof-one")
        second = env["r"].payments.create(db, bot, person, plan.id, "BANK_TRANSFER", "MXN", "proof-two")
        env["r"].receipts.submit(db, bot, first, data.getvalue())
        duplicate = env["r"].receipts.submit(db, bot, second, data.getvalue())
        assert duplicate.duplicate
        with pytest.raises(DomainError):
            env["r"].receipts.review(db, bot, duplicate, env["ua"], "APPROVE")
        assert db.scalar(select(func.count()).select_from(m.PaymentCharge)) == 0


def test_cancellation_creates_one_real_notification_event(env):
    bot, person, plan = bot_parts(env)
    with env["r"].db.system() as db:
        sub = business.grant_subscription(db, bot, person, plan, env["ua"], 3, "Gift", "new-gift")
        business.manage_subscription(db, bot, sub, env["ua"], "CANCEL", "cancel-once", reason="Requested")
        business.manage_subscription(db, bot, sub, env["ua"], "CANCEL", "cancel-once", reason="Requested")
        jobs = list(db.scalars(select(m.Job).where(m.Job.kind == "BUSINESS_NOTICE")))
        assert len(jobs) == 1 and jobs[0].payload["category"] == "cancel"


def test_unexpected_webhook_failures_do_not_escape_to_access_logs(env, monkeypatch):
    import platform_app.ingress as ingress

    env["r"].settings.payment_webhooks_enabled = True

    def failure(*args):
        raise RuntimeError("private-marker")

    monkeypatch.setattr(ingress, "receive", failure)
    with TestClient(create_ingress(env["r"])) as client:
        result = client.post("/payments/hooks/secret-path", content=b"{}")
        assert result.status_code == 503
        assert result.json() == {"code": "WEBHOOK_UNAVAILABLE"}


def test_missing_currency_cannot_be_used_to_reactivate_without_settlement(env, monkeypatch):
    cycle_id = activate(env)
    with env["r"].db.system() as db:
        create_charge(db, env, amount=1000, currency="XTR")
        cycle = db.get(m.BillingCycle, cycle_id)
        env["r"].ledger.finalize(db, cycle)
        sub = db.scalar(select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == env["ta"]))
        sub.cancelled_at = m.now()
        monkeypatch.setattr(m, "now", lambda: cycle.ends_at + 1)
        with pytest.raises(DomainError, match="facturas"):
            env["r"].ledger.select_plan(db, env["ta"], sub.plan_id, db.get(m.PlatformUser, env["ua"]))
