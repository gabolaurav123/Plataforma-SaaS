import logging
import random
import signal
import time
from sqlalchemy import select, func
from .models import (
    Job,
    ManagedBot,
    TelegramUpdate,
    Event,
    Subscription,
    Contact,
    SaaSSubscription,
    Tenant,
    PlatformUser,
    Campaign,
    CampaignRecipient,
    AutomationExecution,
    Message,
    now,
    uid,
)
from .runtime import Runtime
from .errors import DomainError, RetryLater
from .services.common import enqueue, emit, send, audit
from .services.tenants import entitlement, suspend_due

log = logging.getLogger("platform.worker")


class Worker:
    def __init__(self, runtime):
        self.r, self.worker_id, self.cursor = runtime, uid(), None

    def claim(self):
        with self.r.db.system() as session:
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
                )
                .order_by(Job.run_at, Job.created_at)
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
            return job.id

    def mark_delivery(self, session, job, status, telegram_message_id=None):
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
            entitlement(session, bot.tenant_id)
            if bot.status in {"OWNERSHIP_CHANGED", "SUSPENDED"}:
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
        self.r.limiter.outbound(job.bot_id or "master", job.tenant_id or "platform", job.payload["chat_id"])
        client = self.r.clients.child(session, bot) if bot else self.r.clients.master()
        if job.payload.get("receipt_id"):
            from .services.console import Console
            from .models import BankReceipt

            receipt = session.get(BankReceipt, job.payload["receipt_id"])
            viewer = job.payload["viewer_id"]
            if viewer != job.payload["chat_id"] or bot:
                raise DomainError("INVALID_RECEIPT_VIEWER", "Acceso no permitido.", 403)
            ui = Console(self.r, session, None, {"update_id": 0}, {"id": viewer})
            ui.ctx(receipt.tenant_id, "payments")
            result = client.call(
                "sendPhoto",
                chat_id=viewer,
                caption=job.payload["caption"],
                files={"photo": ("comprobante.jpg", self.r.receipts.read(receipt), "image/jpeg")},
            )
            audit(session, receipt.tenant_id, ui.user.id, "TELEGRAM_RECEIPT_VIEWED", receipt.id)
            return
        params = {k: v for k, v in job.payload.items() if k in {"chat_id", "text", "reply_markup"}}
        result = client.call("sendMessage", **params)
        self.mark_delivery(session, job, "SENT", result.get("message_id"))
        audit(session, job.tenant_id, "worker", "MESSAGE_SENT", job.id)

    def tick(self, session):
        self.r.payments.expire_due(session)
        suspend_due(session)
        if self.r.settings.deployment_mode != "telegram":
            enqueue(session, "HEALTH_SCAN", None, {"bucket": now() // 900}, f"health-scan:{now() // 900}")
        for sub in session.scalars(
            select(Subscription)
            .where(
                Subscription.status == "ACTIVE",
                Subscription.expires_at > now(),
                Subscription.expires_at <= now() + 3 * 86400,
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
        for sub in session.scalars(
            select(SaaSSubscription)
            .where(
                SaaSSubscription.status == "TRIAL",
                SaaSSubscription.trial_ends_at.between(now(), now() + 86400),
            )
            .limit(1000)
        ):
            tenant = session.get(Tenant, sub.tenant_id)
            user = session.get(PlatformUser, tenant.owner_user_id)
            send(
                session,
                None,
                user.telegram_user_id,
                "Tu prueba termina en menos de 24 horas. Abre Facturación para continuar.",
                f"trial-reminder:{sub.id}",
            )

    def dispatch(self, session, job):
        bot = session.get(ManagedBot, job.bot_id) if job.bot_id else None
        if job.kind == "UPDATE":
            update = session.get(TelegramUpdate, job.payload["update_id"])
            if update.status == "DONE":
                return
            if bot:
                self.r.updates.child(session, bot, update.payload)
            else:
                self.r.updates.master(session, update.payload)
            update.status = "DONE"
        elif job.kind == "SEND":
            self.process_send(session, job, bot)
        elif job.kind in {"GRANT_ACCESS", "REVOKE_ACCESS"}:
            sub = session.get(Subscription, job.payload["subscription_id"])
            if sub and sub.bot_id == bot.id and sub.tenant_id == bot.tenant_id:
                (self.r.channels.grant if job.kind == "GRANT_ACCESS" else self.r.channels.revoke)(
                    session, bot, sub
                )
        elif job.kind == "EVENT":
            self.r.automations.consume(session, session.get(Event, job.payload["event_id"]))
        elif job.kind == "AUTOMATION":
            self.r.automations.execute(
                session, session.get(AutomationExecution, job.payload["execution_id"]), bot
            )
        elif job.kind == "CAMPAIGN":
            self.r.campaigns.expand(session, session.get(Campaign, job.payload["campaign_id"]))
        elif job.kind == "CONFIGURE":
            from .models import BotSettings

            self.r.provisioner.apply_configuration(
                session, bot, session.scalar(select(BotSettings).where(BotSettings.bot_id == bot.id))
            )
            bot.status, bot.last_error_code = "READY", None
        elif job.kind == "HEALTH":
            if bot and bot.status not in {"OWNERSHIP_CHANGED", "SUSPENDED"}:
                self.r.provisioner.health(session, bot, repair=True)
        elif job.kind == "HEALTH_SCAN":
            query = select(ManagedBot).where(ManagedBot.status.not_in(["OWNERSHIP_CHANGED", "SUSPENDED"]))
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
        job_id = self.claim()
        if not job_id:
            return False
        try:
            with self.r.db.system() as session:
                job = session.get(Job, job_id)
                provision = job.kind == "PROVISION"
                bot_id, rotate = job.bot_id, job.payload.get("rotate", False) and job.attempts == 1
            if provision:
                self.r.provisioner.provision(bot_id, rotate=rotate)
                with self.r.db.system() as session:
                    job = session.get(Job, job_id)
                    job.status = "DONE"
            else:
                with self.r.db.system() as session:
                    job = session.get(Job, job_id)
                    self.dispatch(session, job)
                    job.status = "DONE"
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
                if job.bot_id and code in {"TOKEN_INVALID", "TELEGRAM_FORBIDDEN"}:
                    session.get(ManagedBot, job.bot_id).last_error_code = code
                    if code == "TOKEN_INVALID" and job.kind != "PROVISION":
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
