"""Tenant/bot-scoped business operations used by native menus and queued work."""

from decimal import Decimal, InvalidOperation
from sqlalchemy import select, func
from .. import models as m
from ..db import get_scoped
from ..errors import DomainError
from ..security import digest, random_secret, ROLES
from .common import audit, emit, enqueue
from .tenants import entitlement

CURRENCY_DECIMALS = {
    "XTR": 0,
    "USD": 2,
    "EUR": 2,
    "BOB": 2,
    "MXN": 2,
    "BRL": 2,
    "PEN": 2,
    "COP": 2,
    "ARS": 2,
    "CLP": 0,
    "JPY": 0,
    "GBP": 2,
    "USDT": 6,
    "USDC": 6,
    "BTC": 8,
    "ETH": 18,
}


def amount_minor(value, currency):
    if currency not in CURRENCY_DECIMALS:
        raise DomainError("UNSUPPORTED_CURRENCY", "Moneda no soportada. Elige una moneda del menú.")
    try:
        amount = Decimal(str(value))
        scaled = amount * 10 ** CURRENCY_DECIMALS[currency]
        if not amount.is_finite() or scaled != scaled.to_integral_value() or not 0 < scaled < 10**16:
            raise ValueError()
        return int(scaled)
    except (ValueError, InvalidOperation):
        raise DomainError(
            "INVALID_AMOUNT", "Indica un importe positivo con los decimales de la moneda."
        ) from None


def money(amount, currency):
    places = CURRENCY_DECIMALS.get(currency, 2)
    return f"{Decimal(amount) / 10**places:.{places}f} {currency}"


def entity(db, model, entity_id, bot):
    row = get_scoped(db, model, entity_id, bot.tenant_id)
    bid = getattr(row, "bot_id", None)
    if bid is not None and bid != bot.id:
        raise DomainError("NOT_FOUND", "Recurso no disponible en este bot.", 404)
    return row


def plan_channels(db, plan):
    return list(
        dict.fromkeys(
            ([plan.channel_id] if plan.channel_id else [])
            + list(
                db.scalars(
                    select(m.PlanChannel.channel_id).where(
                        m.PlanChannel.plan_id == plan.id, m.PlanChannel.tenant_id == plan.tenant_id
                    )
                )
            )
        )
    )


def save_channels(db, bot, plan, ids, actor):
    ids = list(dict.fromkeys(ids))
    if len(ids) > 30:
        raise DomainError("TOO_MANY_CHANNELS", "Un plan admite hasta 30 canales.")
    for cid in ids:
        channel = entity(db, m.Channel, cid, bot)
        if channel.access_mode != "PLATFORM":
            raise DomainError("CHANNEL_MODE", "Este canal tiene acceso nativo de Telegram.")
    before = plan_channels(db, plan)
    old = list(
        db.scalars(
            select(m.PlanChannel).where(
                m.PlanChannel.plan_id == plan.id, m.PlanChannel.tenant_id == bot.tenant_id
            )
        )
    )
    for row in old:
        if row.channel_id not in ids:
            db.delete(row)
    for cid in ids:
        if cid not in {x.channel_id for x in old}:
            db.add(m.PlanChannel(tenant_id=bot.tenant_id, plan_id=plan.id, channel_id=cid))
    plan.channel_id = ids[0] if ids else None
    audit(db, bot.tenant_id, actor, "PLAN_CHANNELS_CHANGED", plan.id, {"before": before, "after": ids})


