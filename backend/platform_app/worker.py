import logging
import json
import random
import signal
import time
import base64
from contextlib import nullcontext
from sqlalchemy import select, func, exists, cast, String, case, inspect, update as sql_update
from sqlalchemy.orm import aliased, undefer
from .models import (
    Job,
    ManagedBot,
    TelegramUpdate,
    Event,
    Subscription,
    Contact,
    Campaign,
    CampaignRecipient,
    AutomationExecution,
    Message,
    now,
    uid,
)
from .runtime import Runtime
from . import models as m
from .errors import DomainError, RetryLater
from .services.common import enqueue, emit, send, audit
from .services.tenants import entitlement

log = logging.getLogger("platform.worker")


class Worker:
    def __init__(self, runtime, lane=None):
        self.r, self.worker_id, self.cursor, self.lane = runtime, uid(), None, lane
        self.recovery_at = 0

    def claim(self):
        with self.r.db.system() as session:
            if session.bind.dialect.name == "postgresql":
                return self.claim_postgres(session)
            # An interrupted send may already have reached Telegram. Never resend it blindly.
            stale = session.scalars(
                select(Job)
                .where(Job.status == "RUNNING", Job.lease_until < now())
                .with_for_update(skip_locked=True)
                .limit(100)
            )
            for job in stale:
                job.status = "DELIVERY_UNKNOWN" if job.kind == "SEND" else "PENDING"
                if job.kind == "SEND":
                    self.mark_delivery(session, job, "DELIVERY_UNKNOWN")
            session.flush()
            groups = list(
                session.execute(
                    select(Job.tenant_id, func.min(Job.run_at))
                    .where(Job.status == "PENDING", Job.run_at <= now())
                    .where(Job.lane == self.lane if self.lane else True)
                    .group_by(Job.tenant_id)
                    .order_by(Job.tenant_id)
                    .limit(10001)
                )
            )
            if not groups:
                return None
            keys = [g[0] or "" for g in groups]
            key = next((k for k in keys if self.cursor is not None and k > self.cursor), keys[0])
            self.cursor = key
            job = session.scalar(
                select(Job)
                .where(
                    Job.status == "PENDING",
                    Job.run_at <= now(),
                    Job.tenant_id == key if key else Job.tenant_id.is_(None),
                    Job.lane == self.lane if self.lane else True,
                )
                .order_by(Job.run_at, Job.sequence, Job.created_at, Job.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if not job:
                return None
            job.status, job.lease_owner, job.lease_until = (
                "RUNNING",
                self.worker_id,
                now() + self.r.settings.worker_lease_seconds,
            )
            job.attempts += 1
            job.started_at = now()
            return job.id

    def claim_postgres(self, session):
        """One atomic claim, with stream order checked before consuming a lease."""
        if time.monotonic() >= self.recovery_at:
            for job in session.scalars(
                select(Job)
                .where(Job.status == "RUNNING", Job.lease_until < now())
                .with_for_update(skip_locked=True)
                .limit(100)
            ):
                job.status = "DELIVERY_UNKNOWN" if job.kind == "SEND" else "PENDING"
                if job.kind == "SEND":
                    self.mark_delivery(session, job, "DELIVERY_UNKNOWN")
            session.flush()
            self.recovery_at = time.monotonic() + 5
        candidate, earlier = aliased(Job), aliased(Job)
        blocked = exists(
            select(earlier.id)
            .where(
                earlier.stream_key == candidate.stream_key,
                earlier.sequence < candidate.sequence,
                earlier.status.in_(["PENDING", "RUNNING"]),
            )
            .correlate(candidate)
        )
        tenant = func.coalesce(candidate.tenant_id, "")
        query = (
            select(candidate.id)
            .where(
                candidate.status == "PENDING",
                candidate.run_at <= now(),
                candidate.lane == self.lane if self.lane else True,
                ~blocked,
            )
            .order_by(
                case((tenant > self.cursor, 0), else_=1) if self.cursor is not None else tenant,
                tenant,
                candidate.run_at,
                candidate.sequence,
                candidate.created_at,
                candidate.id,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        claimed = session.execute(
            sql_update(Job)
            .where(Job.id == query.scalar_subquery())
            .values(
                status="RUNNING",
                lease_owner=self.worker_id,
                lease_until=now() + self.r.settings.worker_lease_seconds,
                started_at=now(),
                attempts=Job.attempts + 1,
            )
            .returning(Job.id, Job.tenant_id)
            .execution_options(synchronize_session=False)
        ).first()
        if claimed:
            self.cursor = claimed.tenant_id or ""
            return claimed.id
        return None

    def mark_delivery(self, session, job, status, telegram_message_id=None):
        if job.payload.get("inbox_delivery_id"):
            delivery = session.get(m.InboxDelivery, job.payload["inbox_delivery_id"])
            if delivery and delivery.bot_id == job.bot_id and delivery.tenant_id == job.tenant_id:
                delivery.status, delivery.telegram_message_id = status, telegram_message_id
        if job.payload.get("message_id"):
            message = session.get(Message, job.payload["message_id"])
            if message:
                message.status, message.telegram_message_id = status, telegram_message_id
        if job.payload.get("recipient_id"):
            recipient = session.get(CampaignRecipient, job.payload["recipient_id"])
            if recipient:
                recipient.status = status
                session.flush()
                campaign = session.get(Campaign, recipient.campaign_id)
                pending = session.scalar(
                    select(CampaignRecipient.id)
                    .where(CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.status == "QUEUED")
                    .limit(1)
                )
                if campaign.cursor == "DONE" and not pending and campaign.status != "PAUSED":
                    campaign.status = "COMPLETED"

    def process_send(self, session, job, bot):
        if bot:
            entitlement(session, bot.tenant_id, writable=not job.payload.get("service_message"))
            if bot.status in {"OWNERSHIP_CHANGED", "SUSPENDED", "DISCONNECTED"}:
                raise DomainError("BOT_SUSPENDED", "Bot suspendido.", 403)
        recipient_id = job.payload.get("recipient_id")
        if recipient_id:
            recipient = session.get(CampaignRecipient, recipient_id)
            campaign, contact = (
                session.get(Campaign, recipient.campaign_id),
                session.get(Contact, recipient.contact_id),
            )
            if campaign.status == "PAUSED":
                raise RetryLater(30, "CAMPAIGN_PAUSED")
            if contact.opted_out or contact.stage == "BLOCKED":
                self.mark_delivery(session, job, "SKIPPED")
                return
        if job.payload.get("admin_permission"):
            from .services.background import admin_ui

            if not bot or job.payload.get("viewer_id") != job.payload["chat_id"]:
                raise DomainError("INVALID_VIEWER", "Acceso no permitido.", 403)
            admin_ui(self.r, session, bot, job.payload["viewer_id"], job.payload["admin_permission"])
        if job.payload.get("reply_actor_id"):
            from .services.background import admin_ui

            ui = admin_ui(self.r, session, bot, job.payload["reply_actor_id"], "support")
            outgoing = ui.entity(Message, bot.tenant_id, job.payload["message_id"], "support")
            conv = ui.entity(m.Conversation, bot.tenant_id, outgoing.conversation_id, "support")
            contact = ui.entity(Contact, bot.tenant_id, conv.contact_id, "support")
            if outgoing.admin_id != ui.user.id or contact.telegram_user_id != job.payload["chat_id"]:
                raise DomainError("INVALID_REPLY_RECIPIENT", "Conversación no disponible.", 403)
        self.r.limiter.outbound(job.bot_id or "master", job.tenant_id or "platform", job.payload["chat_id"])
        client = self.r.clients.child(session, bot) if bot else self.r.clients.master()
        if job.payload.get("receipt_id"):
            from .services.console import Console
            from .models import BankReceipt

            receipt = session.get(BankReceipt, job.payload["receipt_id"])
            viewer = job.payload["viewer_id"]
            if not receipt or viewer != job.payload["chat_id"]:
                raise DomainError("INVALID_RECEIPT_VIEWER", "Acceso no permitido.", 403)
            ui = Console(self.r, session, bot, {"update_id": 0}, {"id": viewer})
            ui.entity(BankReceipt, receipt.tenant_id, receipt.id, "payments")
            is_pdf = receipt.media_type == "application/pdf"
            result = client.call(
                "sendDocument" if is_pdf else "sendPhoto",
                chat_id=viewer,
                caption=job.payload["caption"],
                files={
                    "document" if is_pdf else "photo": (
                        "comprobante.pdf" if is_pdf else "comprobante.jpg",
                        self.r.receipts.read(receipt),
                        receipt.media_type,
                    )
                },
            )
            audit(session, receipt.tenant_id, ui.user.id, "TELEGRAM_RECEIPT_VIEWED", receipt.id)
            return
        if job.payload.get("platform_receipt_id"):
            viewer = job.payload.get("viewer_id")
            if bot or viewer != job.payload["chat_id"] or viewer not in self.r.settings.owner_ids:
                raise DomainError("OWNER_REQUIRED", "Acceso no permitido.", 403)
            receipt = session.get(m.PlatformSettlement, job.payload["platform_receipt_id"])
            data = base64.b64decode(
                self.r.vault.decrypt(
                    receipt.receipt_ciphertext, f"{receipt.tenant_id}:{receipt.id}:platform-receipt"
                )
            )
            client.call(
                "sendDocument",
                chat_id=viewer,
                files={
                    "document": (
                        "comprobante.pdf" if receipt.media_type == "application/pdf" else "comprobante.jpg",
                        data,
                        receipt.media_type,
                    )
                },
            )
            audit(session, receipt.tenant_id, str(viewer), "PLATFORM_RECEIPT_VIEWED", receipt.id)
            return
        if job.payload.get("report_id"):
            from .services.background import admin_ui

            viewer = job.payload["viewer_id"]
            if not bot or viewer != job.payload["chat_id"]:
                raise DomainError("INVALID_VIEWER", "Acceso no permitido.", 403)
            ui = admin_ui(self.r, session, bot, viewer, "export")
            report = ui.entity(m.Report, bot.tenant_id, job.payload["report_id"], "export")
            client.call(
                "sendDocument",
                chat_id=viewer,
                caption=job.payload.get("text", "Reporte CSV"),
                files={
                    "document": ("reporte-" + report.id[:8] + ".csv", self.r.reports.read(report), "text/csv")
                },
            )
            audit(session, bot.tenant_id, ui.user.id, "REPORT_DOWNLOADED", report.id)
            return
        params = {k: v for k, v in job.payload.items() if k in {"chat_id", "text", "reply_markup"}}
        media = job.payload.get("media")
        if media:
            from .services.inbox import MEDIA_METHODS, CAPTION_MEDIA

            kind = media.get("kind")
            if kind not in MEDIA_METHODS:
                raise DomainError("INVALID_MEDIA", "Tipo de archivo no permitido.")
            caption = params.pop("text", "")[:1024]
            if kind in CAPTION_MEDIA:
                params["caption"] = caption
            params[kind] = media["file_id"]
            result = client.call(MEDIA_METHODS[kind], **params)
        else:
            result = client.call("sendMessage", **params)
        self.mark_delivery(
            session, job, "SENT", result.get("message_id") if isinstance(result, dict) else None
        )
        if job.payload.get("ingested_at_ms"):
            response_ms = max(0, int(time.time() * 1000) - job.payload["ingested_at_ms"])
            job.payload = {**job.payload, "response_ms": response_ms}
            log.info(
                "telegram_response bot=%s response_ms=%d",
                job.bot_id or "master",
                response_ms,
            )
        audit(session, job.tenant_id, "worker", "MESSAGE_SENT", job.id)

    def tick(self, session):
        self.r.payments.expire_due(session)
        self.r.ledger.tick(session)
        from .services.tenants import suspend_due

        suspend_due(session)
        enqueue(session, "SUMMARY_SCAN", None, {"batch": now() // 3600}, f"summary-scan:{now() // 3600}")
        if self.r.settings.deployment_mode != "telegram":
            enqueue(session, "HEALTH_SCAN", None, {"bucket": now() // 900}, f"health-scan:{now() // 900}")
        for sub in session.scalars(
            select(Subscription)
            .where(
                Subscription.status == "ACTIVE",
                Subscription.expires_at > now(),
                Subscription.expires_at <= now() + 3 * 86400,
                ~exists(
                    select(Event.id).where(
                        Event.tenant_id == Subscription.tenant_id,
                        Event.dedup_key
                        == "expiring:" + Subscription.id + ":" + cast(Subscription.expires_at, String),
                    )
                ),
            )
            .limit(1000)
        ):
            emit(
                session,
                sub.tenant_id,
                "SUBSCRIPTION_EXPIRING",
                f"expiring:{sub.id}:{sub.expires_at}",
                sub.bot_id,
                sub.contact_id,
            )
            from .services.notifications import customer

            customer(
                session,
                session.get(ManagedBot, sub.bot_id),
                session.get(Contact, sub.contact_id),
                "SUBSCRIPTION_EXPIRING",
                f"expiry-reminder:{sub.id}:{sub.expires_at}",
                sub,
            )

    def dispatch(self, session, job):
        from .services.background import KINDS, process

        if job.stream_key:
            earlier_query = exists(
                select(Job.id)
                .where(
                    Job.stream_key == job.stream_key,
                    Job.sequence < job.sequence,
                    Job.status.in_(["PENDING", "RUNNING"]),
                    Job.id != job.id,
                )
                .limit(1)
            )
            if session.bind.dialect.name == "postgresql":
                locked, earlier = session.execute(
                    select(
                        func.pg_try_advisory_xact_lock(func.hashtextextended(job.stream_key, 0)),
                        earlier_query,
                    )
                ).one()
                if not locked:
                    raise RetryLater(1, "STREAM_BUSY")
            else:
                earlier = session.scalar(select(earlier_query))
            if earlier:
                raise RetryLater(1, "STREAM_ORDER")
        bot = session.get(ManagedBot, job.bot_id) if job.bot_id else None
        if job.kind in KINDS:
            process(self.r, session, job, bot)
        elif job.kind == "UPDATE":
            update = session.get(
                TelegramUpdate,
                job.payload["update_id"],
                options=[undefer(TelegramUpdate.sensitive_ciphertext)],
            )
            if update.status == "DONE":
                return
            payload = (
                json.loads(
                    self.r.vault.decrypt(
                        update.sensitive_ciphertext, f"transport:{update.bot_key}:{update.update_id}"
                    )
                )
                if update.sensitive_ciphertext
                else update.payload
            )
            payload["_ingested_at_ms"] = update.payload.get("_ingested_at_ms")
            if bot:
                self.r.updates.child(session, bot, payload)
            else:
                self.r.updates.master(session, payload)
            update.status = "DONE"
            update.sensitive_ciphertext = None
        elif job.kind == "SEND":
            self.process_send(session, job, bot)
        elif job.kind == "VALIDATE_CONNECTION":
            from .models import ConnectionAttempt

            attempt = session.get(ConnectionAttempt, job.payload["attempt_id"])
            if attempt and attempt.tenant_id == job.tenant_id:
                self.r.connections.validate(session, attempt)
        elif job.kind in {"GRANT_ACCESS", "REVOKE_ACCESS"}:
            sub = session.get(Subscription, job.payload["subscription_id"])
            if sub and sub.bot_id == bot.id and sub.tenant_id == bot.tenant_id:
                channels = job.payload.get("channel_ids", sub.channel_snapshot)
                for cid in channels:
                    kind = "GRANT_CHANNEL" if job.kind == "GRANT_ACCESS" else "REVOKE_CHANNEL"
                    enqueue(
                        session,
                        kind,
                        bot.tenant_id,
                        {"subscription_id": sub.id, "channel_id": cid},
                        f"access-channel:{job.id}:{cid}",
                        bot.id,
                    )
        elif job.kind == "EVENT":
            self.r.automations.consume(session, session.get(Event, job.payload["event_id"]))
        elif job.kind == "AUTOMATION":
            self.r.automations.execute(
                session, session.get(AutomationExecution, job.payload["execution_id"]), bot
            )
        elif job.kind == "CAMPAIGN":
            self.r.campaigns.expand(session, session.get(Campaign, job.payload["campaign_id"]))
        elif job.kind == "REGISTER_COMMANDS":
            settings = session.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
            if settings:
                if not any(c.get("command") == "id" for c in settings.commands):
                    settings.commands = [
                        *settings.commands[:99],
                        {"command": "id", "description": "Mi ID de Telegram"},
                    ]
                self.r.clients.child(session, bot).call("setMyCommands", commands=settings.commands)
        elif job.kind == "CONFIGURE":
            from .models import BotSettings

            self.r.provisioner.apply_configuration(
                session, bot, session.scalar(select(BotSettings).where(BotSettings.bot_id == bot.id))
            )
            bot.status, bot.last_error_code = "READY", None
        elif job.kind == "HEALTH":
            if bot and bot.status not in {
                "OWNERSHIP_CHANGED",
                "SUSPENDED",
                "DISCONNECTED",
                "CONNECTION_ERROR",
            }:
                self.r.provisioner.health(session, bot, repair=True)
        elif job.kind == "HEALTH_SCAN":
            query = select(ManagedBot).where(
                ManagedBot.status.not_in(
                    ["OWNERSHIP_CHANGED", "SUSPENDED", "DISCONNECTED", "CONNECTION_ERROR"]
                )
            )
            cursor, bucket = job.payload.get("after"), job.payload["bucket"]
            if cursor:
                query = query.where(ManagedBot.id > cursor)
            bots = list(session.scalars(query.order_by(ManagedBot.id).limit(100)))
            for target in bots:
                enqueue(
                    session,
                    "HEALTH",
                    target.tenant_id,
                    {},
                    f"health:{target.id}:{bucket}",
                    target.id,
                    run_at=now() + int(target.id.replace("-", "")[:8], 16) % 900,
                )
            if len(bots) == 100:
                enqueue(
                    session,
                    "HEALTH_SCAN",
                    None,
                    {"bucket": bucket, "after": bots[-1].id},
                    f"health-scan:{bucket}:{bots[-1].id}",
                )
        elif job.kind == "TICK":
            self.tick(session)
        else:
            raise DomainError("UNKNOWN_JOB", "Tipo de trabajo no soportado.")

    def run_one(self):
        with self.r.claim_lock if self.r.db.system_engine.dialect.name == "sqlite" else nullcontext():
            return self._run_one()

    def _run_one(self):
        job_id = self.claim()
        if not job_id:
            return False
        return self.process_claimed(job_id)

    def reserve_reply(self, session, update_job):
        if update_job.kind != "UPDATE" or session.bind.dialect.name != "postgresql":
            return None
        candidates = [
            reply
            for reply in session.info.get("console_replies", [])
            if inspect(reply).persistent
            and reply.status == "PENDING"
            and reply.bot_id == update_job.bot_id
            and reply.tenant_id == update_job.tenant_id
            and reply.stream_key == update_job.stream_key
            and update_job.sequence < reply.sequence < update_job.sequence + 100
        ]
        if not candidates:
            return None
        reply = min(candidates, key=lambda row: row.sequence)
        reply.status, reply.lease_owner = "RUNNING", self.worker_id
        reply.lease_until, reply.started_at = now() + self.r.settings.worker_lease_seconds, now()
        reply.attempts += 1
        return reply.id

    def process_claimed(self, job_id):
        reserved_reply, committed = None, False
        try:
            with self.r.db.system() as session:
                # Keep the job row locked throughout remote provisioning too. A lease
                # timeout cannot give the same active job to a second worker.
                job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
                if not job or job.status != "RUNNING" or job.lease_owner != self.worker_id:
                    return True
                if job.kind == "PROVISION":
                    self.r.provisioner.provision(
                        job.bot_id, rotate=job.payload.get("rotate", False) and job.attempts == 1
                    )
                else:
                    self.dispatch(session, job)
                job.status = "DONE"
                reserved_reply = self.reserve_reply(session, job)
            committed = True
        except RetryLater as error:
            with self.r.db.system() as session:
                job = session.get(Job, job_id)
                job.status, job.run_at, job.last_error_code = "PENDING", now() + error.seconds, error.code
                job.attempts = max(0, job.attempts - 1)
        except Exception as error:
            code = error.code if isinstance(error, DomainError) else "INTERNAL_JOB_ERROR"
            with self.r.db.system() as session:
                job = session.get(Job, job_id)
                ambiguous = job.kind == "SEND" and code in {
                    "TELEGRAM_TRANSPORT_UNKNOWN",
                    "INTERNAL_JOB_ERROR",
                }
                job.last_error_code = code
                job.status = (
                    "DELIVERY_UNKNOWN"
                    if ambiguous
                    else "FAILED"
                    if job.attempts >= 8 or isinstance(error, DomainError) and error.status < 500
                    else "PENDING"
                )
                job.run_at = now() + min(3600, 2**job.attempts + random.randint(0, 3))
                if job.status in {"FAILED", "DELIVERY_UNKNOWN"}:
                    self.mark_delivery(session, job, job.status)
                    viewer, language = job.payload.get("viewer_id"), "es"
                    if job.kind == "UPDATE":
                        update = session.get(m.TelegramUpdate, job.payload["update_id"])
                        if update:
                            update.status = "FAILED"
                    if job.kind == "PROVIDER_EVENT":
                        event = session.get(m.ProviderEvent, job.payload["event_id"])
                        if event:
                            event.status = "FAILED"
                    if job.kind == "CHECKOUT":
                        payment = session.get(m.Payment, job.payload["payment_id"])
                        person = session.get(Contact, payment.contact_id) if payment else None
                        if person:
                            viewer, language = person.telegram_user_id, person.locale
                    if job.kind == "REPORT":
                        report = session.get(m.Report, job.payload["report_id"])
                        if report:
                            report.status = "FAILED"
                            actor = session.get(m.PlatformUser, report.actor_id)
                            viewer, language = actor.telegram_user_id, actor.locale
                    if job.kind not in {"SEND", "UPDATE", "DELETE_MESSAGE"} and viewer:
                        target = session.get(ManagedBot, job.bot_id) if job.bot_id else None
                        from .services.i18n import t

                        send(
                            session,
                            target,
                            viewer,
                            t("operation_failed", language),
                            "job-error:" + job.id,
                            service_message=True,
                        )
                if code == "TELEGRAM_FORBIDDEN" and job.kind == "SEND" and job.bot_id:
                    person = session.scalar(
                        select(Contact).where(
                            Contact.bot_id == job.bot_id,
                            Contact.telegram_user_id == job.payload.get("chat_id"),
                        )
                    )
                    if person:
                        person.stage = "BLOCKED"
                    self.mark_delivery(session, job, "BLOCKED")
                if job.bot_id and code in {"TOKEN_INVALID", "TELEGRAM_FORBIDDEN"}:
                    session.get(ManagedBot, job.bot_id).last_error_code = code
                    target = session.get(ManagedBot, job.bot_id)
                    if code == "TOKEN_INVALID" and target.connection_kind == "TOKEN":
                        target.status = "CONNECTION_ERROR"
                        session.info["bots_changed"] = True
                        send(
                            session,
                            None,
                            target.owner_telegram_user_id,
                            f"⚠️ @{target.username}: el token ya no es válido. Reemplázalo desde Conexión en tu cuenta SaaS.",
                            f"token-invalid:{target.id}:{target.config_version}",
                        )
                    elif code == "TOKEN_INVALID" and job.kind != "PROVISION":
                        enqueue(
                            session,
                            "PROVISION",
                            job.tenant_id,
                            {},
                            f"token-repair:{job.bot_id}:{now() // 900}",
                            job.bot_id,
                        )
            # Never log the exception, HTTP URL, update body, or provider response.
            log.error("job_failed", extra={"job_id": job_id, "error_code": code})
        if committed and reserved_reply:
            # The menu, buttons and SEND lease are durable before contacting Telegram.
            # A crash here leaves an uncertain SEND; normal recovery never resends it blindly.
            self.process_claimed(reserved_reply)
        return True


def main():
    runtime, running = Runtime(), True
    if runtime.settings.environment == "production":
        runtime.db.verify_production_boundary()
    worker = Worker(runtime)

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    next_tick = 0
    while running:
        if now() >= next_tick:
            with runtime.db.system() as session:
                enqueue(session, "TICK", None, {}, f"tick:{now() // 60}")
            next_tick = now() + 60
        if not worker.run_one():
            time.sleep(0.25)


if __name__ == "__main__":
    main()
