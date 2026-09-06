from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy import select
from .. import models as m
from ..db import get_scoped
from ..errors import DomainError
from ..services.crm import conversation
from ..services.common import emit
from .auth import runtime, customer, login
from .serialization import public
from . import schemas as s

router = APIRouter(prefix="/api")


@router.post("/auth/b/{public_id}")
def auth_customer(public_id: str, body: s.Login, r=Depends(runtime)):
    return login(r, body.init_data, public_id)


def own_contact(db, bot, auth):
    contact = db.scalar(
        select(m.Contact).where(
            m.Contact.bot_id == bot.id, m.Contact.telegram_user_id == auth.telegram_user_id
        )
    )
    if not contact:
        raise DomainError("START_BOT_REQUIRED", "Abre el bot y pulsa Start para activar tu perfil.", 409)
    return contact


@router.get("/b/{public_id}/me")
def profile(ctx=Depends(customer), r=Depends(runtime)):
    bot, auth = ctx
    with r.db.tenant(bot.tenant_id) as db:
        contact = own_contact(db, bot, auth)
        settings = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
        return {
            "bot": {"name": bot.name, "username": bot.username, "public_id": bot.public_id},
            "branding": settings.branding,
            "policies": settings.policies,
            "support_username": settings.support_username,
            "contact": public(contact),
            "subscriptions": [
                public(x)
                for x in db.scalars(select(m.Subscription).where(m.Subscription.contact_id == contact.id))
            ],
            "payments": [
                public(x)
                for x in db.scalars(
                    select(m.Payment)
                    .where(m.Payment.contact_id == contact.id)
                    .order_by(m.Payment.created_at.desc())
                    .limit(100)
                )
            ],
        }


@router.get("/b/{public_id}/plans")
def plans(ctx=Depends(customer), r=Depends(runtime)):
    bot, auth = ctx

    def load():
        with r.db.tenant(bot.tenant_id) as db:
            rows = list(
                db.scalars(
                    select(m.Plan)
                    .where(m.Plan.bot_id == bot.id, m.Plan.active.is_(True))
                    .order_by(m.Plan.sort_order)
                    .limit(100)
                )
            )
            prices = (
                list(
                    db.scalars(
                        select(m.PlanPrice).where(
                            m.PlanPrice.plan_id.in_([p.id for p in rows]),
                            m.PlanPrice.provider == "TELEGRAM_STARS",
                            m.PlanPrice.currency == "XTR",
                        )
                    )
                )
                if rows
                else []
            )
            # The digital storefront exposes only Stars, even when an external provider exists.
            return [
                {**public(p), "prices": [public(price) for price in prices if price.plan_id == p.id]}
                for p in rows
            ]

    return r.public_cache.read(bot, "plans", load)


@router.post("/b/{public_id}/checkout")
def checkout(body: s.Checkout, ctx=Depends(customer), r=Depends(runtime)):
    bot, auth = ctx
    with r.db.tenant(bot.tenant_id) as db:
        contact = own_contact(db, bot, auth)
        payment = r.payments.create(
            db,
            bot,
            contact,
            body.plan_id,
            "TELEGRAM_STARS",
            "XTR",
            f"customer:{contact.id}:{body.idempotency_key}",
            coupon_code=body.coupon_code,
        )
        emit(db, bot.tenant_id, "PLAN_SELECTED", f"plan-selected:{payment.id}", bot.id, contact.id)
        return {"id": payment.id, "url": payment.checkout_url, "status": payment.status}


@router.post("/b/{public_id}/payments/{payment_id}/receipt")
def receipt(payment_id: str, file: UploadFile = File(...), ctx=Depends(customer), r=Depends(runtime)):
    bot, auth = ctx
    with r.db.tenant(bot.tenant_id) as db:
        contact = own_contact(db, bot, auth)
        payment = get_scoped(db, m.Payment, payment_id, bot.tenant_id)
        if payment.contact_id != contact.id or payment.bot_id != bot.id:
            raise DomainError("NOT_FOUND", "Pago no disponible.", 404)
        return public(r.receipts.submit(db, bot, payment, file.file.read(r.settings.max_upload_bytes + 1)))


@router.post("/b/{public_id}/subscriptions/{subscription_id}/renewal")
def renewal(subscription_id: str, body: s.CancelRenewal, ctx=Depends(customer), r=Depends(runtime)):
    bot, auth = ctx
    with r.db.tenant(bot.tenant_id) as db:
        contact = own_contact(db, bot, auth)
        sub = get_scoped(db, m.Subscription, subscription_id, bot.tenant_id)
        if sub.contact_id != contact.id or sub.bot_id != bot.id:
            raise DomainError("NOT_FOUND", "Suscripción no disponible.", 404)
        payment = db.get(m.Payment, sub.payment_id)
        if payment.provider != "TELEGRAM_STARS" or not payment.recurring:
            raise DomainError("NOT_RECURRING", "Esta membresía se renueva manualmente.", 409)
        r.payments.providers["TELEGRAM_STARS"].cancel_subscription(db, bot, contact, sub, body.canceled)
        sub.auto_renew = not body.canceled
        sub.renewal_status = "CANCELED" if body.canceled else "ACTIVE"
        return public(sub)


@router.post("/b/{public_id}/support")
def support(body: s.Note, ctx=Depends(customer), r=Depends(runtime)):
    bot, auth = ctx
    with r.db.tenant(bot.tenant_id) as db:
        contact = own_contact(db, bot, auth)
        conv = conversation(db, bot, contact)
        db.add(
            m.Message(
                tenant_id=bot.tenant_id,
                conversation_id=conv.id,
                direction="IN",
                text=body.text,
                status="RECEIVED",
            )
        )
        return {"received": True}
