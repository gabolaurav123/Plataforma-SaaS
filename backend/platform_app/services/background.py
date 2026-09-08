"""Heavy native-console work, isolated from interactive updates and menu replies."""

import json
from sqlalchemy import select, func
from .. import models as m
from ..errors import DomainError, RetryLater
from .common import send, audit
from .tenants import entitlement

KINDS = {
    "DELETE_MESSAGE",
    "CHECKOUT",
    "SUBMIT_RECEIPT",
    "SUBMIT_PLATFORM_RECEIPT",
    "DELIVER_PLATFORM_RECEIPT",
    "REPORT",
    "DASHBOARD",
    "PUBLISH",
    "VERIFY_CHANNELS",
    "CANCEL_CUSTOMER_RENEWAL",
    "PROVIDER_EVENT",
    "GRANT_CHANNEL",
    "REVOKE_CHANNEL",
    "CAMPAIGN_PREVIEW",
    "SUMMARY_SCAN",
    "BUSINESS_SUMMARY",
    "BILLING_TICK",
    "EXPIRE_SUBSCRIPTIONS",
}
KINDS.add("REFUND_PAYMENT")
KINDS.add("PLATFORM_DASHBOARD")
KINDS.add("BUSINESS_NOTICE")
KINDS.add("SAAS_SUMMARY")


def admin_ui(runtime, db, bot, viewer, permission):
    from .console import Console

    ui = Console(runtime, db, bot, {"update_id": 0}, {"id": viewer})
    ui.ctx(bot.tenant_id, permission)
    ui.render_admin = True
    return ui


