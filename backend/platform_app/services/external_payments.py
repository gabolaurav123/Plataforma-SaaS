"""Server-created checkouts and authenticated provider events; no browser success claims."""

import hashlib
import hmac
import json
import re
import time
import threading
from decimal import Decimal
import httpx
from sqlalchemy import select, func
from .. import models as m
from ..errors import DomainError, RetryLater
from . import payment_methods as methods
from .common import enqueue, audit, emit


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{4,200}", value):
        raise DomainError("INVALID_PROVIDER_REFERENCE", "Referencia de pago no válida.")
    return value


def stripe_signature(body, header, secret, timestamp=None):
    parts = [part.split("=", 1) for part in header.split(",") if "=" in part]
    dates = [value for key, value in parts if key.strip() == "t"]
    signatures = [value for key, value in parts if key.strip() == "v1"]
    if len(dates) != 1 or not dates[0].isdigit() or abs((timestamp or time.time()) - int(dates[0])) > 300:
        raise DomainError("INVALID_SIGNATURE", "Firma de webhook no válida.", 401)
    expected = hmac.new(secret.encode(), dates[0].encode() + b"." + body, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, value) for value in signatures):
        raise DomainError("INVALID_SIGNATURE", "Firma de webhook no válida.", 401)


class HostedProvider:
    def __init__(self, runtime, provider):
        self.r, self.provider = runtime, provider
        self.http = None
        self.http_lock = threading.Lock()

    def request(self, verb, url, **kwargs):
        try:
            with self.http_lock:
                if self.http is None:
                    self.http = httpx.Client(
                        timeout=12,
                        follow_redirects=False,
                        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
                    )
            response = self.http.request(verb, url, **kwargs)
            if response.status_code == 429:
                raise RetryLater(30, "PROVIDER_RATE_LIMITED")
            if response.status_code >= 500:
                raise DomainError(
                    "PROVIDER_UNAVAILABLE",
                    "El proveedor de pago no está disponible. Reintentaremos la operación.",
                    502,
                )
            if response.status_code >= 400:
                raise DomainError(
                    "PROVIDER_REJECTED",
                    "El proveedor rechazó la operación. Revisa la configuración y el estado del pago.",
                    409,
                )
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise DomainError(
                "PROVIDER_UNAVAILABLE", "No pudimos contactar con el proveedor de pago.", 502
            ) from None

    def config(self, db, bot):
        row = methods.get(db, bot, self.provider)
        if not row:
            raise DomainError("PAYMENT_METHOD_DISABLED", "Método de pago no configurado.", 409)
        return row, methods.secrets(self.r, row)

    def paypal_headers(self, row, private):
        base = (
            "https://api-m.paypal.com"
            if row.public_config.get("environment") == "live"
            else "https://api-m.sandbox.paypal.com"
        )
        token = self.request(
            "POST",
            base + "/v1/oauth2/token",
            auth=(row.public_config["client_id"], private["client_secret"]),
            data={"grant_type": "client_credentials"},
        )
        return base, {"Authorization": "Bearer " + token["access_token"], "Content-Type": "application/json"}

    def create_payment(self, db, bot, payment):
        if payment.checkout_url:
            return {"url": payment.checkout_url, "status": payment.status}
        row, private = self.config(db, bot)
        if not self.r.settings.payment_webhooks_enabled or not row.enabled:
            raise DomainError(
                "PAYMENT_METHOD_DISABLED", "Este método aún no puede recibir confirmaciones de pago.", 409
            )
        plan = db.get(m.Plan, payment.plan_id)
        back = "https://t.me/" + bot.username
        if self.provider == "STRIPE":
            result = self.request(
                "POST",
                "https://api.stripe.com/v1/checkout/sessions",
                auth=(private["secret_key"], ""),
                headers={"Idempotency-Key": "checkout:" + payment.id},
                data={
                    "mode": "payment",
                    "success_url": back,
                    "cancel_url": back,
                    "client_reference_id": payment.id,
                    "metadata[payment_id]": payment.id,
                    "payment_intent_data[metadata][payment_id]": payment.id,
                    "line_items[0][price_data][currency]": payment.currency.lower(),
                    "line_items[0][price_data][unit_amount]": str(payment.amount_minor),
                    "line_items[0][price_data][product_data][name]": plan.name,
                    "line_items[0][quantity]": "1",
                },
            )
            url = result["url"]
            if not url.startswith("https://checkout.stripe.com/"):
                raise DomainError("PROVIDER_RESPONSE_INVALID", "Enlace de pago no válido.", 502)
        else:
            from .business import money

            base, headers = self.paypal_headers(row, private)
            result = self.request(
                "POST",
                base + "/v2/checkout/orders",
                headers={**headers, "PayPal-Request-Id": payment.id},
                json={
                    "intent": "CAPTURE",
                    "purchase_units": [
                        {
                            "reference_id": payment.id,
                            "custom_id": payment.id,
                            "description": plan.name[:127],
                            "amount": {
                                "currency_code": payment.currency,
                                "value": money(payment.amount_minor, payment.currency).rsplit(" ", 1)[0],
                            },
                        }
                    ],
                    "payment_source": {
                        "paypal": {
                            "experience_context": {
                                "return_url": back,
                                "cancel_url": back,
                                "user_action": "PAY_NOW",
                            }
                        }
                    },
                },
            )
            url = next(
                (x["href"] for x in result.get("links", []) if x.get("rel") in {"approve", "payer-action"}),
                "",
            )
            if not re.match(r"^https://(?:www\.)?(?:sandbox\.)?paypal\.com/", url):
                raise DomainError("PROVIDER_RESPONSE_INVALID", "Enlace de pago no válido.", 502)
        payment.provider_reference, payment.checkout_url = identifier(result["id"]), url
        return {"url": url, "status": payment.status}

    def verify(self, row, body, headers):
        private = methods.secrets(self.r, row)
        if self.provider == "STRIPE":
            stripe_signature(body, headers.get("stripe-signature", ""), private["webhook_secret"])
            return
        base, auth = self.paypal_headers(row, private)
        required = [
            "paypal-auth-algo",
            "paypal-cert-url",
            "paypal-transmission-id",
            "paypal-transmission-sig",
            "paypal-transmission-time",
        ]
        if any(not headers.get(key) for key in required):
            raise DomainError("INVALID_SIGNATURE", "Firma de webhook no válida.", 401)
        result = self.request(
            "POST",
            base + "/v1/notifications/verify-webhook-signature",
            headers=auth,
            json={
                "auth_algo": headers["paypal-auth-algo"],
                "cert_url": headers["paypal-cert-url"],
                "transmission_id": headers["paypal-transmission-id"],
                "transmission_sig": headers["paypal-transmission-sig"],
                "transmission_time": headers["paypal-transmission-time"],
                "webhook_id": row.public_config["webhook_id"],
                "webhook_event": json.loads(body),
            },
        )
        if result.get("verification_status") != "SUCCESS":
            raise DomainError("INVALID_SIGNATURE", "Firma de webhook no válida.", 401)

    def handle_event(self, db, bot, event):
        row, private = self.config(db, bot)
        kind = event.get("type") if self.provider == "STRIPE" else event.get("event_type")
        if self.provider == "STRIPE":
            if kind == "charge.refunded":
                obj = self.request(
                    "GET",
                    "https://api.stripe.com/v1/charges/" + identifier(event["data"]["object"]["id"]),
                    auth=(private["secret_key"], ""),
                )
                charge = db.scalar(
                    select(m.PaymentCharge).where(
                        m.PaymentCharge.bot_id == bot.id,
                        m.PaymentCharge.tenant_id == bot.tenant_id,
                        m.PaymentCharge.provider == "STRIPE",
                        m.PaymentCharge.charge_id == obj.get("payment_intent"),
                    )
                )
                if not charge:
                    raise RetryLater(10, "PAYMENT_NOT_COMMITTED")
                db.scalar(select(m.Payment).where(m.Payment.id == charge.payment_id).with_for_update())
                db.refresh(charge, with_for_update=True)
                refunded = (
                    db.scalar(
                        select(func.sum(m.PaymentRefund.amount_minor)).where(
                            m.PaymentRefund.charge_id == charge.id
                        )
                    )
                    or 0
                )
                amount = obj.get("amount_refunded", 0) - refunded
                if amount > 0:
                    from .refunds import record

                    record(
                        db,
                        self.r,
                        bot,
                        charge,
                        amount,
                        f"stripe:{obj['id']}:{obj['amount_refunded']}",
                        "stripe-webhook",
                    )
                return
            if kind not in {
                "checkout.session.completed",
                "checkout.session.async_payment_succeeded",
                "checkout.session.async_payment_failed",
                "checkout.session.expired",
            }:
                return
            obj = event["data"]["object"]
            ref = identifier(obj["id"])
            payment = db.scalar(
                select(m.Payment)
                .where(
                    m.Payment.bot_id == bot.id,
                    m.Payment.tenant_id == bot.tenant_id,
                    m.Payment.provider == self.provider,
                    m.Payment.provider_reference == ref,
                )
                .with_for_update()
            )
            if not payment:
                raise RetryLater(10, "CHECKOUT_NOT_COMMITTED")
            result = self.request(
                "GET", "https://api.stripe.com/v1/checkout/sessions/" + ref, auth=(private["secret_key"], "")
            )
            if (
                result.get("client_reference_id") != payment.id
                or result.get("amount_total") != payment.amount_minor
                or result.get("currency", "").upper() != payment.currency
            ):
                raise DomainError("PAYMENT_MISMATCH", "El importe o la referencia no coincide.", 409)
            if result.get("payment_status") == "paid":
                self.r.payments.confirm(
                    db, bot, payment, identifier(result["payment_intent"]), "stripe-webhook"
                )
            elif kind in {"checkout.session.async_payment_failed", "checkout.session.expired"}:
                self.failed(db, bot, payment, event["id"])
            return
        if kind == "PAYMENT.CAPTURE.REFUNDED":
            base, headers = self.paypal_headers(row, private)
            result = self.request(
                "GET", base + "/v2/payments/refunds/" + identifier(event["resource"]["id"]), headers=headers
            )
            if result.get("status") != "COMPLETED":
                return
            capture_url = next(
                (link.get("href", "") for link in result.get("links", []) if link.get("rel") == "up"), ""
            )
            capture_id = identifier(capture_url.rstrip("/").rsplit("/", 1)[-1])
            charge = db.scalar(
                select(m.PaymentCharge).where(
                    m.PaymentCharge.tenant_id == bot.tenant_id,
                    m.PaymentCharge.bot_id == bot.id,
                    m.PaymentCharge.provider == "PAYPAL",
                    m.PaymentCharge.charge_id == capture_id,
                )
            )
            if not charge:
                raise RetryLater(10, "PAYMENT_NOT_COMMITTED")
            from .refunds import record
            from .business import amount_minor

            if result["amount"]["currency_code"] != charge.currency:
                raise DomainError("PAYMENT_MISMATCH", "Moneda de devolución incorrecta.", 409)
            record(
                db,
                self.r,
                bot,
                charge,
                amount_minor(result["amount"]["value"], charge.currency),
                "paypal:" + result["id"],
                "paypal-webhook",
            )
            return
        if kind not in {
            "CHECKOUT.ORDER.APPROVED",
            "PAYMENT.CAPTURE.COMPLETED",
            "PAYMENT.CAPTURE.DENIED",
            "PAYMENT.CAPTURE.PENDING",
        }:
            return
        resource = event["resource"]
        ref = identifier(
            resource["id"]
            if kind == "CHECKOUT.ORDER.APPROVED"
            else resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        )
        payment = db.scalar(
            select(m.Payment)
            .where(
                m.Payment.bot_id == bot.id,
                m.Payment.tenant_id == bot.tenant_id,
                m.Payment.provider == self.provider,
                m.Payment.provider_reference == ref,
            )
            .with_for_update()
        )
        if not payment:
            raise RetryLater(10, "CHECKOUT_NOT_COMMITTED")
        base, headers = self.paypal_headers(row, private)
        order = self.request("GET", base + "/v2/checkout/orders/" + ref, headers=headers)
        if order.get("status") == "APPROVED":
            order = self.request(
                "POST",
                base + "/v2/checkout/orders/" + ref + "/capture",
                headers={**headers, "PayPal-Request-Id": "capture-" + payment.id},
                json={},
            )
        units = order.get("purchase_units", [])
        if len(units) != 1 or units[0].get("custom_id") != payment.id:
            raise DomainError("PAYMENT_MISMATCH", "Referencia de pago no válida.", 409)
        from .business import money

        for capture in units[0].get("payments", {}).get("captures", []):
            amount = capture.get("amount", {})
            if amount.get("currency_code") != payment.currency or Decimal(
                amount.get("value", "-1")
            ) != Decimal(money(payment.amount_minor, payment.currency).rsplit(" ", 1)[0]):
                raise DomainError("PAYMENT_MISMATCH", "El importe del pago no coincide.", 409)
            if capture.get("status") == "COMPLETED":
                self.r.payments.confirm(db, bot, payment, identifier(capture["id"]), "paypal-webhook")
        if kind == "PAYMENT.CAPTURE.DENIED" and payment.status != "APPROVED":
            self.failed(db, bot, payment, event["id"])

    def failed(self, db, bot, payment, external_id):
        if payment.status == "APPROVED":
            return
        payment.status = "FAILED"
        emit(
            db,
            bot.tenant_id,
            "PAYMENT_FAILED",
            f"provider-failed:{bot.id}:{self.provider}:{external_id}",
            bot.id,
            payment.contact_id,
            {"payment_id": payment.id},
        )
        from .notifications import notify, customer

        notify(
            db,
            self.r,
            bot,
            "payment_failed",
            {"key": "failed_payment_notice", "values": {"reference": payment.id[:8]}},
            f"payment-failed:{bot.id}:{self.provider}:{external_id}",
            "payments",
        )
        customer(
            db, bot, db.get(m.Contact, payment.contact_id), "ERROR", "payment-failed-customer:" + external_id
        )

    def refund(self, db, bot, payment, charge, amount=None):
        row, private = self.config(db, bot)
        if charge.bot_id != bot.id or charge.payment_id != payment.id or charge.provider != self.provider:
            raise DomainError("NOT_FOUND", "Pago no disponible.", 404)
        if self.provider == "STRIPE":
            return self.request(
                "POST",
                "https://api.stripe.com/v1/refunds",
                auth=(private["secret_key"], ""),
                headers={"Idempotency-Key": "refund:" + charge.id},
                data={
                    "payment_intent": identifier(charge.charge_id),
                    **({"amount": amount} if amount is not None else {}),
                },
            )
        base, headers = self.paypal_headers(row, private)
        from .business import money

        return self.request(
            "POST",
            base + "/v2/payments/captures/" + identifier(charge.charge_id) + "/refund",
            headers={**headers, "PayPal-Request-Id": "refund-" + charge.id},
            json={
                "amount": {
                    "currency_code": charge.currency,
                    "value": money(amount, charge.currency).rsplit(" ", 1)[0],
                }
            }
            if amount is not None
            else {},
        )

    def cancel_subscription(self, *args):
        return {"automatic_renewal": False}

    def get_status(self, db, payment):
        return payment.status

    def close(self):
        if self.http:
            self.http.close()


