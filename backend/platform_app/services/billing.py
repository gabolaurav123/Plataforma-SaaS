from sqlalchemy import select
from ..models import SaaSPlan, SaaSSubscription, SaaSInvoice, SaaSCharge, Tenant, uid
from ..errors import DomainError
from .common import audit


class SaaSBillingService:
    def __init__(self, runtime):
        self.r = runtime

    def checkout(self, session, tenant_id, user, plan_id):
        plan = session.get(SaaSPlan, plan_id)
        price = plan.prices.get("XTR") if plan and plan.active else None
        if type(price) is not int or not 1 <= price <= 10000:
            raise DomainError(
                "SAAS_PRICE_NOT_CONFIGURED",
                "El propietario de la plataforma debe configurar el precio en Stars.",
                409,
            )
        invoice = SaaSInvoice(
            id=uid(),
            tenant_id=tenant_id,
            invoice_payload=f"saas:{uid()}",
            plan_id=plan.id,
            telegram_user_id=user.telegram_user_id,
            amount_xtr=price,
        )
        session.add(invoice)
        invoice.checkout_url = self.r.clients.master().call(
            "createInvoiceLink",
            title=plan.name,
            description=f"Plan de plataforma {plan.name}",
            payload=invoice.invoice_payload,
            provider_token="",
            currency="XTR",
            prices=[{"label": plan.name, "amount": price}],
            subscription_period=2592000,
        )
        return invoice

    def precheckout(self, session, query):
        invoice = session.scalar(
            select(SaaSInvoice).where(SaaSInvoice.invoice_payload == query["invoice_payload"])
        )
        return bool(
            invoice
            and query["currency"] == "XTR"
            and query["total_amount"] == invoice.amount_xtr
            and query["from"]["id"] == invoice.telegram_user_id
        )

    def confirm(self, session, user_id, event):
        invoice = session.scalar(
            select(SaaSInvoice)
            .where(SaaSInvoice.invoice_payload == event["invoice_payload"])
            .with_for_update()
        )
        if (
            not invoice
            or invoice.telegram_user_id != user_id
            or event["currency"] != "XTR"
            or event["total_amount"] != invoice.amount_xtr
        ):
            raise DomainError("SAAS_PAYMENT_MISMATCH", "El pago de plataforma no coincide.", 409)
        if not event.get("is_recurring") or not isinstance(event.get("subscription_expiration_date"), int):
            raise DomainError("INVALID_SAAS_PERIOD", "Periodo de suscripción no válido.")
        charge_id = event["telegram_payment_charge_id"]
        if session.scalar(select(SaaSCharge.id).where(SaaSCharge.charge_id == charge_id)):
            return
        sub = session.scalar(
            select(SaaSSubscription).where(SaaSSubscription.tenant_id == invoice.tenant_id).with_for_update()
        )
        end = event["subscription_expiration_date"]
        session.add(
            SaaSCharge(
                tenant_id=invoice.tenant_id,
                charge_id=charge_id,
                invoice_id=invoice.id,
                amount_xtr=invoice.amount_xtr,
                period_end=end,
            )
        )
        sub.plan_id, sub.status, sub.current_period_end = (
            invoice.plan_id,
            "ACTIVE",
            max(sub.current_period_end, end),
        )
        tenant = session.get(Tenant, invoice.tenant_id)
        tenant.status, tenant.suspended_at, invoice.status = "ACTIVE", None, "PAID"
        audit(session, invoice.tenant_id, "telegram", "SAAS_PAYMENT_CONFIRMED", invoice.id)
