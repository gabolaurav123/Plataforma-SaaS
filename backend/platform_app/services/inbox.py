"""Native Telegram replies, bound to the actual bot, recipient and delivered message."""

from sqlalchemy import select
from .. import models as m
from ..errors import DomainError
from ..security import redact
from .common import send, audit
from . import crm
from .i18n import t

MEDIA_METHODS = {
    "photo": "sendPhoto",
    "video": "sendVideo",
    "document": "sendDocument",
    "audio": "sendAudio",
    "voice": "sendVoice",
    "animation": "sendAnimation",
    "sticker": "sendSticker",
    "video_note": "sendVideoNote",
}
CAPTION_MEDIA = {"photo", "video", "document", "audio", "voice", "animation"}


def media_from(message):
    for kind in MEDIA_METHODS:
        value = message.get(kind)
        if value:
            return {"kind": kind, "file_id": (value[-1] if kind == "photo" else value)["file_id"]}
    return {}


def receive(ui, person, message):
    media = media_from(message)
    text = redact(message.get("text") or message.get("caption") or "")
    if not text and not media:
        ui.say(ui.t("inbox_supported"))
        return
    incoming = crm.incoming(ui.db, ui.bot, person, text or "[" + media["kind"] + "]", message["message_id"])
    incoming.media = media
    ui.db.flush()
    from .notifications import admins

    for user in admins(ui.db, ui.bot, "support"):
        header = t(
            "inbox_incoming",
            user.locale,
            name=person.first_name,
            username="@" + person.username if person.username else "—",
            user_id=person.telegram_user_id,
        )
        for part in ["text", "media"] if media else ["text"]:
            delivery = m.InboxDelivery(
                id=m.uid(),
                tenant_id=ui.bot.tenant_id,
                bot_id=ui.bot.id,
                message_id=incoming.id,
                viewer_id=user.telegram_user_id,
                part=part,
            )
            ui.db.add(delivery)
            send(
                ui.db,
                ui.bot,
                user.telegram_user_id,
                (header + "\n\n" + incoming.text)[:4096] if part == "text" else header[:1024],
                f"inbox-delivery:{incoming.id}:{user.id}:{part}",
                inbox_delivery_id=delivery.id,
                media=media if part == "media" else None,
                service_message=True,
                admin_permission="support",
                viewer_id=user.telegram_user_id,
            )
    ui.say(ui.t("received"))


def native_reply(ui, message):
    target = message.get("reply_to_message", {}).get("message_id")
    if not ui.bot or not target:
        return False
    delivery = ui.db.scalar(
        select(m.InboxDelivery).where(
            m.InboxDelivery.bot_id == ui.bot.id,
            m.InboxDelivery.tenant_id == ui.bot.tenant_id,
            m.InboxDelivery.viewer_id == ui.actor["id"],
            m.InboxDelivery.telegram_message_id == target,
            m.InboxDelivery.status == "SENT",
        )
    )
    if not delivery:
        return False
    # Recheck current permissions, including custom roles and revocations.
    ui.ctx(ui.bot.tenant_id, "support")
    ui.render_admin = True
    original = ui.db.get(m.Message, delivery.message_id)
    conv = ui.entity(m.Conversation, ui.bot.tenant_id, original.conversation_id, "support")
    media = media_from(message)
    text = redact(message.get("text") or message.get("caption") or "")
    if not text and not media:
        raise DomainError("INBOX_MEDIA", ui.t("inbox_supported"))
    outgoing = crm.reply(
        ui.db,
        ui.bot,
        conv,
        ui.user.id,
        text,
        f"native:{ui.bot.id}:{ui.update['update_id']}",
        media=media,
        actor_telegram_id=ui.actor["id"],
    )
    audit(
        ui.db,
        ui.bot.tenant_id,
        ui.user.id,
        "INBOX_NATIVE_REPLY",
        outgoing.id,
        {"bot_id": ui.bot.id, "delivery_id": delivery.id},
    )
    ui.say(ui.t("inbox_reply_queued"))
    return True
