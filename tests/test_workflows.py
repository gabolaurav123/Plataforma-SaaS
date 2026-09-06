import io
import pytest
from PIL import Image
from sqlalchemy import select, func
from platform_app import models as m
from platform_app.errors import DomainError
from platform_app.worker import Worker
from platform_app.services.common import enqueue, emit
from platform_app.services.crm import upsert_contact, conversation, reply
from platform_app.services.tenants import suspend_due
from conftest import bot_parts


def payment(env, provider="TELEGRAM_STARS", recurring=False):
    bot, contact, plan = bot_parts(env)
    with env["r"].db.system() as db:
        db.get(m.Plan, plan.id).recurring = recurring
        item = env["r"].payments.create(
            db,
            db.get(m.ManagedBot, bot.id),
            db.get(m.Contact, contact.id),
            plan.id,
            provider,
            "XTR" if provider == "TELEGRAM_STARS" else "MXN",
            m.uid(),
            context="TELEGRAM" if provider == "TELEGRAM_STARS" else "OFF_PLATFORM",
        )
        return item


def success_event(item, charge="charge-1", recurring=False, end=None):
    event = {
        "invoice_payload": item.invoice_payload,
        "currency": "XTR",
        "total_amount": item.amount_minor,
        "telegram_payment_charge_id": charge,
    }
    if recurring:
        event.update(is_recurring=True, subscription_expiration_date=end or m.now() + 2592000)
    return event


def test_creator_onboarding_persists_and_creates_managed_bot(env):
    r, client = env["r"], env["client"]
    base = f"/api/t/{env['ta']}"
    # Existing bot uses starter capacity; use a configured larger plan for this scenario.
    with r.db.system() as db:
        sub = db.scalar(select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == env["ta"]))
        db.get(m.SaaSPlan, sub.plan_id).limits = {"bots": 3, "admins": 2, "active_contacts": 1000}
    request = client.post(
        base + "/bots/create", headers=env["a"], json={"name": "Second Bot", "username": "second_test_bot"}
    )
    assert request.status_code == 200, request.text
    assert "/newbot/" in request.json()["url"] and request.json()["prepared_button_id"]
    with r.db.system() as db:
        info = {
            "bot": {"id": 800001, "is_bot": True, "username": "second_test_bot", "first_name": "Second"},
            "user": {"id": 101, "first_name": "Alice"},
        }
        created = r.manager.accept_managed_update(db, info)
        duplicate = r.manager.accept_managed_update(db, info)
        assert created.id == duplicate.id and created.tenant_id == env["ta"]
        bid = created.id
    r.provisioner.provision(bid)
    saved = client.put(base + "/onboarding", headers=env["a"], json={"step": 4, "bot_id": bid})
    assert saved.status_code == 200
    assert client.get(base + "/onboarding", headers=env["a"]).json()["step"] == 4


def test_management_mode_disabled_has_actionable_instructions(env):
    env["fake"].manage = False
    result = env["client"].get("/api/owner/master/capabilities", headers=env["a"])
    assert result.status_code == 200 and not result.json()["enabled"]
    assert result.json()["message"] == "Bot Management Mode no está habilitado."
    assert "BotFather" in " ".join(result.json()["instructions"])


def test_provision_rotation_and_token_refresh(env):
    r = env["r"]
    with r.db.system() as db:
        secret = db.scalar(select(m.BotSecret).where(m.BotSecret.bot_id == env["ba"]))
        old = secret.token_ciphertext
    r.provisioner.provision(env["ba"], rotate=True)
    with r.db.system() as db:
        secret = db.scalar(select(m.BotSecret).where(m.BotSecret.bot_id == env["ba"]))
        assert secret.token_ciphertext != old and secret.token_version == 2
        assert db.get(m.ManagedBot, env["ba"]).status == "READY"
    methods = [method for _, method, _ in env["fake"].calls]
    assert methods.index("replaceManagedBotToken") < len(methods) - 1
    assert "setWebhook" in methods[methods.index("replaceManagedBotToken") :]
    rotations = [p for _, method, p in env["fake"].calls if method == "replaceManagedBotToken"]
    assert rotations[-1]["user_id"] == 700001


