from sqlalchemy import select, func
from .. import models as m
from ..errors import DomainError
from .common import audit, enqueue, emit
from .business import history


def record(db, runtime, bot, charge, amount, reference, actor, reason=""):
    charge = db.scalar(
        select(m.PaymentCharge).where(
            m.PaymentCharge.id == charge.id,
            m.PaymentCharge.bot_id == bot.id,
            m.PaymentCharge.tenant_id == bot.tenant_id,
        )
    )
    if not charge:
        raise DomainError("NOT_FOUND", "Cargo no disponible.", 404)
    payment = db.scalar(
        select(m.Payment)
        .where(
            m.Payment.id == charge.payment_id,
            m.Payment.bot_id == bot.id,
            m.Payment.tenant_id == bot.tenant_id,
        )
        .with_for_update()
    )
    db.refresh(charge, with_for_update=True)
    previous = db.scalar(
        select(m.PaymentRefund).where(
            m.PaymentRefund.bot_id == bot.id,
            m.PaymentRefund.provider == charge.provider,
            m.PaymentRefund.reference == reference,
        )
    )
    if previous:
        if previous.charge_id != charge.id or previous.amount_minor != amount:
            raise DomainError("REFUND_CONFLICT", "La devolución ya existe con otros datos.", 409)
        return previous
    refunded = (
        db.scalar(
            select(func.sum(m.PaymentRefund.amount_minor)).where(m.PaymentRefund.charge_id == charge.id)
        )
        or 0
    )
    if (
        type(amount) is not int
        or amount <= 0
        or refunded + amount > charge.amount_minor
        or charge.refunded_at
    ):
        raise DomainError("INVALID_REFUND", "El importe supera el saldo reembolsable.", 409)
    row = m.PaymentRefund(
        id=m.uid(),
        tenant_id=bot.tenant_id,
        bot_id=bot.id,
        charge_id=charge.id,
        provider=charge.provider,
        reference=reference[:255],
        amount_minor=amount,
        currency=charge.currency,
        actor_id=str(actor),
        reason=reason[:500],
    )
    db.add(row)
    db.flush()
    runtime.ledger.refund(db, charge, amount=amount, key=row.id)
    sub = db.scalar(select(m.Subscription).where(m.Subscription.payment_id == payment.id).with_for_update())
    if refunded + amount == charge.amount_minor:
        charge.refunded_at = m.now()
        remaining = list(
            db.scalars(
                select(m.PaymentCharge).where(
                    m.PaymentCharge.payment_id == payment.id,
                    m.PaymentCharge.refunded_at.is_(None),
                    m.PaymentCharge.id != charge.id,
                )
            )
        )
        payment.status = "APPROVED" if remaining else "REFUNDED"
        if sub:
            sub.expires_at = max([item.period_end or 0 for item in remaining], default=m.now())
            if sub.expires_at <= m.now():
                sub.status, sub.auto_renew = "EXPIRED", False
                enqueue(
                    db,
                    "REVOKE_ACCESS",
                    bot.tenant_id,
                    {"subscription_id": sub.id},
                    "refund-revoke:" + row.id,
                    bot.id,
                )
    if sub:
        history(
            db,
            sub,
            str(actor),
            "REFUNDED" if charge.refunded_at else "PARTIAL_REFUND",
            "refund-history:" + row.id,
            reason=reason,
        )
    audit(
        db,
        bot.tenant_id,
        str(actor),
        "PAYMENT_REFUNDED",
        payment.id,
        {
            "bot_id": bot.id,
            "refund_id": row.id,
            "amount_minor": amount,
            "currency": charge.currency,
            "reason": reason,
        },
    )
    emit(
        db,
        bot.tenant_id,
        "PAYMENT_REFUNDED",
        "refund:" + row.id,
        bot.id,
        payment.contact_id,
        {"payment_id": payment.id, "refund_id": row.id},
    )
    return row
