"""Thirty-day platform billing with immutable sale rates and explicit USD conversion.

Amounts are integer minor units. Commissions round once per invoice, not once per
sale. A missing FX quote blocks invoice finalization; it never invents revenue.
Plan changes take effect at the next cycle. Refunds retain the original rate.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import select, exists, func, case
from .. import models as m
from ..errors import DomainError
from ..security import digest
from .common import audit, send, enqueue

MONTH = 30 * 86400
TERMS = {"STARTER": (0, 800), "PRO": (3000, 400), "AGENCY": (8000, 100)}


def minor(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def setting(db, key):
    row = db.scalar(select(m.PlatformSetting).where(m.PlatformSetting.key == key))
    return dict(row.value) if row else {}


def set_setting(db, key, value, actor):
    row = db.scalar(select(m.PlatformSetting).where(m.PlatformSetting.key == key).with_for_update())
    before = dict(row.value) if row else {}
    if not row:
        row = m.PlatformSetting(key=key)
        db.add(row)
    row.value = value
    audit(db, None, actor, "PLATFORM_SETTING_CHANGED", key, {"before": before, "after": value})


def set_rate(db, currency, usd_minor_per_unit, actor):
    currency = currency.upper()
    if currency == "USD" or not currency.isalpha() or not 3 <= len(currency) <= 8:
        raise DomainError("INVALID_CURRENCY", "Selecciona una moneda distinta de USD.")
    try:
        rate = Decimal(str(usd_minor_per_unit))
        if not rate.is_finite() or not Decimal("0") < rate <= Decimal("1000000000"):
            raise ValueError()
    except (ValueError, InvalidOperation):
        raise DomainError("INVALID_RATE", "Indica una conversión positiva y finita.") from None
    set_setting(
        db, "fx:" + currency, {"rate": str(rate), "as_of": m.now(), "source": f"owner:{actor}"}, actor
    )


def usd_rate(db, currency):
    if currency == "USD":
        return "1", "USD minor units"
    value = setting(db, "fx:" + currency)
    return value.get("rate"), value.get("source", "")


def trial_remaining(sub, timestamp=None):
    seconds = max(0, sub.trial_ends_at - (timestamp or m.now())) if sub.status == "TRIAL" else 0
    return {"seconds": seconds, "days": seconds // 86400, "hours": (seconds % 86400) // 3600}


def usage_snapshot(db, tenant_id):
    from datetime import datetime, timezone

    tenant = db.get(m.Tenant, tenant_id)
    sub = db.scalar(select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == tenant_id))
    plan = db.get(m.SaaSPlan, sub.plan_id)
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    usage = dict(
        db.execute(
            select(m.UsageCounter.key, m.UsageCounter.value).where(
                m.UsageCounter.tenant_id == tenant_id, m.UsageCounter.period == period
            )
        ).all()
    )
    return {
        "measured_at": m.now(),
        "quota_month_utc": period,
        "limits": dict(plan.limits),
        "bots": db.scalar(
            select(func.count())
            .select_from(m.ManagedBot)
            .where(
                m.ManagedBot.tenant_id == tenant_id,
                m.ManagedBot.status.not_in(["DISCONNECTED", "OWNERSHIP_CHANGED"]),
            )
        ),
        "contacts": db.scalar(
            select(func.count()).select_from(m.Contact).where(m.Contact.tenant_id == tenant_id)
        ),
        "admins": 1
        + (
            db.scalar(
                select(func.count(func.distinct(m.BotAdmin.user_id))).where(
                    m.BotAdmin.tenant_id == tenant_id,
                    m.BotAdmin.active.is_(True),
                    m.BotAdmin.user_id != tenant.owner_user_id,
                )
            )
            or 0
        ),
        "campaigns": usage.get("campaigns_month", 0),
        "exports": usage.get("exports_month", 0),
    }


class PlatformLedger:
    def __init__(self, runtime):
        self.r = runtime

    def activate_trial(self, db, tenant, actor):
        if tenant.owner_user_id != actor.id:
            raise DomainError("OWNER_REQUIRED", "Solo el propietario puede activar la prueba.", 403)
        user = db.scalar(select(m.PlatformUser).where(m.PlatformUser.id == actor.id).with_for_update())
        sub = db.scalar(
            select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == tenant.id).with_for_update()
        )
        if sub.trial_starts_at:
            return sub
        if sub.cycle_started_at or sub.status != "PAYMENT_PENDING":
            raise DomainError(
                "TRIAL_UNAVAILABLE", "La prueba se activa antes del primer ciclo comercial.", 409
            )
        if user.trial_used_at:
            raise DomainError(
                "TRIAL_ALREADY_USED", "Ya utilizaste tu prueba gratuita. Selecciona un plan.", 409
            )
        start = m.now()
        user.trial_used_at = sub.trial_starts_at = start
        sub.trial_ends_at = sub.current_period_end = start + 3 * 86400
        sub.status, tenant.status = "TRIAL", "TRIAL"
        audit(
            db,
            tenant.id,
            actor.id,
            "TRIAL_ACTIVATED",
            sub.id,
            {"starts_at": start, "ends_at": sub.trial_ends_at},
        )
        return sub

    def select_plan(self, db, tenant_id, plan_id, actor):
        tenant = db.scalar(select(m.Tenant).where(m.Tenant.id == tenant_id).with_for_update())
        if not tenant or tenant.owner_user_id != actor.id:
            raise DomainError("OWNER_REQUIRED", "Solo el propietario puede cambiar el plan SaaS.", 403)
        if tenant.admin_suspended_at:
            raise DomainError(
                "ADMIN_SUSPENDED", "La plataforma suspendió este negocio. Contacta soporte.", 403
            )
        plan = db.get(m.SaaSPlan, plan_id)
        if not plan or not plan.active:
            raise DomainError("PLAN_UNAVAILABLE", "Plan de plataforma no disponible.", 404)
        sub = db.scalar(
            select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == tenant_id).with_for_update()
        )
        self.advance(db, sub)
        if sub.cycle_started_at and sub.current_period_end > m.now() and sub.status != "CANCELLED":
            sub.pending_plan_id = plan.id
            audit(
                db,
                tenant_id,
                actor.id,
                "SAAS_PLAN_CHANGE_SCHEDULED",
                sub.id,
                {"from": sub.plan_id, "to": plan.id, "effective_at": sub.current_period_end},
            )
            return {"effective_at": sub.current_period_end, "scheduled": True}
        if self.balance(db, tenant_id) > 0 or self.awaiting_rate(db, tenant_id):
            raise DomainError(
                "INVOICE_OUTSTANDING", "Revisa y paga las facturas pendientes antes de reactivar.", 409
            )
        sub.plan_id, sub.pending_plan_id, sub.cancelled_at = plan.id, None, None
        sub.grace_days = setting(db, "billing_policy").get("grace_days", self.r.settings.billing_grace_days)
        self.open_cycle(db, sub, m.now())
        sub.status, tenant.status, tenant.suspended_at = "ACTIVE", "ACTIVE", None
        audit(
            db,
            tenant_id,
            actor.id,
            "SAAS_PLAN_ACTIVATED",
            sub.id,
            {
                "plan_id": plan.id,
                "fixed_usd_minor": plan.fixed_usd_minor,
                "commission_bps": plan.commission_bps,
            },
        )
        return {"effective_at": sub.cycle_started_at, "scheduled": False}

    def open_cycle(self, db, sub, start):
        previous = db.scalar(
            select(m.BillingCycle).where(
                m.BillingCycle.subscription_id == sub.id, m.BillingCycle.starts_at == start
            )
        )
        if previous:
            return previous
        plan = db.get(m.SaaSPlan, sub.plan_id)
        sub.grace_days = setting(db, "billing_policy").get("grace_days", sub.grace_days)
        cycle = m.BillingCycle(
            id=m.uid(),
            tenant_id=sub.tenant_id,
            subscription_id=sub.id,
            plan_id=plan.id,
            plan_name=plan.name,
            fixed_usd_minor=plan.fixed_usd_minor,
            commission_bps=plan.commission_bps,
            starts_at=start,
            ends_at=start + MONTH,
            due_at=start + MONTH + sub.grace_days * 86400,
        )
        db.add(cycle)
        sub.cycle_started_at, sub.current_period_end = start, cycle.ends_at
        db.flush()
        return cycle

    @staticmethod
    def awaiting_rate(db, tenant_id):
        return bool(
            db.scalar(
                select(m.PlatformInvoice.id)
                .where(m.PlatformInvoice.tenant_id == tenant_id, m.PlatformInvoice.status == "NEEDS_RATE")
                .limit(1)
            )
        )

    def grant_access(self, db, tenant, days, actor):
        """Explicit owner concession: no fabricated settlement or reset of trial usage."""
        if type(days) is not int or not 1 <= days <= 365:
            raise DomainError("INVALID_DAYS", "Indica entre 1 y 365 días.")
        sub = db.scalar(
            select(m.SaaSSubscription).where(m.SaaSSubscription.tenant_id == tenant.id).with_for_update()
        )
        if self.balance(db, tenant.id) or self.awaiting_rate(db, tenant.id):
            raise DomainError(
                "INVOICE_OUTSTANDING", "Resuelve las facturas pendientes antes de conceder acceso.", 409
            )
        previous = sub.current_period_end
        cycle = (
            db.scalar(
                select(m.BillingCycle)
                .where(
                    m.BillingCycle.subscription_id == sub.id, m.BillingCycle.starts_at == sub.cycle_started_at
                )
                .with_for_update()
            )
            if sub.cycle_started_at
            else None
        )
        if cycle and cycle.ends_at > m.now() and cycle.status == "OPEN":
            cycle.ends_at += days * 86400
            cycle.due_at += days * 86400
            sub.current_period_end = cycle.ends_at
            sub.status = "ACTIVE"
        elif not cycle:
            sub.current_period_end = max(m.now(), sub.current_period_end) + days * 86400
            if sub.status == "TRIAL":
                sub.trial_ends_at = sub.current_period_end
            else:
                sub.status = "ACTIVE"
        else:
            self.finalize(db, cycle)
            if self.balance(db, tenant.id) or self.awaiting_rate(db, tenant.id):
                raise DomainError(
                    "INVOICE_OUTSTANDING",
                    "Resuelve la factura del ciclo finalizado antes de conceder acceso.",
                    409,
                )
            cycle = self.open_cycle(db, sub, m.now())
            cycle.fixed_usd_minor = 0
            cycle.ends_at = sub.current_period_end = cycle.starts_at + days * 86400
            cycle.due_at = cycle.ends_at + sub.grace_days * 86400
            sub.status = "ACTIVE"
        sub.cancelled_at = None
        tenant.status, tenant.suspended_at, tenant.admin_suspended_at = sub.status, None, None
        audit(
            db,
            tenant.id,
            actor,
            "SAAS_COMPLIMENTARY_EXTENSION",
            sub.id,
            {
                "days": days,
                "previous_end": previous,
                "ends_at": sub.current_period_end,
                "cycle_id": cycle.id if cycle else None,
                "commission_unchanged": True,
            },
        )

    def sale(self, db, charge):
        entry_key = "sale:" + charge.id
        if db.scalar(
            select(m.CommissionEntry.id).where(
                m.CommissionEntry.tenant_id == charge.tenant_id, m.CommissionEntry.entry_key == entry_key
            )
        ):
            return
        sub = db.scalar(
            select(m.SaaSSubscription)
            .where(m.SaaSSubscription.tenant_id == charge.tenant_id)
            .with_for_update()
        )
        timestamp = charge.created_at or m.now()
        cycle = db.scalar(
            select(m.BillingCycle).where(
                m.BillingCycle.tenant_id == charge.tenant_id,
                m.BillingCycle.starts_at <= timestamp,
                m.BillingCycle.ends_at > timestamp,
            )
        )
        if not cycle and sub.cycle_started_at and sub.current_period_end <= timestamp:
            self.advance(db, sub, timestamp)
            cycle = db.scalar(
                select(m.BillingCycle).where(
                    m.BillingCycle.tenant_id == charge.tenant_id,
                    m.BillingCycle.starts_at <= timestamp,
                    m.BillingCycle.ends_at > timestamp,
                )
            )
        rate, source = usd_rate(db, charge.currency)
        db.add(
            m.CommissionEntry(
                tenant_id=charge.tenant_id,
                cycle_id=cycle.id if cycle else None,
                charge_id=charge.id,
                entry_key=entry_key,
                currency=charge.currency,
                gross_minor=charge.amount_minor,
                commission_bps=cycle.commission_bps if cycle else 0,
                usd_rate=rate,
                rate_source=source,
                entry_type="SALE" if cycle else "TRIAL_OR_LEGACY",
            )
        )

    def refund(self, db, charge, amount=None, key=None):
        entry_key = "refund:" + (key or charge.id)
        amount = charge.amount_minor if amount is None else amount
        original = db.scalar(
            select(m.CommissionEntry).where(
                m.CommissionEntry.tenant_id == charge.tenant_id,
                m.CommissionEntry.entry_key == "sale:" + charge.id,
            )
        )
        if not original or db.scalar(
            select(m.CommissionEntry.id).where(
                m.CommissionEntry.tenant_id == charge.tenant_id, m.CommissionEntry.entry_key == entry_key
            )
        ):
            return
        original_cycle = db.get(m.BillingCycle, original.cycle_id) if original.cycle_id else None
        cycle = original_cycle
        if original_cycle and original_cycle.status != "OPEN":
            cycle = db.scalar(
                select(m.BillingCycle)
                .where(m.BillingCycle.tenant_id == charge.tenant_id, m.BillingCycle.status == "OPEN")
                .order_by(m.BillingCycle.starts_at.desc())
            )
        db.add(
            m.CommissionEntry(
                tenant_id=charge.tenant_id,
                cycle_id=cycle.id if cycle else original.cycle_id,
                charge_id=charge.id,
                entry_key=entry_key,
                currency=charge.currency,
                gross_minor=-amount,
                commission_bps=original.commission_bps,
                usd_rate=original.usd_rate,
                rate_source=original.rate_source,
                entry_type="REFUND",
            )
        )
        # A cancelled account with a finalized invoice receives an auditable credit.
        if original_cycle and cycle is None:
            invoice = db.scalar(
                select(m.PlatformInvoice).where(m.PlatformInvoice.cycle_id == original_cycle.id)
            )
            if invoice and original.usd_rate:
                previous_refunds = -(
                    db.scalar(
                        select(func.sum(m.CommissionEntry.gross_minor)).where(
                            m.CommissionEntry.charge_id == charge.id,
                            m.CommissionEntry.entry_type == "REFUND",
                            m.CommissionEntry.entry_key != entry_key,
                        )
                    )
                    or 0
                )
                rate = Decimal(original.usd_rate) * original.commission_bps / 10000
                value = -(
                    minor(Decimal(previous_refunds + amount) * rate) - minor(Decimal(previous_refunds) * rate)
                )
                self.adjust(
                    db,
                    invoice,
                    value,
                    "Reembolso del cargo " + charge.id,
                    "system",
                    "refund-credit:" + (key or charge.id),
                )

    def breakdown(self, db, cycle):
        groups, total, missing = {}, Decimal(0), set()
        rows = db.execute(
            select(
                m.CommissionEntry.currency,
                m.CommissionEntry.commission_bps,
                m.CommissionEntry.usd_rate,
                func.sum(m.CommissionEntry.gross_minor).label("gross"),
                func.count().label("count"),
                func.sum(case((m.CommissionEntry.gross_minor > 0, m.CommissionEntry.gross_minor), else_=0)),
                func.sum(case((m.CommissionEntry.gross_minor < 0, -m.CommissionEntry.gross_minor), else_=0)),
            )
            .where(m.CommissionEntry.tenant_id == cycle.tenant_id, m.CommissionEntry.cycle_id == cycle.id)
            .group_by(
                m.CommissionEntry.currency, m.CommissionEntry.commission_bps, m.CommissionEntry.usd_rate
            )
        )
        for currency, bps, rate, gross, count, sales, refunds in rows:
            bucket = groups.setdefault(
                currency,
                {
                    "gross_minor": 0,
                    "sales_minor": 0,
                    "refunds_minor": 0,
                    "commission_numerator": 0,
                    "entries": 0,
                },
            )
            bucket["gross_minor"] += gross
            bucket["sales_minor"] += sales
            bucket["refunds_minor"] += refunds
            bucket["commission_numerator"] += gross * bps
            bucket["entries"] += count
            if bps and rate is None:
                missing.add(currency)
            elif rate:
                total += Decimal(gross) * Decimal(rate) * bps / 10000
        return {
            "currencies": groups,
            "commission_denominator": 10000,
            "missing_rates": sorted(missing),
            "commission_usd_minor": None if missing else minor(total),
        }

    def finalize(self, db, cycle):
        invoice = db.scalar(
            select(m.PlatformInvoice).where(m.PlatformInvoice.cycle_id == cycle.id).with_for_update()
        )
        if invoice and invoice.status != "NEEDS_RATE":
            return invoice
        data = self.breakdown(db, cycle)
        data["usage"] = (
            invoice.breakdown.get("usage")
            if invoice and invoice.breakdown.get("usage")
            else usage_snapshot(db, cycle.tenant_id)
        )
        data.update(
            starts_at=cycle.starts_at,
            ends_at=cycle.ends_at,
            commission_bps=cycle.commission_bps,
            plan_name=cycle.plan_name,
        )
        if not invoice:
            invoice = m.PlatformInvoice(
                id=m.uid(),
                tenant_id=cycle.tenant_id,
                cycle_id=cycle.id,
                number="SaaS-" + cycle.id,
                fixed_minor=cycle.fixed_usd_minor,
                due_at=cycle.due_at,
            )
            db.add(invoice)
        was_waiting = invoice.status == "NEEDS_RATE"
        invoice.breakdown, invoice.commission_minor = data, data["commission_usd_minor"]
        invoice.status = "NEEDS_RATE" if data["missing_rates"] else "PAYMENT_PENDING"
        cycle.status = "NEEDS_RATE" if data["missing_rates"] else "INVOICED"
        if was_waiting and not data["missing_rates"]:
            sub = db.get(m.SaaSSubscription, cycle.subscription_id)
            invoice.due_at = max(invoice.due_at, m.now() + sub.grace_days * 86400)
        if invoice.commission_minor is not None and self.outstanding(invoice) == 0:
            invoice.status, cycle.status = "PAID", "PAID"
        db.flush()
        audit(
            db,
            cycle.tenant_id,
            "system",
            "SAAS_INVOICE_GENERATED",
            invoice.id,
            {"cycle": cycle.id, "status": invoice.status},
        )
        from .console_saas import invoice_summary

        user = db.get(m.PlatformUser, db.get(m.Tenant, cycle.tenant_id).owner_user_id)
        self.notify(
            db,
            cycle.tenant_id,
            invoice_summary(invoice, user.locale),
            "invoice:" + invoice.id + ":" + invoice.status,
        )
        return invoice

    def advance(self, db, sub, timestamp=None):
        timestamp = timestamp or m.now()
        # Bound catch-up; a suspended/cancelled service must not accrue unlimited fixed fees.
        if not sub.cycle_started_at:
            if sub.cancelled_at and sub.current_period_end <= timestamp:
                sub.status = db.get(m.Tenant, sub.tenant_id).status = "CANCELLED"
            return
        cycle = db.scalar(
            select(m.BillingCycle)
            .where(m.BillingCycle.subscription_id == sub.id, m.BillingCycle.starts_at == sub.cycle_started_at)
            .with_for_update()
        )
        if not cycle or cycle.ends_at > timestamp:
            return
        self.finalize(db, cycle)
        tenant = db.get(m.Tenant, sub.tenant_id)
        if sub.cancelled_at:
            was_cancelled = sub.status == "CANCELLED"
            sub.status, tenant.status = "CANCELLED", "CANCELLED"
            if not was_cancelled:
                audit(db, sub.tenant_id, "system", "SAAS_CANCELLED", sub.id)
            return
        overdue = list(
            db.scalars(
                select(m.PlatformInvoice).where(
                    m.PlatformInvoice.tenant_id == sub.tenant_id,
                    m.PlatformInvoice.status.in_(["PAYMENT_PENDING", "OVERDUE"]),
                    m.PlatformInvoice.due_at < timestamp,
                )
            )
        )
        if any(self.outstanding(invoice) for invoice in overdue):
            sub.status, tenant.status, tenant.suspended_at = "SUSPENDED", "SUSPENDED", timestamp
            for invoice in overdue:
                invoice.status = "OVERDUE"
            return
        if sub.status not in {"SUSPENDED", "CANCELLED"} and not tenant.admin_suspended_at:
            if sub.pending_plan_id:
                sub.plan_id, sub.pending_plan_id = sub.pending_plan_id, None
            # After prolonged inactivity with no debt, resume at the current time instead
            # of inventing months of service that were never processed.
            self.open_cycle(db, sub, cycle.ends_at if timestamp < cycle.ends_at + MONTH else timestamp)

    @staticmethod
    def outstanding(invoice):
        if invoice.commission_minor is None:
            return 0
        return max(
            0,
            invoice.fixed_minor
            + invoice.commission_minor
            + (invoice.adjustment_minor or 0)
            - (invoice.paid_minor or 0),
        )

    def balance(self, db, tenant_id):
        return sum(
            self.outstanding(x)
            for x in db.scalars(
                select(m.PlatformInvoice).where(
                    m.PlatformInvoice.tenant_id == tenant_id, m.PlatformInvoice.status != "NEEDS_RATE"
                )
            )
        )

    def submit(self, db, invoice, actor, method, reference, amount_usd_minor, evidence=None, data=None):
        if db.get(m.Tenant, invoice.tenant_id).owner_user_id != actor.id:
            raise DomainError(
                "OWNER_REQUIRED", "Solo el titular puede presentar el pago de esta factura.", 403
            )
        if method not in {"BANK_TRANSFER", "CRYPTO"} or not reference.strip() or len(reference) > 240:
            raise DomainError("INVALID_SETTLEMENT", "Indica método y referencia de pago válidos.")
        if (
            type(amount_usd_minor) is not int
            or amount_usd_minor <= 0
            or invoice.status in {"PAID", "NEEDS_RATE"}
        ):
            raise DomainError("INVALID_AMOUNT", "Revisa el importe y el estado de la factura.")
        network = (evidence or {}).get("network", "").strip().lower()
        reference_key = digest(method + ":" + network + ":" + reference.strip().lower())
        previous = db.scalar(
            select(m.PlatformSettlement).where(m.PlatformSettlement.reference_hash == reference_key)
        )
        if previous:
            if previous.invoice_id != invoice.id or previous.tenant_id != invoice.tenant_id:
                raise DomainError("REFERENCE_USED", "Esta referencia ya está registrada.", 409)
            return previous
        row = m.PlatformSettlement(
            id=m.uid(),
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            method=method,
            reference_hash=reference_key,
            reference=reference.strip(),
            amount_usd_minor=amount_usd_minor,
            evidence=evidence or {},
            submitted_by=actor.id,
        )
        if data:
            from ..security import inspect_receipt
            import base64

            file = inspect_receipt(data, self.r.settings.max_upload_bytes)
            row.receipt_ciphertext = self.r.vault.encrypt(
                base64.b64encode(file["bytes"]).decode(), f"{invoice.tenant_id}:{row.id}:platform-receipt"
            )
            row.media_type = file["media_type"]
        db.add(row)
        audit(
            db,
            invoice.tenant_id,
            actor.id,
            "SAAS_PAYMENT_SUBMITTED",
            row.id,
            {"method": method, "invoice_id": invoice.id},
        )
        for owner_id in self.r.settings.owner_ids:
            from .i18n import t

            owner = db.scalar(select(m.PlatformUser).where(m.PlatformUser.telegram_user_id == owner_id))
            send(
                db,
                None,
                owner_id,
                t("settlement_pending_notice", owner.locale if owner else "es"),
                "platform-payment:" + row.id + ":" + str(owner_id),
            )
        return row

    def review(self, db, settlement, actor, approve, note=""):
        row = db.scalar(
            select(m.PlatformSettlement).where(m.PlatformSettlement.id == settlement.id).with_for_update()
        )
        if row.status != "PENDING":
            return row
        invoice = db.scalar(
            select(m.PlatformInvoice).where(m.PlatformInvoice.id == row.invoice_id).with_for_update()
        )
        if approve and invoice.commission_minor is None:
            raise DomainError("INVOICE_NOT_READY", "Completa primero la conversión de la factura.")
        if approve and row.amount_usd_minor > self.outstanding(invoice):
            raise DomainError(
                "EXCESS_PAYMENT", "El importe supera el saldo. Registra el ajuste antes de aprobar."
            )
        row.status, row.reviewed_by, row.reviewed_at, row.note = (
            "APPROVED" if approve else "REJECTED",
            actor,
            m.now(),
            note[:500],
        )
        if approve:
            invoice.paid_minor += row.amount_usd_minor
            if self.outstanding(invoice) == 0:
                invoice.status = "PAID"
                db.get(m.BillingCycle, invoice.cycle_id).status = "PAID"
            if self.balance(db, row.tenant_id) == 0 and not self.awaiting_rate(db, row.tenant_id):
                tenant = db.get(m.Tenant, row.tenant_id)
                sub = db.scalar(
                    select(m.SaaSSubscription)
                    .where(m.SaaSSubscription.tenant_id == row.tenant_id)
                    .with_for_update()
                )
                if sub.status != "CANCELLED" and not sub.cancelled_at and not tenant.admin_suspended_at:
                    tenant.status, sub.status, tenant.suspended_at = "ACTIVE", "ACTIVE", None
                    if sub.current_period_end <= m.now():
                        self.open_cycle(db, sub, m.now())
        audit(
            db,
            row.tenant_id,
            actor,
            "SAAS_PAYMENT_" + row.status,
            row.id,
            {"invoice_id": invoice.id, "amount_usd_minor": row.amount_usd_minor},
        )
        self.notify(
            db,
            row.tenant_id,
            {"key": "settlement_approved_notice"}
            if approve
            else {"key": "settlement_rejected_notice", "values": {"note": note[:500]}},
            "settlement-reviewed:" + row.id,
        )
        return row

    def adjust(self, db, invoice, amount, reason, actor, key):
        if not reason.strip() or type(amount) is not int:
            raise DomainError("ADJUSTMENT_REASON", "Indica el importe y el motivo del ajuste.")
        invoice = db.scalar(
            select(m.PlatformInvoice).where(m.PlatformInvoice.id == invoice.id).with_for_update()
        )
        existing = db.scalar(
            select(m.InvoiceAdjustment).where(
                m.InvoiceAdjustment.tenant_id == invoice.tenant_id, m.InvoiceAdjustment.operation_key == key
            )
        )
        if existing:
            return existing
        row = m.InvoiceAdjustment(
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            amount_minor=amount,
            reason=reason[:500],
            actor_id=actor,
            operation_key=key,
        )
        db.add(row)
        invoice.adjustment_minor = (invoice.adjustment_minor or 0) + amount
        if invoice.commission_minor is not None and self.outstanding(invoice) == 0:
            invoice.status = "PAID"
        audit(
            db,
            invoice.tenant_id,
            actor,
            "SAAS_INVOICE_ADJUSTED",
            invoice.id,
            {"amount_minor": amount, "reason": reason},
        )
        return row

    def resolve_rates(self, db, cycle, actor):
        for entry in db.scalars(
            select(m.CommissionEntry).where(
                m.CommissionEntry.cycle_id == cycle.id, m.CommissionEntry.usd_rate.is_(None)
            )
        ):
            rate, source = usd_rate(db, entry.currency)
            if rate:
                entry.usd_rate, entry.rate_source = rate, source
                audit(
                    db,
                    entry.tenant_id,
                    actor,
                    "COMMISSION_RATE_RESOLVED",
                    entry.id,
                    {"rate": rate, "source": source},
                )
        db.flush()
        return self.finalize(db, cycle)

    def notify(self, db, tenant_id, text, key):
        from .i18n import message

        tenant = db.get(m.Tenant, tenant_id)
        user = db.get(m.PlatformUser, tenant.owner_user_id)
        send(db, None, user.telegram_user_id, message(text, user.locale), key)

    def tick(self, db, after=None, batch=None):
        timestamp = m.now()
        batch = timestamp // 60 if batch is None else batch
        query = select(m.SaaSSubscription).where(
            m.SaaSSubscription.status != "CANCELLED",
            (m.SaaSSubscription.status != "SUSPENDED")
            | exists(
                select(m.BillingCycle.id).where(
                    m.BillingCycle.subscription_id == m.SaaSSubscription.id, m.BillingCycle.status == "OPEN"
                )
            ),
        )
        if after:
            query = query.where(m.SaaSSubscription.id > after)
        rows = list(
            db.scalars(query.order_by(m.SaaSSubscription.id).with_for_update(skip_locked=True).limit(100))
        )
        if len(rows) == 100:
            enqueue(
                db,
                "BILLING_TICK",
                None,
                {"after": rows[-1].id, "batch": batch},
                f"billing-tick:{batch}:{rows[-1].id}",
            )
        for sub in rows:
            tenant = db.get(m.Tenant, sub.tenant_id)
            if sub.cancelled_at and not sub.cycle_started_at and sub.current_period_end <= timestamp:
                sub.status = tenant.status = "CANCELLED"
                audit(db, sub.tenant_id, "system", "SAAS_CANCELLED", sub.id)
                continue
            if sub.status == "TRIAL":
                left = sub.trial_ends_at - timestamp
                if left <= 0:
                    sub.status, tenant.status = "PAYMENT_PENDING", "PAYMENT_PENDING"
                    self.notify(db, sub.tenant_id, {"key": "trial_ended_notice"}, f"trial-ended:{sub.id}")
                    audit(db, sub.tenant_id, "system", "TRIAL_EXPIRED", sub.id)
                else:
                    for hours in (24, 3):
                        if left <= hours * 3600:
                            self.notify(
                                db,
                                sub.tenant_id,
                                {"key": "trial_reminder_notice", "values": {"hours": hours}},
                                f"trial-reminder:{sub.id}:{hours}",
                            )
                continue
            self.advance(db, sub, timestamp)
            if sub.cycle_started_at and 0 < sub.current_period_end - timestamp <= 86400:
                self.notify(
                    db,
                    sub.tenant_id,
                    {"key": "cycle_reminder_notice"},
                    f"cycle-reminder:{sub.id}:{sub.current_period_end}",
                )
            invoices = list(
                db.scalars(
                    select(m.PlatformInvoice).where(
                        m.PlatformInvoice.tenant_id == sub.tenant_id,
                        m.PlatformInvoice.status.in_(["PAYMENT_PENDING", "OVERDUE"]),
                    )
                )
            )
            debt = [invoice for invoice in invoices if self.outstanding(invoice) > 0]
            if not debt:
                continue
            earliest = min(x.due_at for x in debt)
            if timestamp >= earliest:
                already_suspended = sub.status == "SUSPENDED"
                sub.status, tenant.status, tenant.suspended_at = "SUSPENDED", "SUSPENDED", timestamp
                for invoice in debt:
                    if invoice.due_at < timestamp:
                        invoice.status = "OVERDUE"
                self.notify(
                    db,
                    sub.tenant_id,
                    {"key": "invoice_overdue_notice"},
                    f"saas-overdue:{min(x.id for x in debt)}",
                )
                if not already_suspended:
                    audit(db, sub.tenant_id, "system", "SAAS_SUSPENDED", sub.id, {"reason": "unpaid_invoice"})
            else:
                sub.status = "PAYMENT_PENDING"
                self.notify(
                    db,
                    sub.tenant_id,
                    {"key": "invoice_pending_notice"},
                    f"saas-pending:{min(x.id for x in debt)}:{'last-day' if earliest - timestamp <= 86400 else 'open'}",
                )