def test_provision_failure_is_retriable(env):
    env["fake"].fail = "setWebhook"
    with pytest.raises(DomainError):
        env["r"].provisioner.provision(env["ba"])
    with env["r"].db.system() as db:
        assert db.get(m.ManagedBot, env["ba"]).status == "PROVISIONING_FAILED"
    env["fake"].fail = None
    env["r"].provisioner.provision(env["ba"])
    with env["r"].db.system() as db:
        assert db.get(m.ManagedBot, env["ba"]).status == "READY"


def test_ownership_transfer_does_not_move_customer_data(env):
    with env["r"].db.system() as db:
        result = env["r"].manager.accept_managed_update(
            db, {"bot": {"id": 700001, "is_bot": True}, "user": {"id": 303}}
        )
        assert result.status == "OWNERSHIP_CHANGED" and not result.published and result.tenant_id == env["ta"]


def test_webhook_secret_and_duplicate_updates(env):
    bot, _, _ = bot_parts(env)
    with env["r"].db.system() as db:
        secret = db.scalar(select(m.BotSecret).where(m.BotSecret.bot_id == bot.id))
        plain = env["r"].vault.decrypt(secret.webhook_ciphertext, f"{bot.tenant_id}:{bot.id}:webhook")
    url = f"/telegram/webhook/{bot.public_id}"
    update = {
        "update_id": 555,
        "message": {
            "message_id": 10,
            "chat": {"id": 900005, "type": "private"},
            "from": {"id": 900005, "first_name": "New client"},
            "text": "/start",
        },
    }
    assert env["client"].post(url, json=update).status_code == 403
    headers = {"X-Telegram-Bot-Api-Secret-Token": plain}
    assert env["client"].post(url, json=update, headers=headers).status_code == 200
    assert env["client"].post(url, json=update, headers=headers).json()["duplicate"]
    worker = Worker(env["r"])
    for _ in range(10):
        if not worker.run_one():
            break
    with env["r"].db.system() as db:
        assert (
            db.scalar(select(func.count()).select_from(m.Contact).where(m.Contact.telegram_user_id == 900005))
            == 1
        )
        assert db.scalar(select(m.TelegramUpdate).where(m.TelegramUpdate.update_id == 555)).status == "DONE"


def test_bank_checkout_blocked_inside_telegram(env):
    bot, contact, plan = bot_parts(env)
    with env["r"].db.system() as db, pytest.raises(DomainError, match="Stars"):
        env["r"].payments.create(
            db, bot, contact, plan.id, "BANK_TRANSFER", "MXN", m.uid(), context="TELEGRAM"
        )


def test_stars_payment_idempotency_and_payload_binding(env):
    item = payment(env)
    bot, contact, _ = bot_parts(env)
    with env["r"].db.system() as db:
        with pytest.raises(DomainError):
            env["r"].payments.confirm_stars(db, bot, 123, success_event(item))
    with env["r"].db.system() as db:
        first = env["r"].payments.confirm_stars(db, bot, contact.telegram_user_id, success_event(item))
        expiry = first.expires_at
        second = env["r"].payments.confirm_stars(db, bot, contact.telegram_user_id, success_event(item))
        assert first.id == second.id and second.expires_at == expiry
        assert db.scalar(select(func.count()).select_from(m.PaymentCharge)) == 1


def test_precheckout_amount_user_and_status(env):
    item = payment(env)
    bot, contact, _ = bot_parts(env)
    query = {
        "invoice_payload": item.invoice_payload,
        "currency": "XTR",
        "total_amount": 500,
        "from": {"id": contact.telegram_user_id},
    }
    with env["r"].db.system() as db:
        assert env["r"].payments.precheckout(db, bot, query)
        assert not env["r"].payments.precheckout(db, bot, {**query, "total_amount": 499})
        assert not env["r"].payments.precheckout(db, bot, {**query, "from": {"id": 123}})


def test_recurring_renewal_uses_authoritative_period_end(env):
    item = payment(env, recurring=True)
    bot, contact, _ = bot_parts(env)
    end = m.now() + 2592000
    with env["r"].db.system() as db:
        first = env["r"].payments.confirm_stars(
            db, bot, contact.telegram_user_id, success_event(item, recurring=True, end=end)
        )
        second = env["r"].payments.confirm_stars(
            db, bot, contact.telegram_user_id, success_event(item, "charge-2", True, end + 2592000)
        )
        assert first.id == second.id and second.expires_at == end + 2592000
        # Reordered old events never add another period.
        env["r"].payments.confirm_stars(
            db, bot, contact.telegram_user_id, success_event(item, "late-charge", True, end)
        )
        assert second.expires_at == end + 2592000


