import hashlib
import hmac
import json
import httpx
import pytest
from sqlalchemy import select, func
from platform_app import models as m
from platform_app.errors import DomainError
from platform_app.services import payment_methods
from platform_app.services.external_payments import stripe_signature, receive
from platform_app.services.background import process
from conftest import bot_parts


def prepare(env, provider):
    r, (bot, person, plan) = env["r"], bot_parts(env)
    r.settings.payment_webhooks_enabled = True
    with r.db.system() as db:
        db.get(m.Plan, plan.id).product_kind = "PHYSICAL"
        db.add(
            m.PlanPrice(
                tenant_id=bot.tenant_id, plan_id=plan.id, provider=provider, currency="USD", amount_minor=1299
            )
        )
        fields = (
            {"secret_key": "sk_test_" + "s" * 24, "webhook_secret": "whsec_" + "w" * 24}
            if provider == "STRIPE"
            else {
                "client_id": "merchant-id",
                "client_secret": "merchant-secret",
                "webhook_id": "WH-123456",
                "environment": "sandbox",
            }
        )
        for key, value in fields.items():
            row = payment_methods.update(db, r, bot, provider, env["ua"], key, value)
        payment_methods.enable(db, r, bot, row, env["ua"])
        payment = r.payments.create(
            db, bot, person, plan.id, provider, "USD", "external-test", defer_checkout=True
        )
        return bot, payment.id, row.webhook_key


def signature(body):
    stamp = str(m.now())
    value = hmac.new(("whsec_" + "w" * 24).encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"stripe-signature": f"t={stamp},v1={value}"}


def test_stripe_signature_rejects_tampering_expiration_and_multiple_timestamps():
    body, secret, timestamp = b'{"id":"evt_123"}', "test_secret", 100000
    digest = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    stripe_signature(body, f"t={timestamp},v1=old,v1={digest}", secret, timestamp)
    for data, header, current in [
        (body + b" ", f"t={timestamp},v1={digest}", timestamp),
        (body, f"t={timestamp},v1={digest}", timestamp + 301),
        (body, f"t={timestamp},t={timestamp},v1={digest}", timestamp),
    ]:
        with pytest.raises(DomainError):
            stripe_signature(data, header, secret, current)


def test_stripe_checkout_verified_paid_event_and_refund_are_idempotent(env):
    bot, pid, key = prepare(env, "STRIPE")
    r = env["r"]
    provider = r.payments.providers["STRIPE"]
    calls = []

    def request(req):
        calls.append(req)
        if req.method == "POST":
            assert (
                b"unit_amount%5D=1299" in req.content and req.headers["Idempotency-Key"] == "checkout:" + pid
            )
            return httpx.Response(
                200, json={"id": "cs_test_123", "url": "https://checkout.stripe.com/c/pay/test"}
            )
        if "/charges/" in req.url.path:
            return httpx.Response(
                200, json={"id": "ch_test_123", "payment_intent": "pi_test_123", "amount_refunded": 299}
            )
        return httpx.Response(
            200,
            json={
                "id": "cs_test_123",
                "client_reference_id": pid,
                "currency": "usd",
                "amount_total": 1299,
                "payment_status": "paid",
                "payment_intent": "pi_test_123",
            },
        )

    provider.http = httpx.Client(transport=httpx.MockTransport(request))
    with r.db.system() as db:
        payment = db.get(m.Payment, pid)
        provider.create_payment(db, bot, payment)
        provider.create_payment(db, bot, payment)
        assert len(calls) == 1
    body = json.dumps(
        {
            "id": "evt_paid_123",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_123"}},
        }
    ).encode()
    receive(r, key, body, signature(body))
    receive(r, key, body, signature(body))
    with r.db.system() as db:
        assert db.scalar(select(func.count()).select_from(m.ProviderEvent)) == 1
        job = db.scalar(select(m.Job).where(m.Job.kind == "PROVIDER_EVENT"))
        process(r, db, job, bot)
        process(r, db, job, bot)
        assert db.get(m.Payment, pid).status == "APPROVED"
        assert db.scalar(select(func.count()).select_from(m.PaymentCharge)) == 1
        assert db.scalar(select(func.count()).select_from(m.Subscription)) == 1
        assert db.scalar(select(m.ProviderEvent)).payload_ciphertext is None
    event = {"id": "evt_refund_123", "type": "charge.refunded", "data": {"object": {"id": "ch_test_123"}}}
    with r.db.system() as db:
        provider.handle_event(db, bot, event)
        provider.handle_event(db, bot, event)
        assert db.scalar(select(func.sum(m.PaymentRefund.amount_minor))) == 299
        assert db.scalar(select(m.Subscription.status)) == "ACTIVE"
        assert db.get(m.Payment, pid).status == "APPROVED"
    provider.close()


