from sqlalchemy import select
from ..models import AuditLog, Event, Job, now, uid
from ..security import redact


def audit(session, tenant_id, actor, action, entity_id=None, data=None):
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=str(actor),
            action=action,
            entity_id=entity_id,
            data=redact(data or {}),
        )
    )


def enqueue(session, kind, tenant_id, payload, dedup_key, bot_id=None, run_at=None):
    previous = session.scalar(select(Job).where(Job.dedup_key == dedup_key))
    if previous:
        return previous
    job = Job(
        id=uid(),
        kind=kind,
        tenant_id=tenant_id,
        bot_id=bot_id,
        payload=payload,
        dedup_key=dedup_key,
        run_at=run_at or now(),
    )
    session.add(job)
    session.flush()
    return job


def emit(session, tenant_id, type, key, bot_id=None, contact_id=None, data=None):
    existing = session.scalar(select(Event).where(Event.tenant_id == tenant_id, Event.dedup_key == key))
    if existing:
        return existing
    event = Event(
        id=uid(),
        tenant_id=tenant_id,
        type=type,
        dedup_key=key,
        bot_id=bot_id,
        contact_id=contact_id,
        data=data or {},
    )
    session.add(event)
    session.flush()
    enqueue(session, "EVENT", tenant_id, {"event_id": event.id}, f"event:{event.id}", bot_id)
    return event


def send(session, bot, chat_id, text, key, **extra):
    return enqueue(
        session,
        "SEND",
        bot.tenant_id if bot else None,
        {"chat_id": chat_id, "text": text, **extra},
        key,
        bot.id if bot else None,
    )