def save_plan(db, bot, actor, values, plan=None):
    entitlement(db, bot.tenant_id)
    name = str(values.get("name", plan.name if plan else "")).strip()
    days = values.get("duration_days", plan.duration_days if plan else 30)
    if not 1 <= len(name) <= 100 or type(days) is not int or not 1 <= days <= 3650:
        raise DomainError("INVALID_PLAN", "Revisa el nombre y la duración del plan.")
    if plan and (plan.bot_id != bot.id or plan.tenant_id != bot.tenant_id):
        raise DomainError("NOT_FOUND", "Plan no disponible.")
    if not plan:
        plan = m.Plan(id=m.uid(), tenant_id=bot.tenant_id, bot_id=bot.id, name=name, duration_days=days)
        db.add(plan)
        db.flush()
    before = {
        k: getattr(plan, k)
        for k in (
            "name",
            "description",
            "duration_days",
            "active",
            "visible",
            "recurring",
            "sort_order",
            "product_kind",
            "purchase_message",
            "benefits",
        )
    }
    for key, value in values.items():
        if key in before:
            setattr(plan, key, value)
    plan.name, plan.duration_days = name, days
    if len(plan.description) > 1000 or len(plan.purchase_message) > 2000 or len(plan.benefits) > 20:
        raise DomainError("INVALID_PLAN", "El texto o la lista de beneficios es demasiado largo.")
    if plan.product_kind not in {"DIGITAL", "PHYSICAL", "OFFLINE_SERVICE"}:
        raise DomainError("INVALID_PRODUCT_KIND", "Indica el tipo real del producto.")
    if plan.recurring and plan.duration_days != 30:
        raise DomainError("INVALID_RENEWAL", "La renovación automática en Stars requiere 30 días.")
    if "channel_ids" in values:
        save_channels(db, bot, plan, values["channel_ids"], actor)
    audit(
        db,
        bot.tenant_id,
        actor,
        "PLAN_SAVED",
        plan.id,
        {"before": before, "after": {k: getattr(plan, k) for k in before}},
    )
    return plan


def price(db, bot, plan, provider, currency, value, actor):
    if provider not in {"TELEGRAM_STARS", "BANK_TRANSFER", "STRIPE", "PAYPAL"}:
        raise DomainError("INVALID_PROVIDER", "Proveedor no soportado.")
    if (
        provider == "TELEGRAM_STARS"
        and currency != "XTR"
        or provider != "TELEGRAM_STARS"
        and currency == "XTR"
    ):
        raise DomainError(
            "INVALID_CURRENCY", "Stars utiliza XTR; los demás métodos utilizan moneda fiduciaria."
        )
    amount = amount_minor(value, currency)
    if provider == "TELEGRAM_STARS" and plan.recurring and amount > 10000:
        raise DomainError("STARS_LIMIT", "La suscripción recurrente admite hasta 10.000 Stars.")
    row = db.scalar(
        select(m.PlanPrice)
        .where(
            m.PlanPrice.plan_id == plan.id,
            m.PlanPrice.tenant_id == bot.tenant_id,
            m.PlanPrice.provider == provider,
            m.PlanPrice.currency == currency,
        )
        .with_for_update()
    )
    before = row.amount_minor if row else None
    if not row:
        row = m.PlanPrice(tenant_id=bot.tenant_id, plan_id=plan.id, provider=provider, currency=currency)
        db.add(row)
    row.amount_minor = amount
    audit(
        db,
        bot.tenant_id,
        actor,
        "PLAN_PRICE_CHANGED",
        plan.id,
        {"provider": provider, "currency": currency, "before_minor": before, "after_minor": amount},
    )
    return row


def duplicate_plan(db, bot, original, actor):
    values = {
        key: getattr(original, key)
        for key in (
            "description",
            "benefits",
            "duration_days",
            "recurring",
            "sort_order",
            "product_kind",
            "purchase_message",
        )
    }
    copy = save_plan(
        db,
        bot,
        actor,
        {
            **values,
            "name": (original.name + " (copia)")[:100],
            "active": False,
            "visible": False,
            "channel_ids": plan_channels(db, original),
        },
    )
    for old in db.scalars(
        select(m.PlanPrice).where(m.PlanPrice.plan_id == original.id, m.PlanPrice.tenant_id == bot.tenant_id)
    ):
        db.add(
            m.PlanPrice(
                tenant_id=bot.tenant_id,
                plan_id=copy.id,
                provider=old.provider,
                currency=old.currency,
                amount_minor=old.amount_minor,
            )
        )
    return copy


def history(db, sub, actor, action, key, before=None, reason=""):
    previous = db.scalar(
        select(m.SubscriptionHistory).where(
            m.SubscriptionHistory.tenant_id == sub.tenant_id, m.SubscriptionHistory.operation_key == key
        )
    )
    if previous:
        return previous
    revision = (
        db.scalar(
            select(func.max(m.SubscriptionHistory.revision)).where(
                m.SubscriptionHistory.subscription_id == sub.id,
                m.SubscriptionHistory.tenant_id == sub.tenant_id,
            )
        )
        or 0
    ) + 1
    row = m.SubscriptionHistory(
        tenant_id=sub.tenant_id,
        subscription_id=sub.id,
        revision=revision,
        actor_id=actor,
        action=action,
        operation_key=key,
        before=before or {},
        after={
            "status": sub.status,
            "plan_id": sub.plan_id,
            "starts_at": sub.starts_at,
            "expires_at": sub.expires_at,
            "origin": sub.origin,
            "channels": sub.channel_snapshot,
        },
        reason=reason[:500],
    )
    db.add(row)
    audit(
        db,
        sub.tenant_id,
        actor,
        "SUBSCRIPTION_" + action,
        sub.id,
        {"before": row.before, "after": row.after, "reason": reason},
    )
    return row


