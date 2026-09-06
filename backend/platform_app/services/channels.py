from sqlalchemy import select
from ..models import Channel, Contact, Plan, Subscription, ChannelInvite, BotSettings, now, uid
from ..errors import DomainError
from .common import audit, emit, send


class ChannelService:
    def __init__(self, runtime):
        self.r = runtime

    def connect_link(self, bot):
        return f"https://t.me/{bot.username}?startchannel&admin=invite_users+restrict_members"

    def connect_from_update(self, session, bot, change):
        # Being added by an arbitrary channel administrator cannot hijack a creator's bot.
        chat = change["chat"]
        if chat["type"] != "channel":
            return None
        channel = session.scalar(
            select(Channel).where(Channel.bot_id == bot.id, Channel.telegram_chat_id == chat["id"])
        )
        if not channel:
            if change.get("from", {}).get("id") != bot.owner_telegram_user_id:
                return None
            if session.scalar(
                select(Channel.id).where(Channel.telegram_chat_id == chat["id"], Channel.bot_id != bot.id)
            ):
                raise DomainError(
                    "CHANNEL_ALREADY_MANAGED",
                    "Este canal ya está conectado a otro bot de la plataforma.",
                    409,
                )
            channel = Channel(
                id=uid(),
                tenant_id=bot.tenant_id,
                bot_id=bot.id,
                telegram_chat_id=chat["id"],
                title=chat["title"],
                username=chat.get("username"),
            )
            session.add(channel)
            session.flush()
        self.verify(session, bot, channel)
        audit(session, bot.tenant_id, str(bot.owner_telegram_user_id), "CHANNEL_CONNECTED", channel.id)
        return channel

    def verify(self, session, bot, channel):
        client = self.r.clients.child(session, bot)
        member = client.call("getChatMember", chat_id=channel.telegram_chat_id, user_id=bot.telegram_bot_id)
        settings = session.scalar(select(BotSettings).where(BotSettings.bot_id == bot.id))
        required = ["can_invite_users"]
        if channel.access_mode == "PLATFORM" and (not settings or settings.remove_expired_members):
            required.append("can_restrict_members")
        missing = [x for x in required if not member.get(x)]
        if member.get("status") not in {"administrator", "creator"}:
            missing.insert(0, "administrator")
        channel.permissions = {x: bool(member.get(x)) for x in required}
        channel.status = "PERMISSIONS_MISSING" if missing else "CONNECTED"
        if not missing:
            channel.connected_at = channel.connected_at or now()
        return {"connected": not missing, "missing": missing, "permissions": channel.permissions}

    def grant(self, session, bot, subscription):
        if subscription.status != "ACTIVE" or subscription.expires_at <= now():
            return
        plan = session.get(Plan, subscription.plan_id)
        if not plan.channel_id:
            return
        channel = session.get(Channel, plan.channel_id)
        if channel.access_mode != "PLATFORM":
            return
        contact = session.get(Contact, subscription.contact_id)
        if not self.verify(session, bot, channel)["connected"]:
            raise DomainError("PERMISSIONS_MISSING", "Faltan permisos en el canal.", 409)
        previous = session.scalar(
            select(ChannelInvite).where(
                ChannelInvite.subscription_id == subscription.id,
                ChannelInvite.expires_at > now(),
                ChannelInvite.revoked_at.is_(None),
                ChannelInvite.used_at.is_(None),
            )
        )
        client = self.r.clients.child(session, bot)
        if not previous:
            client.call(
                "unbanChatMember",
                chat_id=channel.telegram_chat_id,
                user_id=contact.telegram_user_id,
                only_if_banned=True,
            )
            result = client.call(
                "createChatInviteLink",
                chat_id=channel.telegram_chat_id,
                name=subscription.id[:32],
                expire_date=min(now() + 3600, subscription.expires_at),
                creates_join_request=True,
            )
            previous = ChannelInvite(
                tenant_id=bot.tenant_id,
                channel_id=channel.id,
                contact_id=contact.id,
                subscription_id=subscription.id,
                invite_link=result["invite_link"],
                expires_at=min(now() + 3600, subscription.expires_at),
            )
            session.add(previous)
        send(
            session,
            bot,
            contact.telegram_user_id,
            "✅ Tu membresía está activa. Solicita acceso con tu enlace personal:",
            f"access-message:{subscription.id}:{subscription.expires_at}",
            reply_markup={"inline_keyboard": [[{"text": "Entrar al canal", "url": previous.invite_link}]]},
        )

    def join_request(self, session, bot, update):
        channel = session.scalar(
            select(Channel).where(Channel.bot_id == bot.id, Channel.telegram_chat_id == update["chat"]["id"])
        )
        if not channel or channel.access_mode != "PLATFORM":
            return
        invite = session.scalar(
            select(ChannelInvite).where(
                ChannelInvite.tenant_id == bot.tenant_id,
                ChannelInvite.channel_id == channel.id,
                ChannelInvite.invite_link == update.get("invite_link", {}).get("invite_link"),
            )
        )
        contact = session.get(Contact, invite.contact_id) if invite else None
        sub = session.get(Subscription, invite.subscription_id) if invite else None
        valid = bool(
            invite
            and contact.telegram_user_id == update["from"]["id"]
            and sub.status == "ACTIVE"
            and sub.expires_at > now()
            and invite.expires_at > now()
            and not invite.revoked_at
            and not invite.used_at
        )
        client = self.r.clients.child(session, bot)
        client.call(
            "approveChatJoinRequest" if valid else "declineChatJoinRequest",
            chat_id=channel.telegram_chat_id,
            user_id=update["from"]["id"],
        )
        if valid:
            invite.used_at = now()
            client.call(
                "revokeChatInviteLink", chat_id=channel.telegram_chat_id, invite_link=invite.invite_link
            )
            invite.revoked_at = now()
            emit(session, bot.tenant_id, "CHANNEL_ACCESS_GRANTED", f"join:{invite.id}", bot.id, contact.id)

    def revoke(self, session, bot, subscription):
        plan = session.get(Plan, subscription.plan_id)
        if not plan.channel_id:
            return
        channel = session.get(Channel, plan.channel_id)
        settings = session.scalar(select(BotSettings).where(BotSettings.bot_id == bot.id))
        if channel.access_mode != "PLATFORM" or (settings and not settings.remove_expired_members):
            return
        # Another active entitlement for this channel must preserve access.
        other = session.scalar(
            select(Subscription.id)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(
                Subscription.tenant_id == bot.tenant_id,
                Subscription.contact_id == subscription.contact_id,
                Subscription.status == "ACTIVE",
                Subscription.expires_at > now(),
                Plan.channel_id == channel.id,
            )
        )
        if other:
            return
        contact = session.get(Contact, subscription.contact_id)
        client = self.r.clients.child(session, bot)
        member = client.call(
            "getChatMember", chat_id=channel.telegram_chat_id, user_id=contact.telegram_user_id
        )
        if member["status"] in {"creator", "administrator"}:
            audit(session, bot.tenant_id, "system", "CHANNEL_REVOKE_ADMIN_SKIPPED", subscription.id)
            return
        if member["status"] not in {"left", "kicked"}:
            client.call("banChatMember", chat_id=channel.telegram_chat_id, user_id=contact.telegram_user_id)
        for invite in session.scalars(
            select(ChannelInvite).where(
                ChannelInvite.channel_id == channel.id,
                ChannelInvite.contact_id == contact.id,
                ChannelInvite.revoked_at.is_(None),
            )
        ):
            client.call(
                "revokeChatInviteLink", chat_id=channel.telegram_chat_id, invite_link=invite.invite_link
            )
            invite.revoked_at = now()
        emit(
            session,
            bot.tenant_id,
            "CHANNEL_ACCESS_REVOKED",
            f"revoke:{subscription.id}:{subscription.expires_at}",
            bot.id,
            contact.id,
        )

    def native_subscription(self, session, bot, channel, price):
        if not 1 <= price <= 10000:
            raise DomainError("INVALID_STARS_AMOUNT", "El precio debe estar entre 1 y 10.000 Stars.")
        # Never switch a live platform-managed channel with existing plans.
        if session.scalar(select(Plan.id).where(Plan.channel_id == channel.id)):
            raise DomainError(
                "CHANNEL_IN_USE", "Usa un canal sin planes propios para suscripción nativa.", 409
            )
        result = self.r.clients.child(session, bot).call(
            "createChatSubscriptionInviteLink",
            chat_id=channel.telegram_chat_id,
            subscription_period=2592000,
            subscription_price=price,
        )
        channel.access_mode, channel.native_invite_link = "TELEGRAM_NATIVE", result["invite_link"]
        return {"url": channel.native_invite_link, "mode": "TELEGRAM_NATIVE", "managed_by": "TELEGRAM"}
