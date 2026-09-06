import pytest
from sqlalchemy import select, func
from platform_app import models as m
from platform_app.errors import DomainError, RetryLater
from platform_app.services.crm import conversation, reply
from conftest import bot_parts
from test_workflows import payment, success_event


def test_reply_idempotency_and_conflicting_body(env):
    bot, contact, _ = bot_parts(env)
    with env["r"].db.system() as db:
        conv = conversation(db, bot, contact)
        first = reply(db, bot, conv, env["ua"], "hello", "same-key-123")
        assert reply(db, bot, conv, env["ua"], "hello", "same-key-123").id == first.id
        with pytest.raises(DomainError):
            reply(db, bot, conv, env["ua"], "different", "same-key-123")
        assert db.scalar(select(func.count()).select_from(m.Message)) == 1


def test_refund_revokes_only_its_entitlement_and_is_idempotent(env):
    item = payment(env)
    bot, contact, _ = bot_parts(env)
    with env["r"].db.system() as db:
        sub = env["r"].payments.confirm_stars(db, bot, contact.telegram_user_id, success_event(item))
        env["r"].payments.refunded_event(db, bot, {"telegram_payment_charge_id": "charge-1"})
        env["r"].payments.refunded_event(db, bot, {"telegram_payment_charge_id": "charge-1"})
        assert sub.status == "EXPIRED" and db.get(m.Payment, item.id).status == "REFUNDED"


def test_webhook_secret_cannot_be_reused_for_another_bot(env):
    a, b = bot_parts(env)[0], bot_parts(env, "b")[0]
    with env["r"].db.system() as db:
        secret = db.scalar(select(m.BotSecret).where(m.BotSecret.bot_id == a.id))
        plain = env["r"].vault.decrypt(secret.webhook_ciphertext, f"{a.tenant_id}:{a.id}:webhook")
    assert (
        env["client"]
        .post(
            f"/telegram/webhook/{b.public_id}",
            headers={"X-Telegram-Bot-Api-Secret-Token": plain},
            json={"update_id": 123},
        )
        .status_code
        == 403
    )


def test_local_rate_limit_and_retry_after(env):
    env["r"].limiter.check({"limited": 1})
    with pytest.raises(RetryLater) as error:
        env["r"].limiter.check({"limited": 1})
    assert error.value.seconds == 1


def test_disabled_ai_cannot_be_enabled_without_implementation(env):
    response = env["client"].put(
        f"/api/owner/tenants/{env['ta']}/features/ai", headers=env["a"], json={"enabled": True}
    )
    assert response.status_code == 409


def test_payment_receipt_inbox_cross_tenant_ids_are_inaccessible(env):
    bot, contact, _ = bot_parts(env, "b")
    with env["r"].db.system() as db:
        conv = conversation(db, bot, contact)
        conv_id = conv.id
    response = env["client"].post(
        f"/api/t/{env['ta']}/conversations/{conv_id}/messages",
        headers=env["a"],
        json={"text": "forbidden", "idempotency_key": "malicious-key"},
    )
    assert response.status_code == 404
    assert (
        env["client"]
        .patch(f"/api/t/{env['ta']}/contacts/{contact.id}", headers=env["a"], json={"stage": "VIP"})
        .status_code
        == 404
    )