def receive(runtime, webhook_key, body, headers):
    event = json.loads(body)
    with runtime.db.system() as db:
        row = db.scalar(select(m.BotPaymentMethod).where(m.BotPaymentMethod.webhook_key == webhook_key))
        if not row or row.provider not in {"STRIPE", "PAYPAL"}:
            raise DomainError("NOT_FOUND", "Webhook no disponible.", 404)
        runtime.payments.providers[row.provider].verify(row, body, headers)
        eid = identifier(event.get("id"))
        # Serialize verified events for one merchant, including duplicate deliveries.
        db.scalar(select(m.ManagedBot.id).where(m.ManagedBot.id == row.bot_id).with_for_update())
        previous = db.scalar(
            select(m.ProviderEvent).where(
                m.ProviderEvent.provider == row.provider,
                m.ProviderEvent.account_key == row.bot_id,
                m.ProviderEvent.external_id == eid,
            )
        )
        if previous:
            return
        stored = m.ProviderEvent(
            id=m.uid(),
            tenant_id=row.tenant_id,
            provider=row.provider,
            account_key=row.bot_id,
            external_id=eid,
            payload_hash=hashlib.sha256(body).hexdigest(),
        )
        stored.payload_ciphertext = runtime.vault.encrypt(
            json.dumps(event), f"{row.tenant_id}:{stored.id}:provider-event"
        )
        db.add(stored)
        db.flush()
        enqueue(
            db,
            "PROVIDER_EVENT",
            row.tenant_id,
            {"event_id": stored.id},
            "provider-event:" + stored.id,
            row.bot_id,
        )
        audit(
            db,
            row.tenant_id,
            "provider",
            "WEBHOOK_VERIFIED",
            stored.id,
            {"bot_id": row.bot_id, "provider": row.provider},
        )