def test_receipt_hash_review_and_approval(env):
    item = payment(env, "BANK_TRANSFER")
    bot, _, _ = bot_parts(env)
    data = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(data, format="PNG")
    with env["r"].db.system() as db:
        pay = db.get(m.Payment, item.id)
        first = env["r"].receipts.submit(db, bot, pay, data.getvalue())
        db.flush()
        second = env["r"].receipts.submit(db, bot, pay, data.getvalue())
        assert not first.duplicate and second.duplicate
        assert env["r"].receipts.read(first).startswith(b"\xff\xd8")
        env["r"].receipts.review(db, bot, first, env["ua"], "APPROVE")
        assert pay.status == "APPROVED"
        env["r"].receipts.review(db, bot, first, env["ua"], "APPROVE")
        assert db.scalar(select(func.count()).select_from(m.Subscription)) == 1


def test_invalid_upload_rejected(env):
    item = payment(env, "BANK_TRANSFER")
    bot, _, _ = bot_parts(env)
    with env["r"].db.system() as db, pytest.raises(DomainError):
        env["r"].receipts.submit(db, bot, db.get(m.Payment, item.id), b"<script>evil</script>")


def test_channel_permissions_and_personal_join_links(env):
    bot, contact, plan = bot_parts(env)
    item = payment(env)
    with env["r"].db.system() as db:
        change = {"from": {"id": 101}, "chat": {"id": -100123, "type": "channel", "title": "Club"}}
        channel = env["r"].channels.connect_from_update(db, bot, change)
        db.get(m.Plan, plan.id).channel_id = channel.id
        sub = env["r"].payments.confirm_stars(db, bot, contact.telegram_user_id, success_event(item))
        env["fake"].permissions = False
        assert "can_invite_users" in env["r"].channels.verify(db, bot, channel)["missing"]
        env["fake"].permissions = True
        env["r"].channels.grant(db, bot, sub)
        db.flush()
        invite = db.scalar(select(m.ChannelInvite))
        request = {
            "chat": {"id": -100123},
            "from": {"id": 99999},
            "invite_link": {"invite_link": invite.invite_link},
        }
        env["r"].channels.join_request(db, bot, request)
        assert env["fake"].calls[-1][1] == "declineChatJoinRequest"
        request["from"]["id"] = contact.telegram_user_id
        env["r"].channels.join_request(db, bot, request)
        assert invite.used_at and invite.revoked_at
        sub.expires_at = m.now() - 1
        env["r"].payments.expire_due(db)
        env["r"].channels.revoke(db, bot, sub)
        assert sub.status == "EXPIRED"
        assert any(method == "banChatMember" for _, method, _ in env["fake"].calls)


def test_native_channel_is_separate(env):
    bot, _, _ = bot_parts(env)
    with env["r"].db.system() as db:
        channel = env["r"].channels.connect_from_update(
            db, bot, {"from": {"id": 101}, "chat": {"id": -100124, "type": "channel", "title": "Native"}}
        )
        result = env["r"].channels.native_subscription(db, bot, channel, 500)
        assert result["mode"] == "TELEGRAM_NATIVE"
        assert db.scalar(select(func.count()).select_from(m.Subscription)) == 0


def test_inbox_uses_child_bot_and_ambiguous_send_not_retried(env):
    bot, contact, _ = bot_parts(env)
    with env["r"].db.system() as db:
        conv = conversation(db, bot, contact)
        message = reply(db, bot, conv, env["ua"], "Hello", "test-message-key")
        message_id = message.id
    env["fake"].fail = "sendMessage"
    worker = Worker(env["r"])
    assert worker.run_one()
    assert not worker.run_one()
    with env["r"].db.system() as db:
        assert db.get(m.Message, message_id).status == "DELIVERY_UNKNOWN"
    assert env["fake"].calls[-1][0] == bot.telegram_bot_id


