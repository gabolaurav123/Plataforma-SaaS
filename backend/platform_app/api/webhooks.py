import hmac
import json
from copy import deepcopy
from fastapi import APIRouter, Request, Depends
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ..models import ManagedBot, BotSecret, TelegramUpdate, uid
from ..security import digest
from ..errors import DomainError
from ..services.common import enqueue
from .auth import runtime

router = APIRouter()


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
    try:
        with r.db.system() as session:
            bot = session.get(ManagedBot, bot_id) if bot_id else None
            if bot_id and (not bot or bot.tenant_id != tenant_id):
                raise DomainError("BOT_NOT_FOUND", "Bot no disponible.", 404)
            if polling:
                from ..models import PollCursor

                cursor = session.scalar(
                    select(PollCursor).where(PollCursor.bot_key == bot_key).with_for_update()
                )
                if not cursor:
                    cursor = PollCursor(bot_key=bot_key, next_offset=0)
                    session.add(cursor)
                cursor.next_offset = max(cursor.next_offset or 0, update["update_id"] + 1)
            existing = session.scalar(
                select(TelegramUpdate.id).where(
                    TelegramUpdate.bot_key == bot_key, TelegramUpdate.update_id == update["update_id"]
                )
            )
            if existing:
                return {"ok": True, "duplicate": True}
            safe_update, encrypted = deepcopy(update), None
            message = update.get("message", {})
            if message.get("chat", {}).get("type") == "private" and (
                message.get("text") or message.get("caption")
            ):
                encrypted = r.vault.encrypt(json.dumps(update), f"transport:{bot_key}:{update['update_id']}")
                for key in ("text", "caption"):
                    if key in safe_update["message"]:
                        safe_update["message"][key] = "[ENCRYPTED]"
            stored = TelegramUpdate(
                id=uid(),
                bot_key=bot_key,
                tenant_id=tenant_id,
                update_id=update["update_id"],
                payload=safe_update,
                sensitive_ciphertext=encrypted,
            )
            session.add(stored)
            session.flush()
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
