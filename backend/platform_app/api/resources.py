import csv
import io
from decimal import Decimal
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select, func
from .. import models as m
from ..db import get_scoped
from ..errors import DomainError
from ..services.common import audit
from ..services.tenants import feature, check_entity_limit
from ..services.crm import STAGES
from ..services.texts import validate_text
from .auth import runtime, tenant_context, permit
from .serialization import public
from . import schemas as s

router = APIRouter(prefix="/api/t/{workspace_id}")
RESOURCES = {
    "bots": m.ManagedBot,
    "contacts": m.Contact,
    "plans": m.Plan,
    "prices": m.PlanPrice,
    "channels": m.Channel,
    "payments": m.Payment,
    "charges": m.PaymentCharge,
    "receipts": m.BankReceipt,
    "subscriptions": m.Subscription,
    "conversations": m.Conversation,
    "notes": m.InternalNote,
    "tags": m.Tag,
    "campaigns": m.Campaign,
    "automations": m.AutomationRule,
    "coupons": m.Coupon,
    "referrals": m.Referral,
    "links": m.AttributionLink,
    "team": m.TenantMember,
    "providers": m.ProviderConfig,
    "billing": m.SaaSSubscription,
    "usage": m.UsageCounter,
    "flags": m.FeatureFlag,
    "tasks": m.CRMTask,
    "audit": m.AuditLog,
}


@router.get("/resources/{resource}")
def resources(
    resource: str,
    ctx=Depends(tenant_context),
    r=Depends(runtime),
    limit: int = Query(50, ge=1, le=100),
    after: str | None = None,
    bot_id: str | None = None,
    search: str | None = Query(None, max_length=100),
):
    model = RESOURCES.get(resource)
    if not model:
        raise DomainError("NOT_FOUND", "Lista no disponible.", 404)
    with r.db.tenant(ctx.tenant_id) as db:
        query = select(model).where(model.tenant_id == ctx.tenant_id)
        if bot_id:
            get_scoped(db, m.ManagedBot, bot_id, ctx.tenant_id)
            if hasattr(model, "bot_id"):
                query = query.where(model.bot_id == bot_id)
        if after:
            query = query.where(model.id > after)
        if search and hasattr(model, "first_name"):
            query = query.where(model.first_name.contains(search, autoescape=True))
        elif search and hasattr(model, "name"):
            query = query.where(model.name.contains(search, autoescape=True))
        rows = list(db.scalars(query.order_by(model.id).limit(limit + 1)))
        return {
            "items": [public(x) for x in rows[:limit]],
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
        }


@router.post("/campaigns", status_code=201)
def campaign_create(body: s.CampaignCreate, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "sales", db)
        feature(db, ctx.tenant_id, "campaigns")
        get_scoped(db, m.ManagedBot, body.bot_id, ctx.tenant_id)
        validate_text(body.text)
        if body.stage and body.stage not in STAGES:
            raise DomainError("INVALID_STAGE", "Segmento no válido.")
        row = m.Campaign(
            tenant_id=ctx.tenant_id,
            bot_id=body.bot_id,
            name=body.name,
            text=body.text,
            segment={"stage": body.stage, "source": body.source},
        )
        db.add(row)
        db.flush()
        audit(db, ctx.tenant_id, ctx.user_id, "CAMPAIGN_CREATED", row.id)
        return public(row)


@router.post("/campaigns/{campaign_id}/action")
def campaign_action(
    campaign_id: str, body: s.CampaignAction, ctx=Depends(tenant_context), r=Depends(runtime)
):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "sales", db)
        row = get_scoped(db, m.Campaign, campaign_id, ctx.tenant_id)
        if body.action == "PAUSE":
            if row.status == "COMPLETED":
                raise DomainError("CAMPAIGN_COMPLETED", "La campaña ya finalizó.", 409)
            row.status = "PAUSED"
        else:
            r.campaigns.start(db, row, body.scheduled_at)
        audit(db, ctx.tenant_id, ctx.user_id, "CAMPAIGN_" + body.action, row.id)
        return public(row)


