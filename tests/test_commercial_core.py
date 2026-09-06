from decimal import Decimal
import json
import pytest
from sqlalchemy import select, func
from platform_app import models as m
from platform_app.errors import DomainError
from platform_app.services import tenants
from platform_app.services.billing_ledger import MONTH, set_rate
from platform_app.services.business import plan_channels, save_channels
from platform_app.api.webhooks import store_update
from platform_app.worker import Worker
from conftest import bot_parts


def activate(env, name="PRO"):
    r = env["r"]
    with r.db.system() as db:
        plan = db.scalar(select(m.SaaSPlan).where(m.SaaSPlan.name == name))
        actor = db.get(m.PlatformUser, env["ua"])
        r.ledger.select_plan(db, env["ta"], plan.id, actor)
        cycle = db.scalar(select(m.BillingCycle).where(m.BillingCycle.tenant_id == env["ta"]))
        return cycle.id


def test_trial_begins_explicitly_and_is_once_per_owner(env):
    with env["r"].db.system() as db:
        actor = tenants.upsert_user(db, {"id": 303, "first_name": "C"})
        assert actor.trial_used_at is None
        first = tenants.create_tenant(db, actor, "Workspace one", env["r"].settings, activate_trial=False)
        sub = db.scalar(select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == first.id))
        assert sub.status == "PAYMENT_PENDING" and sub.trial_starts_at is None
        env["r"].ledger.activate_trial(db, first, actor)
        assert sub.trial_ends_at - sub.trial_starts_at == 3 * 86400
        assert env["r"].ledger.activate_trial(db, first, actor).id == sub.id
        second = tenants.create_tenant(db, actor, "Workspace two", env["r"].settings, activate_trial=False)
        with pytest.raises(DomainError, match="prueba"):
            env["r"].ledger.activate_trial(db, second, actor)


def test_three_commercial_plans_have_explicit_terms(env):
    with env["r"].db.system() as db:
        rows = {x.name: (x.fixed_usd_minor, x.commission_bps) for x in db.scalars(select(m.SaaSPlan))}
        assert rows == {"STARTER": (0, 800), "PRO": (3000, 400), "AGENCY": (8000, 100)}


def create_charge(db, env, amount=100000, currency="USD", reference="example"):
    bot, person, plan = bot_parts(env)
    pay = m.Payment(
        id=m.uid(),
        tenant_id=bot.tenant_id,
        bot_id=bot.id,
        contact_id=person.id,
        plan_id=plan.id,
        provider="BANK_TRANSFER",
        currency=currency,
        amount_minor=amount,
        idempotency_key=reference,
        invoice_payload=m.uid(),
    )
    db.add(pay)
    db.flush()
    charge = m.PaymentCharge(
        id=m.uid(),
        tenant_id=bot.tenant_id,
        bot_id=bot.id,
        payment_id=pay.id,
        provider=pay.provider,
        currency=currency,
        amount_minor=amount,
        charge_id=reference,
    )
    db.add(charge)
    db.flush()
    env["r"].ledger.sale(db, charge)
    return charge


def test_thirty_dollar_plan_thousand_revenue_is_seventy_due(env):
    cycle_id = activate(env)
    with env["r"].db.system() as db:
        charge = create_charge(db, env)
        env["r"].ledger.sale(db, charge)
        cycle = db.get(m.BillingCycle, cycle_id)
        assert cycle.ends_at - cycle.starts_at == MONTH
        assert db.scalar(select(func.count()).select_from(m.CommissionEntry)) == 1
        invoice = env["r"].ledger.finalize(db, cycle)
        assert (invoice.fixed_minor, invoice.commission_minor, env["r"].ledger.outstanding(invoice)) == (
            3000,
            4000,
            7000,
        )
        assert env["r"].ledger.finalize(db, cycle).id == invoice.id


def test_missing_fx_blocks_finalization_and_rate_snapshot_is_immutable(env):
    cycle_id = activate(env)
    with env["r"].db.system() as db:
        create_charge(db, env, amount=1000, currency="XTR")
        invoice = env["r"].ledger.finalize(db, db.get(m.BillingCycle, cycle_id))
        assert invoice.status == "NEEDS_RATE" and invoice.commission_minor is None
        set_rate(db, "XTR", "1.25", env["ua"])
        env["r"].ledger.resolve_rates(db, db.get(m.BillingCycle, cycle_id), env["ua"])
        assert invoice.commission_minor == 50
        set_rate(db, "XTR", "3", env["ua"])
        entry = db.scalar(select(m.CommissionEntry))
        assert Decimal(entry.usd_rate) == Decimal("1.25")
        assert invoice.commission_minor == 50


