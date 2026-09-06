from sqlalchemy import select
from ..models import Contact, Conversation, Message, AttributionLink, Referral, Job, now, uid
from ..errors import DomainError
from .common import audit, send
from .tenants import check_entity_limit

STAGES = {
    "LEAD",
    "INTERESTED",
    "PLAN_SELECTED",
    "PAYMENT_PENDING",
    "RECEIPT_SUBMITTED",
    "ACTIVE",
    "EXPIRING",
    "EXPIRED",
    "RECOVERED",
    "VIP",
    "BLOCKED",
}


def upsert_contact(session, bot, user, attribution_code=None):
    contact = session.scalar(
        select(Contact).where(Contact.bot_id == bot.id, Contact.telegram_user_id == user["id"])
    )
    if not contact:
        check_entity_limit(session, bot.tenant_id, "active_contacts", Contact)
        contact = Contact(
            id=uid(),
            tenant_id=bot.tenant_id,
            bot_id=bot.id,
            telegram_user_id=user["id"],
            first_name=user.get("first_name", "Cliente")[:128],
            username=user.get("username"),
            last_seen_at=now(),
        )
        session.add(contact)
        session.flush()
        if attribution_code:
            link = session.scalar(
                select(AttributionLink).where(
                    AttributionLink.bot_id == bot.id,
                    AttributionLink.tenant_id == bot.tenant_id,
                    AttributionLink.code == attribution_code,
                )
            )
            if link:
                contact.source, contact.campaign = link.source, link.campaign
                referrer = session.get(Contact, link.referrer_id) if link.referrer_id else None
                if (
                    referrer
                    and referrer.telegram_user_id != contact.telegram_user_id
                    and referrer.bot_id == bot.id
                ):
                    contact.referrer = referrer.id
                    session.add(
                        Referral(tenant_id=bot.tenant_id, referrer_id=referrer.id, referred_id=contact.id)
                    )
    contact.last_seen_at = now()
    return contact


def conversation(session, bot, contact):
    result = session.scalar(
        select(Conversation).where(
            Conversation.contact_id == contact.id, Conversation.tenant_id == bot.tenant_id
        )
    )
    if not result:
        result = Conversation(id=uid(), tenant_id=bot.tenant_id, bot_id=bot.id, contact_id=contact.id)
        session.add(result)
        session.flush()
    return result


def incoming(session, bot, contact, text, message_id):
    conv = conversation(session, bot, contact)
    message = Message(
        tenant_id=bot.tenant_id,
        conversation_id=conv.id,
        direction="IN",
        text=text[:4096],
        telegram_message_id=message_id,
        status="RECEIVED",
    )
    session.add(message)
    return message


def reply(session, bot, conv, actor, text, key):
    if conv.bot_id != bot.id or conv.tenant_id != bot.tenant_id:
        raise DomainError("NOT_FOUND", "Conversación no disponible.", 404)
    dedup_key = f"inbox:{bot.tenant_id}:{key}"
    previous = session.scalar(select(Job).where(Job.dedup_key == dedup_key, Job.tenant_id == bot.tenant_id))
    if previous:
        message = session.get(Message, previous.payload["message_id"])
        if message.conversation_id != conv.id or message.text != text or message.admin_id != actor:
            raise DomainError("IDEMPOTENCY_CONFLICT", "La operación ya existe con otros datos.", 409)
        return message
    contact = session.get(Contact, conv.contact_id)
    msg = Message(
        id=uid(),
        tenant_id=bot.tenant_id,
        conversation_id=conv.id,
        admin_id=actor,
        direction="OUT",
        text=text,
        status="QUEUED",
    )
    session.add(msg)
    session.flush()
    send(session, bot, contact.telegram_user_id, text, dedup_key, message_id=msg.id)
    audit(session, bot.tenant_id, actor, "MESSAGE_QUEUED", msg.id)
    return msg