@router.post("/automations", status_code=201)
def automation_create(body: s.AutomationCreate, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        feature(db, ctx.tenant_id, "automations")
        check_entity_limit(db, ctx.tenant_id, "automations", m.AutomationRule)
        get_scoped(db, m.ManagedBot, body.bot_id, ctx.tenant_id)
        validate_text(body.text)
        required = {
            "SEND_MESSAGE": body.text,
            "SEND_PROMOTION": body.text,
            "NOTIFY_ADMIN": body.text,
            "ADD_TAG": body.tag,
            "CREATE_TASK": body.title,
            "CHANGE_CRM_STAGE": body.stage in STAGES,
        }
        if not required[body.action]:
            raise DomainError("ACTION_CONFIG_REQUIRED", "Completa la configuración de la acción.")
        row = m.AutomationRule(
            tenant_id=ctx.tenant_id,
            bot_id=body.bot_id,
            name=body.name,
            trigger=body.trigger,
            action=body.action,
            delay_seconds=body.delay_seconds,
            active=body.active,
            config={"text": body.text, "stage": body.stage, "tag": body.tag, "title": body.title},
        )
        db.add(row)
        db.flush()
        audit(db, ctx.tenant_id, ctx.user_id, "AUTOMATION_CREATED", row.id)
        return public(row)


@router.post("/coupons", status_code=201)
def coupon_create(body: s.CouponCreate, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "sales", db)
        feature(db, ctx.tenant_id, "coupons")
        if body.expires_at <= m.now():
            raise DomainError("COUPON_EXPIRED", "El cupón debe vencer en el futuro.")
        row = m.Coupon(tenant_id=ctx.tenant_id, **{**body.model_dump(), "code": body.code.upper()})
        db.add(row)
        db.flush()
        audit(db, ctx.tenant_id, ctx.user_id, "COUPON_CREATED", row.id)
        return public(row)


@router.post("/links", status_code=201)
def link_create(body: s.LinkCreate, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "sales", db)
        bot = get_scoped(db, m.ManagedBot, body.bot_id, ctx.tenant_id)
        if body.referrer_id:
            feature(db, ctx.tenant_id, "referrals")
            referrer = get_scoped(db, m.Contact, body.referrer_id, ctx.tenant_id)
            if referrer.bot_id != bot.id:
                raise DomainError("REFERRER_MISMATCH", "El referido debe pertenecer al mismo bot.")
        row = m.AttributionLink(
            tenant_id=ctx.tenant_id, code=m.uid().replace("-", "")[:24], **body.model_dump()
        )
        db.add(row)
        db.flush()
        return {**public(row), "url": f"https://t.me/{bot.username}?start={row.code}"}


@router.get("/analytics")
def analytics(ctx=Depends(tenant_context), r=Depends(runtime), days: int = Query(30, ge=1, le=365)):
    with r.db.tenant(ctx.tenant_id) as db:
        return calculate_analytics(db, ctx.tenant_id, days)


def calculate_analytics(db, tenant_id, days=30):
    start = m.now() - days * 86400
    charge_filter = [
        m.PaymentCharge.tenant_id == tenant_id,
        m.PaymentCharge.created_at >= start,
        m.PaymentCharge.refunded_at.is_(None),
    ]
    revenue = db.execute(
        select(m.PaymentCharge.currency, func.sum(m.PaymentCharge.amount_minor))
        .where(*charge_filter)
        .group_by(m.PaymentCharge.currency)
    )
    active = db.scalar(
        select(func.count())
        .select_from(m.Subscription)
        .where(
            m.Subscription.tenant_id == tenant_id,
            m.Subscription.status == "ACTIVE",
            m.Subscription.expires_at > m.now(),
        )
    )
    contacts = db.scalar(select(func.count()).select_from(m.Contact).where(m.Contact.tenant_id == tenant_id))
    new_clients = db.scalar(
        select(func.count())
        .select_from(m.Contact)
        .where(m.Contact.tenant_id == tenant_id, m.Contact.created_at >= start)
    )
    pending = db.scalar(
        select(func.count())
        .select_from(m.BankReceipt)
        .where(m.BankReceipt.tenant_id == tenant_id, m.BankReceipt.status == "PENDING")
    )
    customers_paid = db.scalar(
        select(func.count(func.distinct(m.Payment.contact_id))).where(
            m.Payment.tenant_id == tenant_id, m.Payment.status == "APPROVED"
        )
    )

    def grouped(column):
        return [
            {"key": key, "currency": currency, "amount_minor": str(amount)}
            for key, currency, amount in db.execute(
                select(column, m.PaymentCharge.currency, func.sum(m.PaymentCharge.amount_minor))
                .join(m.Payment, m.Payment.id == m.PaymentCharge.payment_id)
                .where(*charge_filter)
                .group_by(column, m.PaymentCharge.currency)
            )
        ]

    amounts = {currency: str(amount) for currency, amount in revenue}
    all_time = {
        currency: str(amount)
        for currency, amount in db.execute(
            select(m.PaymentCharge.currency, func.sum(m.PaymentCharge.amount_minor))
            .where(m.PaymentCharge.tenant_id == tenant_id, m.PaymentCharge.refunded_at.is_(None))
            .group_by(m.PaymentCharge.currency)
        )
    }
    events = dict(
        db.execute(
            select(m.Event.type, func.count())
            .where(m.Event.tenant_id == tenant_id, m.Event.created_at >= start)
            .group_by(m.Event.type)
        ).all()
    )
    return {
        "days": days,
        "revenue_minor": amounts,
        "active_subscriptions": active,
        "contacts": contacts,
        "new_clients": new_clients,
        "pending_receipts": pending,
        "conversion_percent": str(
            (Decimal(customers_paid or 0) * 100 / max(contacts or 0, 1)).quantize(Decimal(".01"))
        ),
        "arpu_minor": {c: str(Decimal(v) / max(contacts or 0, 1)) for c, v in amounts.items()},
        "ltv_minor": {c: str(Decimal(v) / max(customers_paid or 0, 1)) for c, v in all_time.items()},
        "by_plan": grouped(m.Payment.plan_id),
        "by_provider": grouped(m.Payment.provider),
        "renewals": events.get("SUBSCRIPTION_RENEWED", 0),
        "expired": events.get("SUBSCRIPTION_EXPIRED", 0),
        "expiring": events.get("SUBSCRIPTION_EXPIRING", 0),
        "recovered": events.get("CUSTOMER_RECOVERED", 0),
    }


@router.get("/export/{resource}")
def export(resource: str, ctx=Depends(tenant_context), r=Depends(runtime), after: str | None = None):
    allowed = {"contacts", "subscriptions", "payments", "campaigns"}
    if resource not in allowed:
        raise DomainError("EXPORT_NOT_SUPPORTED", "Exportación no disponible.", 404)
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "export")
        # Exports remain available to suspended owners; do not destroy or hold their data hostage.
        model = RESOURCES[resource]
        query = select(model).where(model.tenant_id == ctx.tenant_id)
        if after:
            query = query.where(model.id > after)
        rows = list(db.scalars(query.order_by(model.id).limit(1001)))
        values = [public(x) for x in rows[:1000]]
        buffer = io.StringIO(newline="")
        if values:
            writer = csv.DictWriter(buffer, fieldnames=values[0].keys())
            writer.writeheader()
            for item in values:
                writer.writerow(
                    {
                        k: "'" + v
                        if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
                        else v
                        for k, v in item.items()
                    }
                )
        audit(
            db, ctx.tenant_id, ctx.user_id, "DATA_EXPORTED", data={"resource": resource, "rows": len(values)}
        )
        return Response(
            buffer.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{resource}.csv"',
                "X-Next-Cursor": rows[999].id if len(rows) > 1000 else "",
                "Cache-Control": "no-store",
            },
        )