def test_plan_change_applies_next_cycle_without_rewriting_earlier_income(env):
    activate(env)
    with env["r"].db.system() as db:
        create_charge(db, env)
        agency = db.scalar(select(m.SaaSPlan).where(m.SaaSPlan.name == "AGENCY"))
        actor = db.get(m.PlatformUser, env["ua"])
        change = env["r"].ledger.select_plan(db, env["ta"], agency.id, actor)
        assert change["scheduled"]
        sub = db.scalar(select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == env["ta"]))
        env["r"].ledger.advance(db, sub, sub.current_period_end)
        cycles = list(
            db.scalars(
                select(m.BillingCycle)
                .where(m.BillingCycle.tenant_id == env["ta"])
                .order_by(m.BillingCycle.starts_at)
            )
        )
        assert [x.commission_bps for x in cycles] == [400, 100]
        assert db.scalar(select(m.CommissionEntry)).commission_bps == 400


def test_platform_settlement_review_is_idempotent_and_does_not_create_customer_money(env):
    cycle_id = activate(env)
    with env["r"].db.system() as db:
        create_charge(db, env)
        invoice = env["r"].ledger.finalize(db, db.get(m.BillingCycle, cycle_id))
        actor = db.get(m.PlatformUser, env["ua"])
        settlement = env["r"].ledger.submit(db, invoice, actor, "CRYPTO", "network:transaction123", 7000)
        db.flush()
        env["r"].ledger.review(db, settlement, "platform-owner", True, "Ingreso confirmado en wallet")
        env["r"].ledger.review(db, settlement, "platform-owner", True)
        assert invoice.paid_minor == 7000 and invoice.status == "PAID"
        assert db.scalar(select(func.count()).select_from(m.PaymentCharge)) == 1
        assert db.scalar(select(func.count()).select_from(m.PlatformSettlement)) == 1


def test_plain_bot_token_never_enters_persisted_telegram_payload(env):
    r = env["r"]
    r.settings.deployment_mode = "telegram"
    token = "700010:" + "S" * 35
    incoming = {
        "update_id": 555,
        "message": {
            "message_id": 555,
            "chat": {"id": 101, "type": "private"},
            "from": {"id": 101, "first_name": "A"},
            "text": token,
        },
    }
    store_update(None, None, incoming, r)
    with r.db.system() as db:
        row = db.scalar(select(m.TelegramUpdate).where(m.TelegramUpdate.update_id == 555))
        assert token not in json.dumps(row.payload)
        assert token not in json.dumps(row.sensitive_ciphertext)
    while Worker(r).run_one():
        pass
    with r.db.system() as db:
        row = db.scalar(select(m.TelegramUpdate).where(m.TelegramUpdate.update_id == 555))
        assert row.status == "DONE" and row.sensitive_ciphertext is None


def test_token_validation_does_not_mutate_bot_before_explicit_confirmation(env):
    r = env["r"]
    with r.db.system() as db:
        actor = db.get(m.PlatformUser, env["ua"])
        attempt = r.connections.request(db, env["ta"], actor, "700020:" + "T" * 35, "new-connection")
        before = len(env["fake"].calls)
        r.connections.validate(db, attempt)
        methods = [method for _, method, _ in env["fake"].calls[before:]]
        assert methods == ["getMe", "getWebhookInfo"]
        assert attempt.status == "VALIDATED"
        with pytest.raises(DomainError):
            r.connections.confirm(db, attempt.id, env["tb"], db.get(m.PlatformUser, env["ub"]))


def test_free_invitation_preserves_plan_and_has_no_payment_or_commission(env):
    bot, person, plan = bot_parts(env)
    with env["r"].db.system() as db:
        offer = env["r"].invitations.create(db, bot, env["ua"], plan.id, 30, 1, m.now() + 3600)
        db.flush()
        code = env["r"].invitations.link(bot, offer).split("gift_")[1]
        sub = env["r"].invitations.redeem(db, bot, db.get(m.Contact, person.id), code)
        assert sub.plan_id == plan.id and sub.payment_id is None and sub.origin == "invite_link"
        assert sub.expires_at - sub.starts_at == 30 * 86400
        assert env["r"].invitations.redeem(db, bot, db.get(m.Contact, person.id), code).id == sub.id
        assert offer.uses == 1
        assert db.scalar(select(func.count()).select_from(m.PaymentCharge)) == 0
        assert db.scalar(select(func.count()).select_from(m.CommissionEntry)) == 0


def test_plan_cannot_include_channel_of_another_bot_in_same_workspace(env):
    bot, _, plan = bot_parts(env)
    with env["r"].db.system() as db:
        other = m.ManagedBot(
            id=m.uid(),
            tenant_id=bot.tenant_id,
            telegram_bot_id=900888,
            owner_telegram_user_id=101,
            public_id=m.uid(),
            username="other_bot",
            name="Other",
        )
        db.add(other)
        db.flush()
        channel = m.Channel(
            id=m.uid(), tenant_id=bot.tenant_id, bot_id=other.id, telegram_chat_id=-789, title="Other"
        )
        db.add(channel)
        db.flush()
        with pytest.raises(DomainError):
            save_channels(db, bot, db.get(m.Plan, plan.id), [channel.id], env["ua"])
        assert plan_channels(db, plan) == []
