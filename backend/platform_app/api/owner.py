from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from .. import models as m
from ..errors import DomainError
from ..services.common import audit
from .auth import runtime, platform_owner
from .serialization import public
from . import schemas as s

router = APIRouter(prefix="/api/owner")


@router.get("/health")
def health(auth=Depends(platform_owner), r=Depends(runtime)):
    with r.db.system() as db:
        audit(db, None, auth.user_id, "PLATFORM_HEALTH_VIEWED")
        return {
            "tenants": db.scalar(select(func.count()).select_from(m.Tenant)),
            "bots": db.scalar(select(func.count()).select_from(m.ManagedBot)),
            "queue": dict(db.execute(select(m.Job.status, func.count()).group_by(m.Job.status)).all()),
            "trials": db.scalar(
                select(func.count())
                .select_from(m.SaaSSubscription)
                .where(m.SaaSSubscription.status == "TRIAL")
            ),
            "revenue_30d_xtr": str(
                db.scalar(
                    select(func.sum(m.SaaSCharge.amount_xtr)).where(
                        m.SaaSCharge.created_at >= m.now() - 30 * 86400
                    )
                )
                or 0
            ),
            "encryption_configured": r.vault is not None,
            "master_configured": bool(r.settings.master_bot_token.get_secret_value()),
        }


@router.get("/master/capabilities")
def capabilities(auth=Depends(platform_owner), r=Depends(runtime)):
    return r.manager.capabilities()


@router.post("/master/configure")
def configure_master(auth=Depends(platform_owner), r=Depends(runtime)):
    result = r.manager.configure_master()
    with r.db.system() as db:
        audit(db, None, auth.user_id, "MASTER_CONFIGURED")
    return result


@router.get("/resources/{resource}")
def resources(
    resource: str,
    auth=Depends(platform_owner),
    r=Depends(runtime),
    limit: int = Query(50, ge=1, le=100),
    after: str | None = None,
):
    model = {
        "tenants": m.Tenant,
        "bots": m.ManagedBot,
        "jobs": m.Job,
        "audit": m.AuditLog,
        "support": m.PlatformSupportTicket,
        "saas-plans": m.SaaSPlan,
    }.get(resource)
    if not model:
        raise DomainError("NOT_FOUND", "Lista no disponible.", 404)
    with r.db.system() as db:
        query = select(model)
        if after:
            query = query.where(model.id > after)
        rows = list(db.scalars(query.order_by(model.id).limit(limit + 1)))
        audit(db, None, auth.user_id, "PLATFORM_RESOURCE_VIEWED", data={"resource": resource})
        return {
            "items": [public(x) for x in rows[:limit]],
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
        }


@router.post("/tenants/{tenant_id}/action")
def tenant_action(tenant_id: str, body: s.OwnerAction, auth=Depends(platform_owner), r=Depends(runtime)):
    with r.db.system() as db:
        tenant = db.get(m.Tenant, tenant_id)
        if not tenant:
            raise DomainError("NOT_FOUND", "Espacio no disponible.", 404)
        if body.action == "REACTIVATE":
            sub = db.scalar(select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == tenant_id))
            if sub.current_period_end <= m.now():
                raise DomainError(
                    "BILLING_EXPIRED", "Se requiere renovar o conceder un periodo de prueba auditado.", 409
                )
            tenant.status, tenant.suspended_at = "ACTIVE", None
            sub.status = "ACTIVE"
        else:
            tenant.status, tenant.suspended_at = "SUSPENDED", m.now()
        audit(db, tenant.id, auth.user_id, "TENANT_" + body.action, tenant.id, {"reason": body.reason})
        return public(tenant)


@router.put("/saas-plans/{plan_id}")
def saas_plan(plan_id: str, body: s.SaaSPlanUpdate, auth=Depends(platform_owner), r=Depends(runtime)):
    with r.db.system() as db:
        plan = db.get(m.SaaSPlan, plan_id)
        if not plan:
            raise DomainError("NOT_FOUND", "Plan no disponible.", 404)
        plan.prices = {"XTR": body.amount_xtr}
        plan.limits = {**plan.limits, **body.model_dump(exclude={"amount_xtr"})}
        audit(db, None, auth.user_id, "SAAS_PLAN_CONFIGURED", plan.id)
        return public(plan)


@router.put("/tenants/{tenant_id}/features/{key}")
def feature_flag(
    tenant_id: str, key: str, body: s.FeatureUpdate, auth=Depends(platform_owner), r=Depends(runtime)
):
    from ..services.tenants import DEFAULT_FEATURES

    if key not in DEFAULT_FEATURES:
        raise DomainError("UNKNOWN_FEATURE", "Función no válida.")
    # There is no inference provider or spending path in this release.
    if key in {"ai", "ocr", "external_payments"} and body.enabled:
        raise DomainError("ADDON_NOT_IMPLEMENTED", "Esta integración todavía no está implementada.", 409)
    with r.db.system() as db:
        if not db.get(m.Tenant, tenant_id):
            raise DomainError("NOT_FOUND", "Espacio no disponible.", 404)
        row = db.scalar(
            select(m.FeatureFlag).where(m.FeatureFlag.tenant_id == tenant_id, m.FeatureFlag.key == key)
        )
        if not row:
            row = m.FeatureFlag(tenant_id=tenant_id, key=key)
            db.add(row)
        row.enabled = body.enabled
        audit(db, tenant_id, auth.user_id, "FEATURE_CONFIGURED", data={"key": key, "enabled": body.enabled})
        return {"saved": True}