def manage_subscription(db, bot, sub, actor, action, key, days=None, plan_id=None, reason=""):
    sub = db.scalar(
        select(m.Subscription)
        .where(
            m.Subscription.id == sub.id,
            m.Subscription.bot_id == bot.id,
            m.Subscription.tenant_id == bot.tenant_id,
        )
        .with_for_update()
    )
    if not sub:
        raise DomainError("NOT_FOUND", "Suscripción no disponible.")
    if db.scalar(
        select(m.SubscriptionHistory.id).where(
            m.SubscriptionHistory.tenant_id == bot.tenant_id, m.SubscriptionHistory.operation_key == key
        )
    ):
        return sub
    before = {
        "status": sub.status,
        "plan_id": sub.plan_id,
        "expires_at": sub.expires_at,
        "channels": list(sub.channel_snapshot),
    }
    if action in {"EXTEND", "GIFT_DAYS", "RENEW"}:
        if type(days) is not int or not 1 <= days <= 3650:
            raise DomainError("INVALID_DURATION", "Indica entre 1 y 3650 días.")
        sub.expires_at = max(m.now(), sub.expires_at) + days * 86400
        sub.status = "ACTIVE"
    elif action in {"CANCEL", "SUSPEND"}:
        sub.status = "CANCELLED" if action == "CANCEL" else "SUSPENDED"
        if sub.auto_renew and sub.initial_charge_id:
            enqueue(
                db,
                "CANCEL_CUSTOMER_RENEWAL",
                bot.tenant_id,
                {"subscription_id": sub.id},
                "cancel-renewal:" + key,
                bot.id,
            )
            sub.renewal_status = "CANCEL_PENDING"
        else:
            sub.auto_renew = False
    elif action == "REACTIVATE":
        if sub.expires_at <= m.now():
            raise DomainError("EXPIRED", "Amplía la duración antes de reactivar una suscripción vencida.")
        sub.status = "ACTIVE"
    elif action == "CHANGE_PLAN":
        plan = entity(db, m.Plan, plan_id, bot)
        if plan.archived_at:
            raise DomainError("PLAN_ARCHIVED", "El plan está archivado.")
        sub.plan_id, sub.channel_snapshot = plan.id, plan_channels(db, plan)
    else:
        raise DomainError("INVALID_ACTION", "Acción de suscripción no válida.")
    history(db, sub, actor, action, key, before, reason)
    if action == "CANCEL":
        enqueue(
            db,
            "BUSINESS_NOTICE",
            bot.tenant_id,
            {
                "category": "cancel",
                "message": {
                    "key": "cancel_notice",
                    "values": {
                        "name": db.get(m.Contact, sub.contact_id).first_name,
                        "plan": db.get(m.Plan, sub.plan_id).name,
                    },
                },
            },
            "cancel-notice:" + key,
            bot.id,
        )
    if action in {"CANCEL", "SUSPEND", "CHANGE_PLAN"}:
        enqueue(
            db,
            "REVOKE_ACCESS",
            bot.tenant_id,
            {"subscription_id": sub.id, "channel_ids": before["channels"]},
            "sub-revoke:" + key,
            bot.id,
        )
    if sub.status == "ACTIVE":
        enqueue(db, "GRANT_ACCESS", bot.tenant_id, {"subscription_id": sub.id}, "sub-grant:" + key, bot.id)
    return sub


