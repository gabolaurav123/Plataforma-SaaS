from typing import Protocol
from sqlalchemy import select, func
from ..models import (
    Payment,
    PaymentCharge,
    ManagedBot,
    Plan,
    PlanPrice,
    Contact,
    ProviderConfig,
    BotPaymentMethod,
    Subscription,
    Coupon,
    CouponRedemption,
    Referral,
    now,
    uid,
)
from ..errors import DomainError
from ..db import get_scoped
from .common import audit, emit, enqueue
from .tenants import entitlement, feature


class PaymentProvider(Protocol):
    def create_payment(self, session, bot, payment): ...
    def get_status(self, session, payment): ...
    def handle_webhook(self, session, bot, user_id, event): ...
    def refund(self, session, bot, payment, charge): ...
    def cancel_subscription(self, session, bot, contact, subscription, canceled): ...
    def reconcile(self, session, bot, offset=0): ...


class TelegramStarsProvider:
    def __init__(self, runtime):
        self.r = runtime

    def create_payment(self, session, bot, payment):
        plan = session.get(Plan, payment.plan_id)
        parameters = {
            "title": plan.name[:32],
            "description": (plan.description or plan.name)[:255],
            "payload": payment.invoice_payload,
            "provider_token": "",
            "currency": "XTR",
            "prices": [{"label": plan.name, "amount": payment.amount_minor}],
        }
        if payment.recurring:
            if payment.duration_days != 30 or payment.amount_minor > 10000:
                raise DomainError(
                    "STARS_PERIOD", "Las suscripciones recurrentes usan 30 días y hasta 10.000 Stars."
                )
            parameters["subscription_period"] = 2592000
        payment.checkout_url = self.r.clients.child(session, bot).call("createInvoiceLink", **parameters)
        return {"url": payment.checkout_url, "status": payment.status}

    def get_status(self, session, payment):
        return payment.status

    def handle_webhook(self, session, bot, user_id, event):
        return self.r.payments.confirm_stars(session, bot, user_id, event)

    def refund(self, session, bot, payment, charge):
        contact = session.get(Contact, payment.contact_id)
        return self.r.clients.child(session, bot).call(
            "refundStarPayment", user_id=contact.telegram_user_id, telegram_payment_charge_id=charge.charge_id
        )

    def cancel_subscription(self, session, bot, contact, subscription, canceled=True):
        if not subscription.initial_charge_id:
            raise DomainError("NO_RECURRING_SUBSCRIPTION", "No hay renovación automática que modificar.", 409)
        return self.r.clients.child(session, bot).call(
            "editUserStarSubscription",
            user_id=contact.telegram_user_id,
            telegram_payment_charge_id=subscription.initial_charge_id,
            is_canceled=canceled,
        )

    def reconcile(self, session, bot, offset=0):
        return self.r.clients.child(session, bot).call("getStarTransactions", offset=offset, limit=100)


class BankTransferProvider:
    def create_payment(self, session, bot, payment):
        return {"status": "PENDING", "requires_receipt": True}

    def get_status(self, session, payment):
        return payment.status

    def handle_webhook(self, *args):
        raise DomainError("NO_BANK_WEBHOOK", "Las transferencias requieren revisión de comprobante.")

    def refund(self, *args):
        raise DomainError("MANUAL_REFUND_REQUIRED", "El reembolso bancario se realiza en tu banco.", 409)

    def cancel_subscription(self, *args):
        return {"automatic_renewal": False}

    def reconcile(self, *args):
        return {"mode": "MANUAL_REVIEW"}


class ExternalHostedProvider:
    """Contract only. No processor is silently enabled or given a fake checkout."""

    def create_payment(self, *args):
        raise DomainError(
            "PROVIDER_ADAPTER_REQUIRED", "Conecta un adaptador aprobado para tu actividad.", 409
        )

    get_status = handle_webhook = refund = cancel_subscription = reconcile = create_payment


