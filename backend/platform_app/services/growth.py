from datetime import datetime, UTC
from sqlalchemy import select
from ..models import (
    CampaignRecipient,
    Contact,
    AutomationRule,
    AutomationExecution,
    Event,
    Tag,
    ContactTag,
    CRMTask,
    TenantMember,
    PlatformUser,
    now,
    uid,
)
from ..errors import DomainError
from .common import enqueue, send, audit
from .tenants import feature, reserve_limit, entitlement
from .texts import render
from .crm import STAGES

TRIGGERS = {
    "USER_STARTED": "START",
    "PLAN_SELECTED": "PLAN_SELECTED",
    "PAYMENT_CREATED": "PAYMENT_PENDING",
    "PAYMENT_CONFIRMED": "PAYMENT_APPROVED",
    "SUBSCRIPTION_EXPIRING": "SUBSCRIPTION_EXPIRING",
    "SUBSCRIPTION_EXPIRED": "SUBSCRIPTION_EXPIRED",
    "SUBSCRIPTION_RENEWED": "SUBSCRIPTION_RENEWED",
    "INACTIVE": "INACTIVE",
}
ACTIONS = {"SEND_MESSAGE", "ADD_TAG", "CHANGE_CRM_STAGE", "NOTIFY_ADMIN", "CREATE_TASK", "SEND_PROMOTION"}


class CampaignService:
    def start(self, session, campaign, when=None):
        feature(session, campaign.tenant_id, "campaigns")
        if campaign.status not in {"DRAFT", "PAUSED", "SCHEDULED"}:
            raise DomainError("CAMPAIGN_STATE", "Esta campaña ya está en ejecución o finalizó.", 409)
        if campaign.status == "DRAFT":
            reserve_limit(
                session, campaign.tenant_id, "campaigns_month", period=datetime.now(UTC).strftime("%Y-%m")
            )
        campaign.scheduled_at = when or now()
        campaign.status = "SCHEDULED" if campaign.scheduled_at > now() else "RUNNING"
        enqueue(
            session,
            "CAMPAIGN",
            campaign.tenant_id,
            {"campaign_id": campaign.id},
            f"campaign:{campaign.id}:{uid()}",
            campaign.bot_id,
            run_at=campaign.scheduled_at,
        )

    def expand(self, session, campaign):
        entitlement(session, campaign.tenant_id)
        if campaign.status in {"PAUSED", "COMPLETED"}:
            return
        campaign.status = "RUNNING"
        query = select(Contact).where(
            Contact.tenant_id == campaign.tenant_id,
            Contact.bot_id == campaign.bot_id,
            Contact.opted_out.is_(False),
            Contact.stage != "BLOCKED",
        )
        if campaign.segment.get("stage"):
            query = query.where(Contact.stage == campaign.segment["stage"])
        if campaign.segment.get("source"):
            query = query.where(Contact.source == campaign.segment["source"])
        if campaign.cursor == "DONE":
            return
        if campaign.cursor:
            query = query.where(Contact.id > campaign.cursor)
        contacts = list(session.scalars(query.order_by(Contact.id).limit(100)))
        for contact in contacts:
            recipient = session.scalar(
                select(CampaignRecipient).where(
                    CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.contact_id == contact.id
                )
            )
            if not recipient:
                recipient = CampaignRecipient(
                    id=uid(), tenant_id=campaign.tenant_id, campaign_id=campaign.id, contact_id=contact.id
                )
                session.add(recipient)
                enqueue(
                    session,
                    "SEND",
                    campaign.tenant_id,
                    {
                        "chat_id": contact.telegram_user_id,
                        "text": render(campaign.text, {"first_name": contact.first_name}),
                        "recipient_id": recipient.id,
                    },
                    f"campaign-recipient:{campaign.id}:{contact.id}",
                    campaign.bot_id,
                )
        if len(contacts) == 100:
            campaign.cursor = contacts[-1].id
            enqueue(
                session,
                "CAMPAIGN",
                campaign.tenant_id,
                {"campaign_id": campaign.id},
                f"campaign-page:{campaign.id}:{campaign.cursor}",
                campaign.bot_id,
            )
        else:
            campaign.cursor = "DONE"
            if not contacts:
                campaign.status = "COMPLETED"