def grant_subscription(db, bot, person, plan, actor, days, reason, key):
    entitlement(db, bot.tenant_id)
    person = entity(db, m.Contact, person.id, bot)
    plan = entity(db, m.Plan, plan.id, bot)
    db.refresh(person, with_for_update=True)
    previous = db.scalar(
        select(m.SubscriptionHistory).where(
            m.SubscriptionHistory.tenant_id == bot.tenant_id, m.SubscriptionHistory.operation_key == key
        )
    )
    if previous:
        return entity(db, m.Subscription, previous.subscription_id, bot)
    if type(days) is not int or not 1 <= days <= 3650 or len(reason.strip()) < 3 or plan.archived_at:
        raise DomainError("INVALID_GRANT", "Revisa el plan, la duración y el motivo del acceso gratuito.")
    sub = m.Subscription(
        id=m.uid(),
        tenant_id=bot.tenant_id,
        bot_id=bot.id,
        contact_id=person.id,
        plan_id=plan.id,
        payment_id=None,
        origin="MANUAL",
        starts_at=m.now(),
        expires_at=m.now() + days * 86400,
        channel_snapshot=plan_channels(db, plan),
        status="ACTIVE",
        auto_renew=False,
    )
    db.add(sub)
    db.flush()
    person.stage = "ACTIVE"
    history(db, sub, actor, "MANUAL_GRANTED", key, reason=reason)
    enqueue(db, "GRANT_ACCESS", bot.tenant_id, {"subscription_id": sub.id}, "manual-access:" + sub.id, bot.id)
    return sub


class InvitationService:
    def __init__(self, runtime):
        self.r = runtime

    def create(self, db, bot, actor, plan_id, days, max_uses, expires_at, note="", channel_ids=None):
        entitlement(db, bot.tenant_id)
        plan = entity(db, m.Plan, plan_id, bot)
        if (
            type(days) is not int
            or not 1 <= days <= 3650
            or type(max_uses) is not int
            or not 1 <= max_uses <= 100000
            or not m.now() < expires_at <= m.now() + 366 * 86400
        ):
            raise DomainError(
                "INVALID_INVITATION", "Revisa duración, usos y fecha de vencimiento del enlace."
            )
        included = plan_channels(db, plan)
        selected = included if channel_ids is None else list(dict.fromkeys(channel_ids))
        if not set(selected).issubset(included):
            raise DomainError("INVALID_CHANNEL", "La invitación solo puede incluir canales del plan.")
        code = random_secret()
        offer = m.AccessOffer(
            id=m.uid(),
            tenant_id=bot.tenant_id,
            bot_id=bot.id,
            plan_id=plan.id,
            code_hash=digest(code),
            code_ciphertext={},
            duration_days=days,
            channel_ids=selected,
            max_uses=max_uses,
            uses=0,
            expires_at=expires_at,
            actor_id=actor,
            note=note[:500],
        )
        offer.code_ciphertext = self.r.vault.encrypt(code, f"{bot.tenant_id}:{offer.id}:invite")
        db.add(offer)
        audit(
            db,
            bot.tenant_id,
            actor,
            "INVITATION_CREATED",
            offer.id,
            {"plan_id": plan.id, "days": days, "max_uses": max_uses, "expires_at": expires_at},
        )
        return offer

    def link(self, bot, offer):
        if offer.bot_id != bot.id or offer.tenant_id != bot.tenant_id:
            raise DomainError("NOT_FOUND", "Invitación no disponible.")
        code = self.r.vault.decrypt(offer.code_ciphertext, f"{bot.tenant_id}:{offer.id}:invite")
        return f"https://t.me/{bot.username}?start=gift_{code}"

    def redeem(self, db, bot, contact, code):
        entitlement(db, bot.tenant_id)
        if contact.bot_id != bot.id or contact.tenant_id != bot.tenant_id or len(code) > 64:
            raise DomainError("NOT_FOUND", "Invitación no disponible.")
        offer = db.scalar(
            select(m.AccessOffer)
            .where(
                m.AccessOffer.bot_id == bot.id,
                m.AccessOffer.tenant_id == bot.tenant_id,
                m.AccessOffer.code_hash == digest(code),
            )
            .with_for_update()
        )
        if not offer:
            raise DomainError("INVITATION_INVALID", "El enlace de invitación no es válido.")
        old = db.scalar(
            select(m.AccessRedemption).where(
                m.AccessRedemption.offer_id == offer.id, m.AccessRedemption.contact_id == contact.id
            )
        )
        if old:
            return db.get(m.Subscription, old.subscription_id)
        if not offer.active or offer.expires_at <= m.now() or offer.uses >= offer.max_uses:
            raise DomainError("INVITATION_EXPIRED", "Esta invitación venció o agotó sus usos.")
        plan = entity(db, m.Plan, offer.plan_id, bot)
        db.scalar(select(m.Contact).where(m.Contact.id == contact.id).with_for_update())
        sub = m.Subscription(
            id=m.uid(),
            tenant_id=bot.tenant_id,
            bot_id=bot.id,
            contact_id=contact.id,
            plan_id=plan.id,
            payment_id=None,
            origin="invite_link",
            starts_at=m.now(),
            expires_at=m.now() + offer.duration_days * 86400,
            channel_snapshot=list(offer.channel_ids),
            status="ACTIVE",
            auto_renew=False,
        )
        db.add(sub)
        db.flush()
        db.add(
            m.AccessRedemption(
                tenant_id=bot.tenant_id, offer_id=offer.id, contact_id=contact.id, subscription_id=sub.id
            )
        )
        offer.uses += 1
        contact.stage = "ACTIVE"
        history(
            db,
            sub,
            str(contact.telegram_user_id),
            "INVITE_GRANTED",
            "invite:" + offer.id + ":" + contact.id,
            reason=offer.note,
        )
        emit(
            db,
            bot.tenant_id,
            "INVITE_USED",
            "invite-used:" + offer.id + ":" + contact.id,
            bot.id,
            contact.id,
            {"offer_id": offer.id, "subscription_id": sub.id},
        )
        enqueue(
            db, "GRANT_ACCESS", bot.tenant_id, {"subscription_id": sub.id}, "invite-access:" + sub.id, bot.id
        )
        return sub