def test_campaign_is_scoped_and_respects_optout(env):
    bot, contact, _ = bot_parts(env)
    with env["r"].db.system() as db:
        optout = upsert_contact(db, bot, {"id": 999999, "first_name": "Optout"})
        optout.opted_out = True
        campaign = m.Campaign(
            id=m.uid(),
            tenant_id=bot.tenant_id,
            bot_id=bot.id,
            name="Welcome",
            text="Hi {{first_name}}",
            segment={},
        )
        db.add(campaign)
        db.flush()
        env["r"].campaigns.start(db, campaign)
    worker = Worker(env["r"])
    for _ in range(10):
        if not worker.run_one():
            break
    with env["r"].db.system() as db:
        recipients = list(db.scalars(select(m.CampaignRecipient)))
        assert (
            len(recipients) == 1 and recipients[0].contact_id == contact.id and recipients[0].status == "SENT"
        )


def test_automation_execution_is_idempotent(env):
    bot, contact, _ = bot_parts(env)
    with env["r"].db.system() as db:
        rule = m.AutomationRule(
            tenant_id=bot.tenant_id,
            bot_id=bot.id,
            name="Interested",
            trigger="START",
            action="CHANGE_CRM_STAGE",
            config={"stage": "INTERESTED"},
        )
        db.add(rule)
        db.flush()
        event = emit(db, bot.tenant_id, "USER_STARTED", "start-event", bot.id, contact.id)
        env["r"].automations.consume(db, event)
        env["r"].automations.consume(db, event)
        assert db.scalar(select(func.count()).select_from(m.AutomationExecution)) == 1
    worker = Worker(env["r"])
    for _ in range(10):
        if not worker.run_one():
            break
    with env["r"].db.system() as db:
        assert db.get(m.Contact, contact.id).stage == "INTERESTED"


def test_queue_fairness_between_tenants(env):
    with env["r"].db.system() as db:
        for index in range(10):
            enqueue(db, "EVENT", env["ta"], {}, f"a-{index}")
        enqueue(db, "EVENT", env["tb"], {}, "b-1")
    worker = Worker(env["r"])
    jobs = [worker.claim(), worker.claim()]
    with env["r"].db.system() as db:
        assert {db.get(m.Job, job).tenant_id for job in jobs} == {env["ta"], env["tb"]}


def test_trial_expiration_suspends_without_destroying_data(env):
    with env["r"].db.system() as db:
        sub = db.scalar(select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == env["ta"]))
        sub.current_period_end = m.now() - 1
        suspend_due(db)
        assert db.get(m.Tenant, env["ta"]).status == "SUSPENDED"
    assert (
        env["client"].post(f"/api/t/{env['ta']}/bots/{env['ba']}/repair", headers=env["a"]).status_code == 403
    )
    assert env["client"].get(f"/api/t/{env['ta']}/export/contacts", headers=env["a"]).status_code == 200


def test_saas_billing_is_separate_from_customer_subscription(env):
    with env["r"].db.system() as db:
        sub = db.scalar(select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == env["ta"]))
        plan = db.get(m.SaaSPlan, sub.plan_id)
        plan.prices = {"XTR": 1000}
        invoice = env["r"].billing.checkout(db, env["ta"], db.get(m.PlatformUser, env["ua"]), plan.id)
        event = {
            "invoice_payload": invoice.invoice_payload,
            "currency": "XTR",
            "total_amount": 1000,
            "telegram_payment_charge_id": "saas-1",
            "is_recurring": True,
            "subscription_expiration_date": m.now() + 2592000,
        }
        env["r"].billing.confirm(db, 101, event)
        env["r"].billing.confirm(db, 101, event)
        assert sub.status == "ACTIVE"
        assert db.scalar(select(func.count()).select_from(m.Subscription)) == 0
        assert db.scalar(select(func.count()).select_from(m.SaaSCharge)) == 1


def test_money_no_float_inputs(env):
    body = {
        "bot_id": env["ba"],
        "name": "Bad money",
        "prices": [{"provider": "TELEGRAM_STARS", "currency": "XTR", "amount_minor": 12.50}],
    }
    assert env["client"].post(f"/api/t/{env['ta']}/plans", headers=env["a"], json=body).status_code == 422