class AutomationService:
    def consume(self, session, event):
        if not event.contact_id or event.type not in TRIGGERS:
            return
        try:
            feature(session, event.tenant_id, "automations")
        except DomainError:
            return
        rules = session.scalars(
            select(AutomationRule).where(
                AutomationRule.tenant_id == event.tenant_id,
                AutomationRule.bot_id == event.bot_id,
                AutomationRule.trigger == TRIGGERS[event.type],
                AutomationRule.active.is_(True),
            )
        )
        for rule in rules:
            if session.scalar(
                select(AutomationExecution.id).where(
                    AutomationExecution.rule_id == rule.id, AutomationExecution.event_id == event.id
                )
            ):
                continue
            execution = AutomationExecution(
                id=uid(), tenant_id=event.tenant_id, rule_id=rule.id, event_id=event.id
            )
            session.add(execution)
            session.flush()
            enqueue(
                session,
                "AUTOMATION",
                event.tenant_id,
                {"execution_id": execution.id},
                f"automation:{rule.id}:{event.id}",
                event.bot_id,
                now() + rule.delay_seconds,
            )

    def execute(self, session, execution, bot):
        if execution.status != "PENDING":
            return
        feature(session, execution.tenant_id, "automations")
        rule, event = session.get(AutomationRule, execution.rule_id), session.get(Event, execution.event_id)
        contact = session.get(Contact, event.contact_id)
        if not rule.active or not contact:
            execution.status = "SKIPPED"
            return
        config = rule.config
        if rule.action in {"SEND_MESSAGE", "SEND_PROMOTION"}:
            if contact.opted_out or contact.stage == "BLOCKED":
                execution.status = "SKIPPED"
                return
            send(
                session,
                bot,
                contact.telegram_user_id,
                render(config.get("text", ""), {"first_name": contact.first_name}),
                f"automation-send:{execution.id}",
            )
        elif rule.action == "CHANGE_CRM_STAGE":
            if config.get("stage") not in STAGES:
                raise DomainError("INVALID_STAGE", "Etapa no válida.")
            contact.stage = config["stage"]
        elif rule.action == "ADD_TAG":
            tag = session.scalar(select(Tag).where(Tag.tenant_id == bot.tenant_id, Tag.name == config["tag"]))
            if not tag:
                tag = Tag(id=uid(), tenant_id=bot.tenant_id, name=config["tag"])
                session.add(tag)
                session.flush()
            if not session.scalar(
                select(ContactTag.id).where(ContactTag.contact_id == contact.id, ContactTag.tag_id == tag.id)
            ):
                session.add(ContactTag(tenant_id=bot.tenant_id, contact_id=contact.id, tag_id=tag.id))
        elif rule.action == "CREATE_TASK":
            session.add(CRMTask(tenant_id=bot.tenant_id, contact_id=contact.id, title=config["title"]))
        elif rule.action == "NOTIFY_ADMIN":
            admins = session.scalars(
                select(PlatformUser)
                .join(TenantMember, TenantMember.user_id == PlatformUser.id)
                .where(
                    TenantMember.tenant_id == bot.tenant_id,
                    TenantMember.active.is_(True),
                    TenantMember.role.in_(["OWNER", "SUPERVISOR"]),
                )
            )
            for admin in admins:
                send(
                    session,
                    None,
                    admin.telegram_user_id,
                    render(config.get("text", "Nuevo evento de cliente"), {"first_name": contact.first_name}),
                    f"automation-admin:{execution.id}:{admin.id}",
                )
        execution.status = "COMPLETED"
        audit(session, bot.tenant_id, "system", "AUTOMATION_EXECUTED", execution.id)
