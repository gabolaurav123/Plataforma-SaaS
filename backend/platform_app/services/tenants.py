from sqlalchemy import select, func
from ..models import (
    PlatformUser,
    Tenant,
    TenantMember,
    Onboarding,
    SaaSPlan,
    SaaSSubscription,
    FeatureFlag,
    UsageCounter,
    now,
    uid,
)
from ..errors import DomainError
from .common import audit


DEFAULT_LIMITS = {
    "bots": 1,
    "admins": 2,
    "active_contacts": 1000,
    "campaigns_month": 5,
    "automations": 5,
    "analytics_retention_days": 90,
    "exports_month": 5,
    "ai_units": 0,
}
DEFAULT_FEATURES = {
    "bank_payments": True,
    "stars": True,
    "external_payments": False,
    "campaigns": True,
    "automations": True,
    "advanced_analytics": False,
    "coupons": True,
    "referrals": True,
    "team_members": True,
    "ai": False,
    "ocr": False,
    "custom_branding": True,
    "multiple_bots": False,
}


def seed_saas_plans(session):
    for name, bots, contacts, campaigns, admins in [
        ("STARTER", 1, 1000, 5, 2),
        ("PRO", 3, 10000, 30, 5),
        ("AGENCY", 10, 100000, 100, 20),
    ]:
        if not session.scalar(select(SaaSPlan).where(SaaSPlan.name == name)):
            session.add(
                SaaSPlan(
                    name=name,
                    limits={
                        **DEFAULT_LIMITS,
                        "bots": bots,
                        "active_contacts": contacts,
                        "campaigns_month": campaigns,
                        "admins": admins,
                    },
                    features={**DEFAULT_FEATURES, "multiple_bots": bots > 1},
                    prices={},
                )
            )
    session.flush()


def upsert_user(session, user):
    obj = session.scalar(select(PlatformUser).where(PlatformUser.telegram_user_id == user["id"]))
    if not obj:
        obj = PlatformUser(
            id=uid(), telegram_user_id=user["id"], first_name=user.get("first_name", "Creador")[:128]
        )
        session.add(obj)
    obj.username, obj.first_name = user.get("username"), user.get("first_name", obj.first_name)[:128]
    session.flush()
    return obj


def create_tenant(session, user, name, settings):
    # Lock the global user row: repeated/concurrent onboarding cannot exceed owner quotas.
    session.scalar(select(PlatformUser).where(PlatformUser.id == user.id).with_for_update())
    count = session.scalar(select(func.count()).select_from(Tenant).where(Tenant.owner_user_id == user.id))
    if count >= 10:
        raise DomainError("WORKSPACE_LIMIT", "Contacta soporte para crear más espacios.", 409)
    seed_saas_plans(session)
    plan = session.scalar(select(SaaSPlan).where(SaaSPlan.name == "STARTER"))
    tenant = Tenant(id=uid(), name=name, owner_user_id=user.id)
    session.add(tenant)
    session.flush()
    session.add(TenantMember(tenant_id=tenant.id, user_id=user.id, role="OWNER"))
    session.add(Onboarding(tenant_id=tenant.id, user_id=user.id, step=1))
    end = now() + settings.trial_days * 86400
    session.add(
        SaaSSubscription(tenant_id=tenant.id, plan_id=plan.id, trial_ends_at=end, current_period_end=end)
    )
    audit(session, tenant.id, user.id, "TENANT_CREATED", tenant.id)
    session.flush()
    return tenant


def entitlement(session, tenant_id, *, writable=True):
    tenant = session.get(Tenant, tenant_id)
    sub = session.scalar(select(SaaSSubscription).where(SaaSSubscription.tenant_id == tenant_id))
    if not tenant or not sub:
        raise DomainError("TENANT_NOT_FOUND", "Espacio no disponible.", 404)
    if writable and (
        tenant.deleted_at
        or tenant.status in {"SUSPENDED", "CANCELLED"}
        or sub.status not in {"TRIAL", "ACTIVE"}
        or sub.current_period_end <= now()
    ):
        raise DomainError("SAAS_SUSPENDED", "Renueva tu plan de plataforma para continuar.", 403)
    plan = session.get(SaaSPlan, sub.plan_id)
    return tenant, sub, plan


def feature(session, tenant_id, key):
    _, _, plan = entitlement(session, tenant_id)
    flag = session.scalar(
        select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id, FeatureFlag.key == key)
    )
    enabled = flag.enabled if flag else plan.features.get(key, False)
    if not enabled:
        raise DomainError("FEATURE_DISABLED", "Esta función no está habilitada en tu plan.", 403)


def reserve_limit(session, tenant_id, key, quantity=1, period="all"):
    # Serialize all reservations for one tenant; no check-then-insert race.
    session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    _, _, plan = entitlement(session, tenant_id)
    counter = session.scalar(
        select(UsageCounter).where(
            UsageCounter.tenant_id == tenant_id, UsageCounter.key == key, UsageCounter.period == period
        )
    )
    if not counter:
        counter = UsageCounter(tenant_id=tenant_id, key=key, period=period, value=0)
        session.add(counter)
    if counter.value + quantity > plan.limits.get(key, 0):
        raise DomainError("PLAN_LIMIT", f"Alcanzaste el límite de {key} de tu plan.", 409)
    counter.value += quantity
    session.flush()


def check_entity_limit(session, tenant_id, key, model):
    session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    _, _, plan = entitlement(session, tenant_id)
    count = session.scalar(select(func.count()).select_from(model).where(model.tenant_id == tenant_id))
    if count >= plan.limits.get(key, 0):
        raise DomainError("PLAN_LIMIT", f"Alcanzaste el límite de {key}.", 409)


def suspend_due(session):
    rows = session.scalars(
        select(SaaSSubscription)
        .where(
            SaaSSubscription.current_period_end <= now(),
            SaaSSubscription.status.in_(["TRIAL", "ACTIVE", "PAST_DUE"]),
        )
        .with_for_update(skip_locked=True)
        .limit(100)
    )
    for sub in rows:
        sub.status = "SUSPENDED"
        tenant = session.get(Tenant, sub.tenant_id)
        tenant.status, tenant.suspended_at = "SUSPENDED", now()
        audit(session, sub.tenant_id, "system", "SAAS_SUSPENDED", sub.id)