class PaymentService:
    def __init__(self, runtime):
        self.r = runtime
        from .external_payments import HostedProvider

        self.providers = {
            "TELEGRAM_STARS": TelegramStarsProvider(runtime),
            "BANK_TRANSFER": BankTransferProvider(),
            "EXTERNAL_HOSTED_PROVIDER": ExternalHostedProvider(),
            "STRIPE": HostedProvider(runtime, "STRIPE"),
            "PAYPAL": HostedProvider(runtime, "PAYPAL"),
        }

    def create(
        self,
        session,
        bot,
        contact,
        plan_id,
        provider,
        currency,
        idempotency_key,
        *,
        context="TELEGRAM",
        coupon_code=None,
        defer_checkout=False,
    ):
        entitlement(session, bot.tenant_id)
        if contact.bot_id != bot.id or contact.tenant_id != bot.tenant_id:
            raise DomainError("NOT_FOUND", "Cliente no disponible.", 404)
        plan = get_scoped(session, Plan, plan_id, bot.tenant_id)
        if plan.bot_id != bot.id or not plan.active or plan.archived_at:
            raise DomainError("PLAN_UNAVAILABLE", "Plan no disponible.", 404)
        if plan.product_kind == "DIGITAL" and context == "TELEGRAM" and provider != "TELEGRAM_STARS":
            raise DomainError(
                "STARS_REQUIRED", "Los productos digitales dentro de Telegram se pagan con Stars.", 403
            )
        if not bot.published and context == "TELEGRAM":
            raise DomainError("BOT_NOT_PUBLISHED", "Este bot todavía no está publicado.", 409)
        if provider not in self.providers:
            raise DomainError("INVALID_PROVIDER", "Proveedor no soportado.")
        feature(
            session,
            bot.tenant_id,
            {
                "TELEGRAM_STARS": "stars",
                "BANK_TRANSFER": "bank_payments",
                "EXTERNAL_HOSTED_PROVIDER": "external_payments",
                "STRIPE": "external_payments",
                "PAYPAL": "external_payments",
            }[provider],
        )
        config = session.scalar(
            select(BotPaymentMethod).where(
                BotPaymentMethod.tenant_id == bot.tenant_id,
                BotPaymentMethod.bot_id == bot.id,
                BotPaymentMethod.provider == provider,
            )
        )
        if config is None:
            config = session.scalar(
                select(ProviderConfig).where(
                    ProviderConfig.tenant_id == bot.tenant_id,
                    ProviderConfig.provider == provider,
                    ProviderConfig.enabled.is_(True),
                )
            )
        if not config or not config.enabled:
            raise DomainError("PAYMENT_METHOD_DISABLED", "Método de pago no disponible.", 409)
        previous = session.scalar(
            select(Payment).where(
                Payment.tenant_id == bot.tenant_id, Payment.idempotency_key == idempotency_key
            )
        )
        if previous:
            if (
                previous.contact_id,
                previous.bot_id,
                previous.plan_id,
                previous.provider,
                previous.currency,
            ) != (contact.id, bot.id, plan_id, provider, currency):
                raise DomainError("IDEMPOTENCY_CONFLICT", "Esta operación ya existe con otros datos.", 409)
            return previous
        price = session.scalar(
            select(PlanPrice).where(
                PlanPrice.tenant_id == bot.tenant_id,
                PlanPrice.plan_id == plan.id,
                PlanPrice.provider == provider,
                PlanPrice.currency == currency,
            )
        )
        if not price:
            raise DomainError("PRICE_UNAVAILABLE", "Precio no disponible.")
        amount = price.amount_minor
        coupon = None
        if coupon_code:
            feature(session, bot.tenant_id, "coupons")
            coupon = session.scalar(
                select(Coupon)
                .where(Coupon.tenant_id == bot.tenant_id, Coupon.code == coupon_code.upper())
                .with_for_update()
            )
            if not coupon or not coupon.active or coupon.expires_at <= now():
                raise DomainError("COUPON_INVALID", "Cupón no válido.")
            count = session.scalar(
                select(func.count())
                .select_from(CouponRedemption)
                .where(CouponRedemption.coupon_id == coupon.id)
            )
            used = session.scalar(
                select(CouponRedemption.id).where(
                    CouponRedemption.coupon_id == coupon.id, CouponRedemption.contact_id == contact.id
                )
            )
            if count >= coupon.max_redemptions or used:
                raise DomainError("COUPON_LIMIT", "Este cupón ya no está disponible.")
            if plan.recurring:
                raise DomainError("COUPON_RECURRING", "Los cupones se aplican a pagos únicos.")
            amount = max(1, amount * (100 - coupon.percent_off) // 100)
        payment = Payment(
            id=uid(),
            tenant_id=bot.tenant_id,
            bot_id=bot.id,
            contact_id=contact.id,
            plan_id=plan.id,
            provider=provider,
            currency=currency,
            amount_minor=amount,
            duration_days=plan.duration_days,
            recurring=plan.recurring and provider == "TELEGRAM_STARS",
            idempotency_key=idempotency_key,
            invoice_payload=f"customer:{uid()}",
            channel_snapshot=[],
        )
        from .business import plan_channels

        payment.channel_snapshot = plan_channels(session, plan)
        session.add(payment)
        session.flush()
        if coupon:
            session.add(
                CouponRedemption(
                    tenant_id=bot.tenant_id, coupon_id=coupon.id, contact_id=contact.id, payment_id=payment.id
                )
            )
        if defer_checkout:
            enqueue(
                session,
                "CHECKOUT",
                bot.tenant_id,
                {"payment_id": payment.id},
                "checkout:" + payment.id,
                bot.id,
            )
        else:
            self.providers[provider].create_payment(session, bot, payment)
        contact.stage = "PAYMENT_PENDING"
        emit(session, bot.tenant_id, "PAYMENT_CREATED", f"payment:{payment.id}", bot.id, contact.id)
        return payment

    def precheckout(self, session, bot, query):
        payment = session.scalar(
            select(Payment)
            .where(Payment.bot_id == bot.id, Payment.invoice_payload == query["invoice_payload"])
            .with_for_update()
        )
        if (
            not payment
            or payment.provider != "TELEGRAM_STARS"
            or payment.status not in {"PENDING", "APPROVED"}
        ):
            return False
        if payment.status == "APPROVED" and not payment.recurring:
            return False
        contact = session.get(Contact, payment.contact_id)
        try:
            entitlement(session, bot.tenant_id)
        except DomainError:
            return False
        return bool(
            bot.published
            and contact.telegram_user_id == query["from"]["id"]
            and query["currency"] == "XTR"
            and payment.amount_minor == query["total_amount"]
        )

    def confirm_stars(self, session, bot, user_id, event):
        payment = session.scalar(
            select(Payment)
            .where(Payment.bot_id == bot.id, Payment.invoice_payload == event["invoice_payload"])
            .with_for_update()
        )
        if not payment:
            raise DomainError("PAYMENT_NOT_FOUND", "Pago no identificado.", 404)
        contact = session.get(Contact, payment.contact_id)
        if (
            contact.telegram_user_id != user_id
            or event["currency"] != "XTR"
            or event["total_amount"] != payment.amount_minor
            or payment.provider != "TELEGRAM_STARS"
        ):
            raise DomainError("PAYMENT_MISMATCH", "Los datos del pago no coinciden.", 409)
        recurring = bool(event.get("is_recurring"))
        if recurring != payment.recurring:
            raise DomainError("RECURRENCE_MISMATCH", "La periodicidad del pago no coincide.", 409)
        end = event.get("subscription_expiration_date")
        if recurring and (type(end) is not int or end <= 0):
            raise DomainError("INVALID_PERIOD", "El pago recurrente no incluye un periodo válido.")
        return self.confirm(
            session, bot, payment, event["telegram_payment_charge_id"], "telegram", period_end=end
        )

    def confirm(self, session, bot, payment, charge_id, actor, period_end=None):
        if payment.tenant_id != bot.tenant_id or payment.bot_id != bot.id:
            raise DomainError("NOT_FOUND", "Pago no disponible.", 404)
        session.scalar(select(Payment).where(Payment.id == payment.id).with_for_update())
        previous = session.scalar(
            select(PaymentCharge).where(
                PaymentCharge.bot_id == bot.id,
                PaymentCharge.provider == payment.provider,
                PaymentCharge.charge_id == charge_id,
            )
        )
        if previous:
            if previous.payment_id != payment.id:
                raise DomainError("CHARGE_CONFLICT", "Cargo ya registrado.", 409)
            return session.scalar(select(Subscription).where(Subscription.payment_id == payment.id))
        if payment.status in {"REFUNDED", "REJECTED"} or (
            payment.status == "APPROVED" and not payment.recurring
        ):
            raise DomainError("PAYMENT_FINALIZED", "Este pago ya fue procesado.", 409)
        contact = session.scalar(select(Contact).where(Contact.id == payment.contact_id).with_for_update())
        sub = session.scalar(select(Subscription).where(Subscription.payment_id == payment.id))
        renewal = sub is not None
        if not sub:
            latest = (
                session.scalar(
                    select(func.max(Subscription.expires_at)).where(
                        Subscription.contact_id == contact.id,
                        Subscription.plan_id == payment.plan_id,
                        Subscription.status == "ACTIVE",
                    )
                )
                or now()
            )
            sub = Subscription(
                id=uid(),
                tenant_id=bot.tenant_id,
                bot_id=bot.id,
                contact_id=contact.id,
                plan_id=payment.plan_id,
                payment_id=payment.id,
                starts_at=now(),
                expires_at=period_end or max(latest, now()) + payment.duration_days * 86400,
                auto_renew=payment.recurring,
                initial_charge_id=charge_id if payment.recurring else None,
                channel_snapshot=list(payment.channel_snapshot),
            )
            session.add(sub)
        else:
            sub.expires_at = max(sub.expires_at, period_end or sub.expires_at)
            sub.status, sub.renewal_status = "ACTIVE", "ACTIVE"
        charge = PaymentCharge(
            id=uid(),
            tenant_id=bot.tenant_id,
            payment_id=payment.id,
            bot_id=bot.id,
            provider=payment.provider,
            charge_id=charge_id,
            amount_minor=payment.amount_minor,
            currency=payment.currency,
            period_end=sub.expires_at,
        )
        session.add(charge)
        payment.status, payment.confirmed_at = "APPROVED", now()
        recovered = contact.stage == "EXPIRED"
        contact.stage = "ACTIVE"
        session.flush()
        self.r.ledger.sale(session, charge)
        from .business import history

        history(session, sub, actor, "RENEWED" if renewal else "CREATED", "charge:" + charge.id)
        from .notifications import customer, notify
        from .business import money

        customer(
            session,
            bot,
            contact,
            "RENEWAL" if renewal else "PAYMENT_APPROVED",
            "purchase-notice:" + charge.id,
            sub,
            payment,
        )
        plan = session.get(Plan, payment.plan_id)
        if plan.purchase_message:
            from .texts import render, customer_variables
            from .common import send

            send(
                session,
                bot,
                contact.telegram_user_id,
                render(plan.purchase_message, customer_variables(session, bot, contact, sub, payment)),
                "after-purchase:" + charge.id,
                service_message=True,
            )
        notify(
            session,
            self.r,
            bot,
            "new_sale",
            f"💰 {money(payment.amount_minor, payment.currency)} · {plan.name}\n{contact.first_name}",
            "sale:" + charge.id,
            "payments",
            "detail",
            {"resource": "payments", "id": payment.id},
        )
        audit(session, bot.tenant_id, actor, "PAYMENT_APPROVED", payment.id)
        emit(
            session,
            bot.tenant_id,
            "PAYMENT_CONFIRMED",
            f"charge:{charge_id}",
            bot.id,
            contact.id,
            {"payment_id": payment.id},
        )
        emit(
            session,
            bot.tenant_id,
            "SUBSCRIPTION_RENEWED" if renewal else "SUBSCRIPTION_ACTIVATED",
            f"sub-charge:{charge_id}",
            bot.id,
            contact.id,
        )
        if recovered:
            emit(session, bot.tenant_id, "CUSTOMER_RECOVERED", f"recovered:{charge_id}", bot.id, contact.id)
        enqueue(
            session,
            "GRANT_ACCESS",
            bot.tenant_id,
            {"subscription_id": sub.id},
            f"grant:{sub.id}:{sub.expires_at}",
            bot.id,
        )
        referral = session.scalar(
            select(Referral).where(Referral.referred_id == contact.id, Referral.tenant_id == bot.tenant_id)
        )
        if referral:
            referral.status = "QUALIFIED"
        return sub

    def refunded_event(self, session, bot, event):
        charge = session.scalar(
            select(PaymentCharge)
            .where(
                PaymentCharge.tenant_id == bot.tenant_id,
                PaymentCharge.bot_id == bot.id,
                PaymentCharge.provider == "TELEGRAM_STARS",
                PaymentCharge.charge_id == event["telegram_payment_charge_id"],
            )
            .with_for_update()
        )
        if not charge or charge.refunded_at:
            return
        from .refunds import record

        return record(
            session,
            self.r,
            bot,
            charge,
            charge.amount_minor,
            "stars:" + charge.charge_id,
            "telegram",
            "Telegram Stars refund",
        )

    def expire_due(self, session):
        rows = list(
            session.scalars(
                select(Subscription)
                .where(Subscription.status == "ACTIVE", Subscription.expires_at <= now())
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        )
        if len(rows) == 100:
            enqueue(session, "EXPIRE_SUBSCRIPTIONS", None, {}, f"expire-batch:{now() // 60}:{rows[-1].id}")
        for sub in rows:
            sub.status = "EXPIRED"
            from .business import history

            history(session, sub, "system", "EXPIRED", f"expired:{sub.id}:{sub.expires_at}")
            contact = session.get(Contact, sub.contact_id)
            from .notifications import customer

            customer(
                session,
                session.get(ManagedBot, sub.bot_id),
                contact,
                "SUBSCRIPTION_EXPIRED",
                f"expired-message:{sub.id}:{sub.expires_at}",
                sub,
            )
            other = session.scalar(
                select(Subscription.id).where(
                    Subscription.contact_id == contact.id,
                    Subscription.status == "ACTIVE",
                    Subscription.expires_at > now(),
                    Subscription.id != sub.id,
                )
            )
            if not other:
                contact.stage = "EXPIRED"
            emit(
                session,
                sub.tenant_id,
                "SUBSCRIPTION_EXPIRED",
                f"expired:{sub.id}:{sub.expires_at}",
                sub.bot_id,
                sub.contact_id,
            )
            enqueue(
                session,
                "REVOKE_ACCESS",
                sub.tenant_id,
                {"subscription_id": sub.id},
                f"expire-revoke:{sub.id}:{sub.expires_at}",
                sub.bot_id,
            )