def process(runtime, db, job, bot):
    p = job.payload
    if job.kind == "SAAS_SUMMARY":
        from .console import Console
        from .console_saas import billing

        ui = Console(runtime, db, None, {"update_id": p["update_id"]}, {"id": p["viewer_id"]})
        ui.count = 50  # Same update stream; the immediate acknowledgement comes first.
        billing(ui, job.tenant_id, prepared=True)
    elif job.kind == "BUSINESS_NOTICE":
        from .notifications import notify

        notify(db, runtime, bot, p["category"], p["message"], job.id, p.get("permission", "read"))
    elif job.kind == "PLATFORM_DASHBOARD":
        if p["viewer_id"] not in runtime.settings.owner_ids:
            raise DomainError("OWNER_REQUIRED", "Acceso no permitido.", 403)
        from .reporting import bounds
        from .business import money

        start, end = bounds("month")

        def count(model, *filters):
            return db.scalar(select(func.count()).select_from(model).where(*filters)) or 0

        states = dict(
            db.execute(
                select(m.SaaSSubscription.status, func.count()).group_by(m.SaaSSubscription.status)
            ).all()
        )
        queue = dict(
            db.execute(
                select(m.Job.status, func.count()).where(m.Job.status != "DONE").group_by(m.Job.status)
            ).all()
        )
        receipts = (
            db.scalar(
                select(func.sum(m.PlatformSettlement.amount_usd_minor)).where(
                    m.PlatformSettlement.status == "APPROVED"
                )
            )
            or 0
        )
        fixed, commission = db.execute(
            select(
                func.sum(m.PlatformInvoice.fixed_minor), func.sum(m.PlatformInvoice.commission_minor)
            ).where(m.PlatformInvoice.commission_minor.is_not(None))
        ).one()
        pending = (
            db.scalar(
                select(
                    func.sum(
                        m.PlatformInvoice.fixed_minor
                        + m.PlatformInvoice.commission_minor
                        + m.PlatformInvoice.adjustment_minor
                        - m.PlatformInvoice.paid_minor
                    )
                ).where(m.PlatformInvoice.status.in_(["PAYMENT_PENDING", "OVERDUE"]))
            )
            or 0
        )
        from .console import Console

        ui = Console(runtime, db, None, {"update_id": 0}, {"id": p["viewer_id"]})
        text = ui.t(
            "platform_state_summary",
            tenants=count(m.Tenant),
            new=count(m.Tenant, m.Tenant.created_at >= start, m.Tenant.created_at < end),
            users=count(m.PlatformUser),
            bots=count(m.ManagedBot),
            contacts=count(m.Contact),
            states="\n".join(f"{key}: {value}" for key, value in sorted(states.items())),
        )
        text += ui.t(
            "platform_money_summary",
            receipts=money(receipts, "USD"),
            fixed=money(fixed or 0, "USD"),
            commission=money(commission or 0, "USD"),
            pending=money(pending, "USD"),
            unpriced=count(m.PlatformInvoice, m.PlatformInvoice.status == "NEEDS_RATE"),
            queue=", ".join(f"{key}: {value}" for key, value in sorted(queue.items())),
        )
        send(db, None, p["viewer_id"], text, "platform-dashboard-result:" + job.id, service_message=True)
    elif job.kind == "SUMMARY_SCAN":
        from .notifications import schedule_summaries

        schedule_summaries(db, p.get("after"), p.get("batch"))
    elif job.kind == "BUSINESS_SUMMARY":
        from .notifications import deliver_summary

        deliver_summary(db, runtime, bot, job)
    elif job.kind == "BILLING_TICK":
        runtime.ledger.tick(db, p.get("after"), p.get("batch"))
    elif job.kind == "EXPIRE_SUBSCRIPTIONS":
        runtime.payments.expire_due(db)
    elif job.kind == "REFUND_PAYMENT":
        ui = admin_ui(runtime, db, bot, p["viewer_id"], "payments")
        charge = ui.entity(m.PaymentCharge, bot.tenant_id, p["charge_id"], "payments")
        payment = db.scalar(
            select(m.Payment)
            .where(m.Payment.id == charge.payment_id, m.Payment.bot_id == bot.id)
            .with_for_update()
        )
        db.refresh(charge, with_for_update=True)
        refunded = (
            db.scalar(
                select(func.sum(m.PaymentRefund.amount_minor)).where(m.PaymentRefund.charge_id == charge.id)
            )
            or 0
        )
        remaining = charge.amount_minor - refunded
        if remaining <= 0:
            return
        provider = runtime.payments.providers[charge.provider]
        if charge.provider == "TELEGRAM_STARS":
            provider.refund(db, bot, payment, charge)
            runtime.payments.refunded_event(db, bot, {"telegram_payment_charge_id": charge.charge_id})
        elif charge.provider in {"STRIPE", "PAYPAL"}:
            result = provider.refund(db, bot, payment, charge, remaining)
            if result.get("status") in {"succeeded", "COMPLETED"}:
                from .business import amount_minor

                amount = result.get("amount")
                valid = (
                    (
                        type(amount) is int
                        and amount == remaining
                        and str(result.get("currency", "")).upper() == charge.currency
                    )
                    if charge.provider == "STRIPE"
                    else (
                        isinstance(amount, dict)
                        and amount.get("currency_code") == charge.currency
                        and amount_minor(amount.get("value", "0"), charge.currency) == remaining
                    )
                )
                if not valid:
                    raise DomainError(
                        "REFUND_MISMATCH",
                        "La confirmación del reembolso no coincide. Revisa el proveedor.",
                        409,
                    )
                from .refunds import record

                record(
                    db,
                    runtime,
                    bot,
                    charge,
                    remaining,
                    charge.provider.lower() + ":" + result["id"],
                    ui.user.id,
                    "Provider refund confirmed",
                )
        else:
            raise DomainError("MANUAL_REFUND_REQUIRED", "Registra la devolución realizada en el banco.", 409)
        audit(
            db,
            bot.tenant_id,
            ui.user.id,
            "REFUND_REQUESTED",
            payment.id,
            {"amount_minor": remaining, "provider": charge.provider},
        )
        send(
            db,
            bot,
            p["viewer_id"],
            ui.t("refund_requested_notice"),
            "refund-result:" + job.id,
            service_message=True,
            admin_permission="payments",
            viewer_id=p["viewer_id"],
        )
    elif job.kind == "DELETE_MESSAGE":
        try:
            client = runtime.clients.child(db, bot) if bot else runtime.clients.master()
            client.call("deleteMessage", chat_id=p["chat_id"], message_id=p["message_id"])
        except DomainError:
            pass  # Telegram may have already removed it or the deletion window expired.
    elif job.kind == "CAMPAIGN_PREVIEW":
        from .console_campaigns import version
        from .texts import render

        ui = admin_ui(runtime, db, bot, p["viewer_id"], "sales")
        row = ui.entity(m.Campaign, bot.tenant_id, p["campaign_id"], "sales")
        if row.status != "DRAFT" or not (row.text or row.media):
            raise DomainError("CAMPAIGN_STATE", "Añade contenido a una difusión en borrador.")
        count = runtime.campaigns.count(db, row)
        send(
            db,
            bot,
            p["viewer_id"],
            render(
                row.text,
                {
                    "name": ui.user.first_name,
                    "first_name": ui.user.first_name,
                    "username": ui.user.username or "",
                },
            ),
            "campaign-preview-media:" + job.id,
            media=row.media,
            reply_markup={"inline_keyboard": [[x] for x in row.buttons]},
            service_message=True,
            admin_permission="sales",
            viewer_id=p["viewer_id"],
        )
        send(
            db,
            bot,
            p["viewer_id"],
            ui.t("campaign_preview_notice", count=count),
            "campaign-preview-confirm:" + job.id,
            reply_markup={
                "inline_keyboard": [
                    [
                        ui.button(
                            ui.t("campaign_confirm_label"),
                            "campaign_confirm",
                            id=row.id,
                            count=count,
                            version=version(row),
                        )
                    ],
                    [ui.button(ui.t("cancel"), "__cancel")],
                ]
            },
            service_message=True,
            admin_permission="sales",
            viewer_id=p["viewer_id"],
        )
    elif job.kind == "PROVIDER_EVENT":
        event = db.scalar(
            select(m.ProviderEvent)
            .where(
                m.ProviderEvent.id == p["event_id"],
                m.ProviderEvent.tenant_id == bot.tenant_id,
                m.ProviderEvent.account_key == bot.id,
            )
            .with_for_update()
        )
        if event and event.status != "DONE":
            body = json.loads(
                runtime.vault.decrypt(
                    event.payload_ciphertext, f"{event.tenant_id}:{event.id}:provider-event"
                )
            )
            try:
                runtime.payments.providers[event.provider].handle_event(db, bot, body)
            except RetryLater as error:
                if (
                    error.code not in {"CHECKOUT_NOT_COMMITTED", "PAYMENT_NOT_COMMITTED"}
                    or m.now() - event.created_at < 900
                ):
                    raise
                event.status = "REVIEW_REQUIRED"
                audit(
                    db,
                    bot.tenant_id,
                    "system",
                    "PROVIDER_EVENT_UNMATCHED",
                    event.id,
                    {"bot_id": bot.id, "provider": event.provider, "external_id": event.external_id},
                )
                from .notifications import notify

                notify(
                    db,
                    runtime,
                    bot,
                    "payment_failed",
                    {"key": "provider_review_notice", "values": {"reference": event.external_id}},
                    "provider-review:" + event.id,
                    "payments",
                )
                return
            event.status, event.payload_ciphertext = "DONE", None
    elif job.kind == "CHECKOUT":
        from . import payment_methods
        from .texts import bot_text
        from .business import money
        from .console import Console

        entitlement(db, bot.tenant_id)
        payment = db.scalar(
            select(m.Payment)
            .where(
                m.Payment.id == p["payment_id"],
                m.Payment.bot_id == bot.id,
                m.Payment.tenant_id == bot.tenant_id,
            )
            .with_for_update()
        )
        if not payment or payment.status not in {"PENDING", "RECEIPT_SUBMITTED"}:
            return
        person = db.get(m.Contact, payment.contact_id)
        runtime.payments.providers[payment.provider].create_payment(db, bot, payment)
        ui = Console(runtime, db, bot, {"update_id": 0}, {"id": person.telegram_user_id})
        ui.language = person.locale
        message = (
            bot_text(db, bot, "PAYMENT_METHOD", locale=person.locale)
            + "\n"
            + money(payment.amount_minor, payment.currency)
        )
        buttons = []
        if payment.provider in {"BANK_TRANSFER", "CRYPTO_MANUAL"}:
            config = payment.instructions_snapshot or {}
            if not config and payment.provider == "BANK_TRANSFER":
                method = payment_methods.get(db, bot, payment.provider)
                config = payment_methods.public_config(runtime, method) if method else {}
                payment.instructions_snapshot = config
            if payment.provider == "CRYPTO_MANUAL":
                from .console_crypto import details

                message += "\n\n" + details(ui, config) + "\n\n" + ui.t("crypto_payment_notice")
            else:
                message += "\n" + "\n".join(
                    str(config.get(k, "")) for k in ["bank", "holder", "account", "instructions", "additional"]
                )
            message += "\n" + bot_text(db, bot, "RECEIPT_REQUEST", locale=person.locale)
            buttons = [[ui.button(ui.t("send_receipt"), "receipt_for", id=payment.id)]]
            if config.get("qr_file_id"):
                send(
                    db,
                    bot,
                    person.telegram_user_id,
                    "QR · " + money(payment.amount_minor, payment.currency),
                    "bank-qr:" + payment.id,
                    media={"kind": "photo", "file_id": config["qr_file_id"]},
                    service_message=True,
                )
        elif payment.checkout_url:
            buttons = [[{"text": ui.t("pay_now"), "url": payment.checkout_url}]]
        send(
            db,
            bot,
            person.telegram_user_id,
            message,
            "checkout-delivery:" + payment.id,
            reply_markup={"inline_keyboard": buttons},
            service_message=True,
        )
    elif job.kind == "SUBMIT_RECEIPT":
        payment = db.scalar(
            select(m.Payment)
            .where(
                m.Payment.id == p["payment_id"],
                m.Payment.bot_id == bot.id,
                m.Payment.tenant_id == bot.tenant_id,
            )
            .with_for_update()
        )
        person = db.get(m.Contact, payment.contact_id) if payment else None
        if not person or person.telegram_user_id != p["viewer_id"]:
            raise DomainError("NOT_FOUND", "Pago no disponible.", 404)
        data = runtime.clients.child(db, bot).download(p["file_id"], runtime.settings.max_upload_bytes)
        receipt = runtime.receipts.submit(db, bot, payment, data)
        from .notifications import customer

        customer(db, bot, person, "RECEIPT_RECEIVED", "receipt-received:" + receipt.id)
    elif job.kind == "SUBMIT_PLATFORM_RECEIPT":
        invoice = db.get(m.PlatformInvoice, p["invoice_id"])
        actor = db.get(m.PlatformUser, p["actor_id"])
        if invoice.tenant_id != job.tenant_id or db.get(m.Tenant, job.tenant_id).owner_user_id != actor.id:
            raise DomainError("NOT_FOUND", "Factura no disponible.", 404)
        data = runtime.clients.master().download(p["file_id"], runtime.settings.max_upload_bytes)
        runtime.ledger.submit(
            db,
            invoice,
            actor,
            p["method"],
            p["reference"],
            p.get("amount_usd_minor", runtime.ledger.outstanding(invoice)),
            data=data,
            evidence=p.get("evidence"),
        )
    elif job.kind == "DELIVER_PLATFORM_RECEIPT":
        if p["viewer_id"] not in runtime.settings.owner_ids:
            raise DomainError("OWNER_REQUIRED", "Acceso no permitido.", 403)
        send(
            db,
            None,
            p["viewer_id"],
            "Comprobante SaaS",
            "platform-proof:" + job.id,
            platform_receipt_id=p["settlement_id"],
            viewer_id=p["viewer_id"],
            service_message=True,
        )
    elif job.kind == "REPORT":
        report = db.scalar(
            select(m.Report).where(
                m.Report.id == p["report_id"], m.Report.bot_id == bot.id, m.Report.tenant_id == bot.tenant_id
            )
        )
        if report:
            runtime.reports.generate(db, bot, report)
    elif job.kind == "DASHBOARD":
        from .reporting import snapshot
        from .notifications import summary_text

        ui = admin_ui(runtime, db, bot, p["viewer_id"], "stats")
        data = snapshot(db, bot, p["starts_at"], p["ends_at"])
        send(
            db,
            bot,
            p["viewer_id"],
            summary_text(db, bot, data, ui.user.locale),
            "dashboard-result:" + job.id,
            service_message=True,
            viewer_id=p["viewer_id"],
            admin_permission="stats",
            reply_markup={
                "inline_keyboard": [
                    [
                        ui.button(ui.t("reports"), "reports"),
                        ui.button(ui.t("users"), "list", resource="contacts"),
                    ],
                    [ui.button(ui.t("home"), "home")],
                ]
            },
        )
    elif job.kind in {"PUBLISH", "VERIFY_CHANNELS"}:
        ui = admin_ui(runtime, db, bot, p["viewer_id"], "configure" if job.kind == "PUBLISH" else "channels")
        if job.kind == "PUBLISH":
            result = runtime.provisioner.publish(db, bot, ui.user.id)
            message = (
                ui.t("bot_published_notice")
                if result["ready"]
                else ui.t("publish_missing_notice")
                + "\n".join(
                    ui.t("publish_check_" + key) for key, value in result["checks"].items() if not value
                )
            )
        else:
            rows = list(
                db.scalars(
                    select(m.Channel).where(m.Channel.bot_id == bot.id, m.Channel.tenant_id == bot.tenant_id)
                )
            )
            message = "\n".join(
                ("✅ " if runtime.channels.verify(db, bot, row)["connected"] else "⚠️ ") + row.title
                for row in rows
            ) or ui.t("channel_required_notice")
        send(db, bot, p["viewer_id"], message, "configuration-result:" + job.id, service_message=True)
    elif job.kind == "CANCEL_CUSTOMER_RENEWAL":
        sub = db.get(m.Subscription, p["subscription_id"])
        if not sub or sub.bot_id != bot.id or sub.tenant_id != bot.tenant_id:
            raise DomainError("NOT_FOUND", "Suscripción no disponible.", 404)
        person = db.get(m.Contact, sub.contact_id)
        canceled = p.get("canceled", True)
        runtime.payments.providers["TELEGRAM_STARS"].cancel_subscription(db, bot, person, sub, canceled)
        sub.auto_renew, sub.renewal_status = not canceled, "CANCELED" if canceled else "ACTIVE"
        audit(
            db, bot.tenant_id, p.get("actor_id", "system"), "RENEWAL_UPDATED", sub.id, {"canceled": canceled}
        )
        if p.get("viewer_id"):
            from .i18n import t

            send(
                db,
                bot,
                p["viewer_id"],
                t("renewal_updated", person.locale),
                "renewal-updated:" + job.id,
                service_message=True,
            )
    elif job.kind in {"GRANT_CHANNEL", "REVOKE_CHANNEL"}:
        sub = db.get(m.Subscription, p["subscription_id"])
        if sub and sub.tenant_id == bot.tenant_id and sub.bot_id == bot.id:
            method = runtime.channels.grant if job.kind == "GRANT_CHANNEL" else runtime.channels.revoke
            method(db, bot, sub, p["channel_id"])
    else:
        raise DomainError("UNKNOWN_JOB", "Trabajo no disponible.")
