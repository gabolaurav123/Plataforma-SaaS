import hmac
import json
import time
from copy import deepcopy
from fastapi import APIRouter, Request, Depends
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select, func, literal
from sqlalchemy.exc import IntegrityError
from ..models import ManagedBot, BotSecret, TelegramUpdate, uid
from ..security import digest
from ..errors import DomainError
from ..services.common import enqueue, insert_once
from .auth import runtime

router = APIRouter()


def store_polling_postgres(session, bot_id, tenant_id, update, values):
    """Commit offset, encrypted update and its outbox job with a single round trip."""
    from sqlalchemy.dialects.postgresql import insert
    from ..models import PollCursor, Job

    key = bot_id or "master"
    timestamp = int(time.time())

    def explicit(model, data):
        return {name: literal(value, type_=model.__table__.c[name].type) for name, value in data.items()}

    cursor = insert(PollCursor).values(
        **explicit(
            PollCursor,
            dict(
                id=uid(),
                bot_key=key,
                next_offset=update["update_id"] + 1,
                created_at=timestamp,
                updated_at=timestamp,
            ),
        )
    )
    cursor = cursor.on_conflict_do_update(
        index_elements=["bot_key"],
        set_={"next_offset": func.greatest(PollCursor.next_offset, cursor.excluded.next_offset)},
    ).cte("advanced_cursor")
    accepted = (
        insert(TelegramUpdate)
        .values(
            **explicit(
                TelegramUpdate,
                {
                    **values,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "status": "PENDING",
                },
            )
        )
        .on_conflict_do_nothing(index_elements=["bot_key", "update_id"])
        .returning(TelegramUpdate.id)
        .cte("accepted_update")
    )
    actor = update.get("callback_query", {}).get("from") or update.get("message", {}).get("from") or {}
    job = dict(
        id=uid(),
        tenant_id=tenant_id,
        bot_id=bot_id,
        kind="UPDATE",
        created_at=timestamp,
        updated_at=timestamp,
        status="PENDING",
        attempts=0,
        payload={"update_id": values["id"]},
        dedup_key=f"update:{key}:{update['update_id']}",
        run_at=timestamp,
        lane="interactive",
        stream_key=f"{key}:{actor.get('id', 'service')}",
        sequence=update["update_id"] * 100,
    )
    statement = (
        insert(Job)
        .from_select(
            list(job),
            select(
                *(literal(value, type_=Job.__table__.c[name].type) for name, value in job.items())
            ).select_from(accepted),
            include_defaults=False,
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(Job.id)
        .add_cte(cursor)
    )
    inserted = session.scalar(statement)
    if inserted:
        session.info["jobs_enqueued"] = True
    return {"ok": True, **({"duplicate": True} if not inserted else {})}


@router.post("/telegram/webhook/{public_id}", status_code=200)
async def webhook(public_id: str, request: Request, r=Depends(runtime)):
    header = request.headers.get("x-telegram-bot-api-secret-token", "")
    try:
        update = await request.json()
    except ValueError:
        raise DomainError("INVALID_UPDATE", "Update no válido.") from None
    return await run_in_threadpool(ingest, public_id, header, update, r)


def ingest(public_id, header, update, r):
    with r.db.system() as session:
        bot = None
        if public_id == "master":
            expected = r.settings.master_webhook_secret.get_secret_value()
            valid = bool(expected) and hmac.compare_digest(expected, header)
        else:
            bot = session.scalar(select(ManagedBot).where(ManagedBot.public_id == public_id))
            secret = session.scalar(select(BotSecret).where(BotSecret.bot_id == bot.id)) if bot else None
            valid = bool(secret) and hmac.compare_digest(secret.webhook_secret_hash, digest(header))
        if not valid:
            raise DomainError("INVALID_WEBHOOK", "Webhook no autorizado.", 403)
        if bot and bot.status in {"DISCONNECTED", "OWNERSHIP_CHANGED"}:
            return {"ok": True, "disconnected": True}
        bot_id, tenant_id = (bot.id, bot.tenant_id) if bot else (None, None)
    return store_update(bot_id, tenant_id, update, r)


def store_update(bot_id, tenant_id, update, r, *, polling=False):
    """Trusted ingestion shared by authenticated webhooks and outbound Telegram polling."""
    if not isinstance(update, dict) or type(update.get("update_id")) is not int:
        raise DomainError("INVALID_UPDATE", "Update no válido.")
    bot_key = bot_id or "master"
    ingested_at_ms = int(time.time() * 1000)
    try:
        with r.db.system() as session:
            bot = session.get(ManagedBot, bot_id) if bot_id else None
            if bot_id and (not bot or bot.tenant_id != tenant_id):
                raise DomainError("BOT_NOT_FOUND", "Bot no disponible.", 404)
            fast_polling = (
                polling and session.bind.dialect.name == "postgresql" and not update.get("pre_checkout_query")
            )
            if polling and not fast_polling:
                from ..models import PollCursor

                pg = session.bind.dialect.name == "postgresql"
                if pg:
                    from sqlalchemy.dialects.postgresql import insert
                else:
                    from sqlalchemy.dialects.sqlite import insert
                statement = insert(PollCursor).values(bot_key=bot_key, next_offset=update["update_id"] + 1)
                session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["bot_key"],
                        set_={
                            "next_offset": (func.greatest if pg else func.max)(
                                PollCursor.next_offset, statement.excluded.next_offset
                            )
                        },
                    )
                )
            safe_update, encrypted = deepcopy(update), None
            safe_update["_ingested_at_ms"] = ingested_at_ms
            message = update.get("message", {})
            if message.get("chat", {}).get("type") == "private":
                encrypted = r.vault.encrypt(json.dumps(update), f"transport:{bot_key}:{update['update_id']}")
                # Includes captions, nested replies and media; keep only routing/timing metadata public.
                safe_update["message"] = {
                    k: v for k, v in message.items() if k in {"message_id", "date", "from", "chat"}
                }
                for key in ("text", "caption"):
                    if key in message:
                        safe_update["message"][key] = "[ENCRYPTED]"
            values = dict(
                id=uid(),
                bot_key=bot_key,
                tenant_id=tenant_id,
                update_id=update["update_id"],
                payload=safe_update,
                sensitive_ciphertext=encrypted,
            )
            if fast_polling:
                return store_polling_postgres(session, bot_id, tenant_id, update, values)
            stored, inserted = insert_once(session, TelegramUpdate, values, ["bot_key", "update_id"])
            if not inserted:
                return {"ok": True, "duplicate": True}
            if update.get("pre_checkout_query"):
                # Dedicated fast path; never wait behind campaigns (Telegram has a 10s deadline).
                query = update["pre_checkout_query"]
                valid = (
                    r.payments.precheckout(session, bot, query)
                    if bot
                    else r.billing.precheckout(session, query)
                )
                client = r.clients.child(session, bot) if bot else r.clients.master()
                params = {"pre_checkout_query_id": query["id"], "ok": valid}
                if not valid:
                    params["error_message"] = (
                        "El pedido cambió o ya no está disponible. Crea uno nuevo desde el bot."
                    )
                client.call("answerPreCheckoutQuery", **params)
                stored.status = "DONE"
            else:
                enqueue(
                    session,
                    "UPDATE",
                    tenant_id,
                    {"update_id": stored.id},
                    f"update:{bot_key}:{update['update_id']}",
                    bot_id,
                    stream_key=f"{bot_key}:{(update.get('callback_query', {}).get('from') or message.get('from') or {}).get('id', 'service')}",
                    sequence=update["update_id"] * 100,
                )
        return {"ok": True}
    except IntegrityError:
        # A concurrent insert of the same update is already durable.
        with r.db.system() as session:
            if session.scalar(
                select(TelegramUpdate.id).where(
                    TelegramUpdate.bot_key == bot_key, TelegramUpdate.update_id == update["update_id"]
                )
            ):
                return {"ok": True, "duplicate": True}
        raise