def test_wrong_stripe_amount_cannot_activate_membership(env):
    bot, pid, _ = prepare(env, "STRIPE")
    provider = env["r"].payments.providers["STRIPE"]
    provider.http = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "client_reference_id": pid,
                    "amount_total": 1,
                    "currency": "usd",
                    "payment_status": "paid",
                    "payment_intent": "pi_wrong_123",
                },
            )
        )
    )
    with env["r"].db.system() as db:
        db.get(m.Payment, pid).provider_reference = "cs_test_wrong"
        with pytest.raises(DomainError, match="importe"):
            provider.handle_event(
                db,
                bot,
                {
                    "id": "evt_wrong_123",
                    "type": "checkout.session.completed",
                    "data": {"object": {"id": "cs_test_wrong"}},
                },
            )
        assert db.scalar(select(func.count()).select_from(m.Subscription)) == 0
        assert db.scalar(select(func.count()).select_from(m.PaymentCharge)) == 0
    provider.close()


def test_paypal_verifies_signature_and_captures_only_matching_order(env):
    bot, pid, key = prepare(env, "PAYPAL")
    provider = env["r"].payments.providers["PAYPAL"]
    verified = []

    def request(req):
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "oauth-test"})
        if req.url.path.endswith("verify-webhook-signature"):
            verified.append(json.loads(req.content))
            return httpx.Response(200, json={"verification_status": "SUCCESS"})
        if req.method == "POST" and req.url.path.endswith("/orders"):
            data = json.loads(req.content)
            assert data["purchase_units"][0]["amount"]["value"] == "12.99"
            return httpx.Response(
                200,
                json={
                    "id": "ORDER123",
                    "links": [
                        {
                            "rel": "payer-action",
                            "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER123",
                        }
                    ],
                },
            )
        if req.url.path.endswith("/capture"):
            assert req.headers["PayPal-Request-Id"] == "capture-" + pid
            return httpx.Response(
                200,
                json={
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "custom_id": pid,
                            "payments": {
                                "captures": [
                                    {
                                        "id": "CAPTURE123",
                                        "status": "COMPLETED",
                                        "amount": {"currency_code": "USD", "value": "12.99"},
                                    }
                                ]
                            },
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"status": "APPROVED", "purchase_units": [{"custom_id": pid}]})

    provider.http = httpx.Client(transport=httpx.MockTransport(request))
    with env["r"].db.system() as db:
        provider.create_payment(db, bot, db.get(m.Payment, pid))
    event = {"id": "WH_EVENT123", "event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "ORDER123"}}
    body = json.dumps(event).encode()
    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.paypal.com/cert",
        "paypal-transmission-id": "transmission",
        "paypal-transmission-sig": "signed",
        "paypal-transmission-time": "2026-09-06T12:00:00Z",
    }
    receive(env["r"], key, body, headers)
    assert verified[0]["webhook_id"] == "WH-123456" and verified[0]["webhook_event"] == event
    with env["r"].db.system() as db:
        job = db.scalar(select(m.Job).where(m.Job.kind == "PROVIDER_EVENT"))
        process(env["r"], db, job, bot)
        process(env["r"], db, job, bot)
        assert db.scalar(select(func.count()).select_from(m.PaymentCharge)) == 1
        assert db.get(m.Payment, pid).status == "APPROVED"
    provider.close()