def set_admin(db, bot, actor, telegram_id, role, permissions=None, *, platform_owner=False):
    if role not in set(ROLES) | {"CUSTOM"} or role == "OWNER":
        raise DomainError(
            "INVALID_ROLE", "Elige un rol de administrador; la propiedad no se transfiere aquí."
        )
    user = db.scalar(select(m.PlatformUser).where(m.PlatformUser.telegram_user_id == telegram_id))
    if not user:
        raise DomainError(
            "USER_NOT_REGISTERED", "La persona debe iniciar primero el bot maestro de la plataforma."
        )
    tenant = db.get(m.Tenant, bot.tenant_id)
    if user.id == tenant.owner_user_id:
        raise DomainError("OWNER_PROTECTED", "El propietario conserva siempre el control total.", 403)
    allowed = set(permissions or [])
    if not allowed.issubset(ROLES["ADMIN"]):
        raise DomainError("INVALID_PERMISSION", "La lista contiene permisos no válidos.")
    from .tenants import feature

    feature(db, bot.tenant_id, "team_members")
    db.refresh(tenant, with_for_update=True)
    if actor != tenant.owner_user_id and not platform_owner:
        grantor = db.scalar(
            select(m.BotAdmin).where(
                m.BotAdmin.tenant_id == bot.tenant_id,
                m.BotAdmin.bot_id == bot.id,
                m.BotAdmin.user_id == actor,
                m.BotAdmin.active.is_(True),
            )
        )
        grantable = set(
            grantor.permissions
            if grantor and grantor.role == "CUSTOM"
            else ROLES.get(grantor.role, set())
            if grantor
            else set()
        )
        if not (allowed if role == "CUSTOM" else ROLES[role]).issubset(grantable):
            raise DomainError("PERMISSION_ESCALATION", "Solo puedes conceder permisos que ya tienes.", 403)
    already_member = db.scalar(
        select(m.BotAdmin.id)
        .where(
            m.BotAdmin.tenant_id == bot.tenant_id, m.BotAdmin.user_id == user.id, m.BotAdmin.active.is_(True)
        )
        .limit(1)
    )
    if not already_member:
        _, _, plan = entitlement(db, bot.tenant_id)
        total = (
            db.scalar(
                select(func.count(func.distinct(m.BotAdmin.user_id))).where(
                    m.BotAdmin.tenant_id == bot.tenant_id,
                    m.BotAdmin.active.is_(True),
                    m.BotAdmin.user_id != tenant.owner_user_id,
                )
            )
            or 0
        )
        if total + 1 >= plan.limits.get("admins", 2):
            raise DomainError("PLAN_LIMIT", "Alcanzaste el límite de administradores de tu plan.", 409)
    row = db.scalar(
        select(m.BotAdmin).where(m.BotAdmin.bot_id == bot.id, m.BotAdmin.user_id == user.id).with_for_update()
    )
    before = {"role": row.role, "active": row.active, "permissions": row.permissions} if row else {}
    if not row:
        row = m.BotAdmin(tenant_id=bot.tenant_id, bot_id=bot.id, user_id=user.id)
        db.add(row)
    row.role, row.active, row.permissions = role, True, sorted(allowed)
    audit(
        db,
        bot.tenant_id,
        actor,
        "BOT_ADMIN_CHANGED",
        row.id,
        {"before": before, "after": {"role": role, "permissions": row.permissions, "user_id": user.id}},
    )
    return row
