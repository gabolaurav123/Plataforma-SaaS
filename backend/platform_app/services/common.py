from sqlalchemy import select
from ..models import AuditLog, Event, Job, now, uid
from ..security import redact


def insert_once(session, model, values, columns):
    """Database uniqueness is the arbiter, including concurrent webhook workers."""
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(model).values(**values).on_conflict_do_nothing(index_elements=columns).returning(model)
    inserted = session.scalar(statement)
    if inserted is not None:
        return inserted, True
    return session.scalar(
        select(model).where(*(getattr(model, key) == values[key] for key in columns))
    ), False


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


def enqueue(
    session,
    kind,
    tenant_id,
    payload,
    dedup_key,
    bot_id=None,
    run_at=None,
    *,
    lane=None,
    stream_key=None,
    sequence=0,
):
    job, inserted = insert_once(
        session,
        Job,
        dict(
            id=uid(),
            kind=kind,
            tenant_id=tenant_id,
            bot_id=bot_id,
            payload=payload,
            dedup_key=dedup_key,
            run_at=run_at or now(),
            lane=lane
            or (
                "interactive"
                if kind == "UPDATE" or kind == "SEND" and dedup_key.startswith("console:")
                else "background"
            ),
            stream_key=stream_key,
            sequence=sequence,
        ),
        ["dedup_key"],
    )
    if inserted:
        session.info["jobs_enqueued"] = True
    return job


def emit(session, tenant_id, type, key, bot_id=None, contact_id=None, data=None):
    event, inserted = insert_once(
        session,
        Event,
        dict(
            id=uid(),
            tenant_id=tenant_id,
            type=type,
            dedup_key=key,
            bot_id=bot_id,
            contact_id=contact_id,
            data=data or {},
        ),
        ["tenant_id", "dedup_key"],
    )
    if inserted:
        enqueue(session, "EVENT", tenant_id, {"event_id": event.id}, f"event:{event.id}", bot_id)
    return event


def send(session, bot, chat_id, text, key, **extra):
    interactive = extra.pop("interactive", key.startswith("console:"))
    sequence = extra.pop("sequence", 0)
    if key.startswith("console:"):
        parts = key.rsplit(":", 2)
        sequence = int(parts[-2]) * 100 + int(parts[-1])
    return enqueue(
        session,
        "SEND",
        bot.tenant_id if bot else None,
        {"chat_id": chat_id, "text": text, **extra},
        key,
        bot.id if bot else None,
        lane="interactive" if interactive else "background",
        stream_key=f"{bot.id if bot else 'master'}:{chat_id}" if interactive else None,
        sequence=sequence,
    )
