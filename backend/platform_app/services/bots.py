import secrets
from urllib.parse import quote, urlencode
from sqlalchemy import select, func
from ..models import (
    ManagedBot,
    BotSecret,
    BotSettings,
    BotText,
    BotCreationRequest,
    Channel,
    Plan,
    PlanPrice,
    ProviderConfig,
    TenantMember,
    SaaSPlan,
    now,
    uid,
)
from ..errors import DomainError
from ..security import digest, random_secret, inspect_image, require_role
from .common import audit, enqueue
from .tenants import create_tenant, upsert_user, check_entity_limit, entitlement
from .texts import DEFAULT_TEXTS

MASTER_UPDATES = ["message", "callback_query", "managed_bot", "pre_checkout_query", "subscription"]
CHILD_UPDATES = [
    "message",
    "callback_query",
    "my_chat_member",
    "chat_member",
    "chat_join_request",
    "pre_checkout_query",
    "subscription",
]
BOTFATHER_INSTRUCTIONS = [
    "Abre @BotFather en Telegram.",
    "Abre su Mini App y selecciona el NUEVO Master Bot.",
    "En sus ajustes activa ‘Bot Management Mode’.",
    "Vuelve al panel y pulsa Verificar Master Bot.",
]


class TelegramBotManager:
    def __init__(self, runtime):
        self.r = runtime

    def capabilities(self):
        me = self.r.clients.master().call("getMe")
        enabled = me.get("can_manage_bots") is True
        return {
            "enabled": enabled,
            "username": me.get("username"),
            "telegram_bot_id": me["id"],
            "message": "Bot Management Mode habilitado."
            if enabled
            else "Bot Management Mode no está habilitado.",
            "instructions": [] if enabled else BOTFATHER_INSTRUCTIONS,
        }

    def configure_master(self):
        capability = self.capabilities()
        expected = self.r.settings.master_bot_username.lstrip("@").lower()
        if expected and (capability["username"] or "").lower() != expected:
            raise DomainError(
                "MASTER_BOT_MISMATCH", "El token no corresponde al Master Bot configurado.", 409
            )
        client = self.r.clients.master()
        if self.r.settings.deployment_mode == "telegram":
            client.call("deleteWebhook", drop_pending_updates=False)
            client.call(
                "setMyCommands",
                commands=[
                    {"command": "start", "description": "Mi negocio y mis bots"},
                    {"command": "admin", "description": "Administración de la plataforma"},
                    {"command": "id", "description": "Mi identificador de Telegram"},
                    {"command": "cancel", "description": "Cancelar y volver al inicio"},
                    {"command": "support", "description": "Ayuda y soporte"},
                    {"command": "paysupport", "description": "Ayuda con pagos"},
                ],
            )
            client.call("setChatMenuButton", menu_button={"type": "commands"})
            return capability
        client.call(
            "setWebhook",
            url=f"{self.r.settings.public_api_url}/telegram/webhook/master",
            secret_token=self.r.settings.master_webhook_secret.get_secret_value(),
            allowed_updates=MASTER_UPDATES,
            drop_pending_updates=False,
        )
        client.call(
            "setMyCommands",
            commands=[
                {"command": "start", "description": "Crear y administrar mi negocio"},
                {"command": "paysupport", "description": "Ayuda con pagos de plataforma"},
            ],
        )
        client.call(
            "setChatMenuButton",
            menu_button={
                "type": "web_app",
                "text": "Mi negocio",
                "web_app": {"url": self.r.settings.mini_app_url},
            },
        )
        return capability

    def request_creation(self, session, tenant_id, user, suggested_name, suggested_username):
        capability = self.capabilities()
        if not capability["enabled"]:
            raise DomainError("MANAGEMENT_MODE_DISABLED", capability["message"], 409)
        check_entity_limit(session, tenant_id, "bots", ManagedBot)
        self.check_polling_capacity(session)
        # One active correlation per creator. No tenant supplied by Telegram is trusted.
        active = list(
            session.scalars(
                select(BotCreationRequest).where(
                    BotCreationRequest.telegram_user_id == user.telegram_user_id,
                    BotCreationRequest.expires_at > now(),
                    BotCreationRequest.consumed_bot_id.is_(None),
                )
            )
        )
        for old in active:
            old.expires_at = now()
        request = BotCreationRequest(
            id=uid(),
            tenant_id=tenant_id,
            telegram_user_id=user.telegram_user_id,
            request_id=secrets.randbelow(2**31 - 1),
            expires_at=now() + 1800,
        )
        session.add(request)
        session.flush()
        username = capability["username"]
        link = f"https://t.me/newbot/{quote(username)}/{quote(suggested_username)}?{urlencode({'name': suggested_name})}"
        button = {
            "text": "Crear mi bot",
            "request_managed_bot": {
                "request_id": request.request_id,
                "suggested_name": suggested_name,
                "suggested_username": suggested_username,
            },
        }
        if self.r.settings.deployment_mode == "telegram":
            audit(session, tenant_id, user.id, "BOT_CREATION_REQUESTED", request.id)
            return {"url": link, "keyboard": [[button]], "expires_at": request.expires_at}
        prepared = self.r.clients.master().call(
            "savePreparedKeyboardButton",
            user_id=user.telegram_user_id,
            button={
                "text": "Crear mi bot",
                "request_managed_bot": {
                    "request_id": request.request_id,
                    "suggested_name": suggested_name,
                    "suggested_username": suggested_username,
                },
            },
        )
        audit(session, tenant_id, user.id, "BOT_CREATION_REQUESTED", request.id)
        return {"url": link, "prepared_button_id": prepared["id"], "expires_at": request.expires_at}

    def accept_managed_update(self, session, payload, creator=None, request_id=None):
        info, user_data = payload["bot"], payload.get("user") or creator
        if not info.get("is_bot") or not user_data:
            raise DomainError("INVALID_MANAGED_UPDATE", "Evento de bot no válido.")
        bot = session.scalar(
            select(ManagedBot).where(ManagedBot.telegram_bot_id == info["id"]).with_for_update()
        )
        if bot:
            if bot.owner_telegram_user_id != user_data["id"]:
                # An ownership transfer must never transfer the previous tenant's private records.
                bot.status, bot.published = "OWNERSHIP_CHANGED", False
                bot.health = {"ownership_review_required": True}
                audit(session, bot.tenant_id, "telegram", "BOT_OWNERSHIP_CHANGED", bot.id)
                return bot
            bot.username, bot.name = info.get("username", bot.username), info.get("first_name", bot.name)
            enqueue(
                session, "PROVISION", bot.tenant_id, {"bot_id": bot.id}, f"refresh:{bot.id}:{uid()}", bot.id
            )
            return bot
        user = upsert_user(session, user_data)
        query = select(BotCreationRequest).where(
            BotCreationRequest.telegram_user_id == user.telegram_user_id,
            BotCreationRequest.expires_at > now(),
            BotCreationRequest.consumed_bot_id.is_(None),
        )
        if request_id is not None:
            query = query.where(BotCreationRequest.request_id == request_id)
        pending = list(session.scalars(query.with_for_update()))
        if len(pending) > 1:
            raise DomainError("AMBIGUOUS_CREATION", "Abre de nuevo el asistente de creación.", 409)
        if pending:
            tenant_id = pending[0].tenant_id
            member = session.scalar(
                select(TenantMember).where(
                    TenantMember.tenant_id == tenant_id,
                    TenantMember.user_id == user.id,
                    TenantMember.active.is_(True),
                )
            )
            if user.telegram_user_id not in self.r.settings.owner_ids:
                require_role(member.role if member else "", "configure")
        else:
            # A valid Telegram-created bot may arrive from a shared official deep link.
            tenant_id = create_tenant(
                session, user, f"Negocio de {user.first_name}"[:100], self.r.settings
            ).id
        check_entity_limit(session, tenant_id, "bots", ManagedBot)
        self.check_polling_capacity(session)
        bot = ManagedBot(
            id=uid(),
            tenant_id=tenant_id,
            telegram_bot_id=info["id"],
            owner_telegram_user_id=user.telegram_user_id,
            username=info.get("username", ""),
            name=info["first_name"],
            public_id=uid(),
        )
        session.add(bot)
        session.flush()
        if pending:
            pending[0].consumed_bot_id = bot.id
        enqueue(session, "PROVISION", tenant_id, {"bot_id": bot.id}, f"provision:{bot.id}", bot.id)
        audit(session, tenant_id, user.id, "BOT_CREATED", bot.id)
        return bot

    def check_polling_capacity(self, session):
        if self.r.settings.deployment_mode != "telegram":
            return
        # Serialize capacity checks in PostgreSQL without keeping a connection alive at idle.
        session.scalar(select(SaaSPlan).where(SaaSPlan.name == "STARTER").with_for_update())
        count = session.scalar(
            select(func.count())
            .select_from(ManagedBot)
            .where(ManagedBot.status.not_in(["OWNERSHIP_CHANGED", "SUSPENDED"]))
        )
        if count >= self.r.settings.polling_max_bots:
            raise DomainError(
                "PLATFORM_CAPACITY",
                "La plataforma alcanzó su capacidad inicial. Contacta al administrador.",
                409,
            )

    def refresh_secret(self, session, bot, rotate=False):
        if bot.status == "OWNERSHIP_CHANGED":
            raise DomainError("OWNERSHIP_CHANGED", "Se requiere revisar el cambio de propietario.", 409)
        method = "replaceManagedBotToken" if rotate else "getManagedBotToken"
        # Telegram's user_id here is the bot's own ID, NOT the creator's user ID.
        token = self.r.clients.master().call(method, user_id=bot.telegram_bot_id)
        if not isinstance(token, str) or ":" not in token:
            raise DomainError("INVALID_TOKEN_RESPONSE", "Telegram no devolvió una credencial válida.", 502)
        context = f"{bot.tenant_id}:{bot.id}"
        secret = session.scalar(
            select(BotSecret).where(BotSecret.bot_id == bot.id, BotSecret.tenant_id == bot.tenant_id)
        )
        if not secret:
            webhook = random_secret()
            secret = BotSecret(
                tenant_id=bot.tenant_id,
                bot_id=bot.id,
                token_ciphertext=self.r.vault.encrypt(token, context + ":token"),
                token_last_rotated_at=now(),
                webhook_ciphertext=self.r.vault.encrypt(webhook, context + ":webhook"),
                webhook_secret_hash=digest(webhook),
            )
            session.add(secret)
        elif self.r.vault.decrypt(secret.token_ciphertext, context + ":token") != token:
            secret.token_ciphertext = self.r.vault.encrypt(token, context + ":token")
            secret.token_version += 1
            secret.token_last_rotated_at = now()
            bot.config_version += 1
            audit(
                session, bot.tenant_id, "system", "TOKEN_ROTATED", bot.id, {"version": secret.token_version}
            )
        session.flush()
        return secret


class ManagedBotProvisioner:
    def __init__(self, runtime):
        self.r = runtime

    def provision(self, bot_id, rotate=False):
        # Persist the new credential BEFORE remote webhook configuration. A failed remote
        # operation can be retried with the correct token even after a process restart.
        with self.r.db.system() as session:
            bot = session.get(ManagedBot, bot_id)
            if not bot:
                return
            self.r.manager.refresh_secret(session, bot, rotate)
        try:
            with self.r.db.system() as session:
                bot = session.get(ManagedBot, bot_id)
                client = self.r.clients.child(session, bot)
                me = client.call("getMe")
                if me["id"] != bot.telegram_bot_id:
                    raise DomainError("BOT_ID_MISMATCH", "La identidad del bot no coincide.")
                settings = session.scalar(select(BotSettings).where(BotSettings.bot_id == bot.id))
                if not settings:
                    settings = BotSettings(
                        tenant_id=bot.tenant_id,
                        bot_id=bot.id,
                        commands=[
                            {"command": "start", "description": "Inicio"},
                            {"command": "plans", "description": "Ver planes"},
                            {"command": "support", "description": "Contactar soporte"},
                            {"command": "paysupport", "description": "Ayuda con pagos"},
                            {"command": "stop", "description": "Desactivar campañas"},
                        ],
                    )
                    session.add(settings)
                for key, value in DEFAULT_TEXTS.items():
                    if not session.scalar(
                        select(BotText.id).where(BotText.bot_id == bot.id, BotText.key == key)
                    ):
                        session.add(BotText(tenant_id=bot.tenant_id, bot_id=bot.id, key=key, value=value))
                secret = session.scalar(select(BotSecret).where(BotSecret.bot_id == bot.id))
                webhook_secret = self.r.vault.decrypt(
                    secret.webhook_ciphertext, f"{bot.tenant_id}:{bot.id}:webhook"
                )
                if self.r.settings.deployment_mode == "telegram":
                    client.call("deleteWebhook", drop_pending_updates=False)
                else:
                    client.call(
                        "setWebhook",
                        url=f"{self.r.settings.public_api_url}/telegram/webhook/{bot.public_id}",
                        secret_token=webhook_secret,
                        allowed_updates=CHILD_UPDATES,
                        drop_pending_updates=False,
                    )
                session.flush()
                self.apply_configuration(session, bot, settings)
                bot.status, bot.last_error_code = "READY", None
                if self.r.settings.deployment_mode == "telegram":
                    from .common import send

                    send(
                        session,
                        None,
                        bot.owner_telegram_user_id,
                        f"✅ @{bot.username} está conectado. Abre /start aquí para configurarlo y publicarlo.",
                        f"native-provisioned:{bot.id}",
                    )
                audit(session, bot.tenant_id, "system", "BOT_PROVISIONED", bot.id)
        except DomainError as error:
            with self.r.db.system() as session:
                bot = session.get(ManagedBot, bot_id)
                bot.status, bot.last_error_code = "PROVISIONING_FAILED", error.code
            raise

    def apply_configuration(self, session, bot, settings):
        client = self.r.clients.child(session, bot)
        client.call("setMyName", name=bot.name)
        client.call("setMyDescription", description=settings.description)
        client.call("setMyShortDescription", short_description=settings.short_description)
        client.call("setMyCommands", commands=settings.commands)
        if self.r.settings.deployment_mode == "telegram":
            client.call("setChatMenuButton", menu_button={"type": "commands"})
            return
        client.call(
            "setChatMenuButton",
            menu_button={
                "type": "web_app",
                "text": settings.menu_text,
                "web_app": {"url": f"{self.r.settings.mini_app_url}/b/{bot.public_id}"},
            },
        )

    def photo(self, session, bot, data):
        image = inspect_image(data, self.r.settings.max_upload_bytes)
        self.r.clients.child(session, bot).call(
            "setMyProfilePhoto",
            photo={"type": "static", "photo": "attach://photo"},
            files={"photo": ("profile.jpg", image["bytes"], "image/jpeg")},
        )
        audit(session, bot.tenant_id, "admin", "BOT_PHOTO_CONFIGURED", bot.id)

    def health(self, session, bot, repair=False):
        client = self.r.clients.child(session, bot)
        me, webhook = client.call("getMe"), client.call("getWebhookInfo")
        expected = f"{self.r.settings.public_api_url}/telegram/webhook/{bot.public_id}"
        menu = client.call("getChatMenuButton")
        native = self.r.settings.deployment_mode == "telegram"
        if native:
            expected = ""
        menu_ok = (
            menu.get("type") == "commands"
            if native
            else (menu.get("web_app", {}).get("url") == f"{self.r.settings.mini_app_url}/b/{bot.public_id}")
        )
        good = me["id"] == bot.telegram_bot_id and webhook.get("url") == expected and menu_ok
        if repair and not good:
            enqueue(
                session, "PROVISION", bot.tenant_id, {"bot_id": bot.id}, f"repair:{bot.id}:{uid()}", bot.id
            )
        channels = list(
            session.scalars(
                select(Channel).where(Channel.bot_id == bot.id, Channel.tenant_id == bot.tenant_id)
            )
        )
        for channel in channels:
            self.r.channels.verify(session, bot, channel)
        health = {
            "identity_ok": me["id"] == bot.telegram_bot_id,
            "webhook_ok": webhook.get("url") == expected,
            "menu_ok": menu_ok,
            "transport": "polling" if native else "webhook",
            "pending_updates": webhook.get("pending_update_count", 0),
            "last_webhook_error_at": webhook.get("last_error_date"),
            "channel_permissions_ok": all(c.status == "CONNECTED" for c in channels),
            "checked_at": now(),
        }
        bot.health = health
        if bot.status != "OWNERSHIP_CHANGED":
            bot.status = (
                "READY"
                if good and health["channel_permissions_ok"]
                else "WEBHOOK_ERROR"
                if not good
                else "PERMISSIONS_MISSING"
            )
        return health

    def readiness(self, session, bot):
        settings = session.scalar(select(BotSettings).where(BotSettings.bot_id == bot.id))
        plans = list(session.scalars(select(Plan).where(Plan.bot_id == bot.id, Plan.active.is_(True))))
        stars = session.scalar(
            select(ProviderConfig).where(
                ProviderConfig.tenant_id == bot.tenant_id,
                ProviderConfig.provider == "TELEGRAM_STARS",
                ProviderConfig.enabled.is_(True),
            )
        )
        prices = (
            list(
                session.scalars(
                    select(PlanPrice).where(
                        PlanPrice.plan_id.in_([p.id for p in plans]),
                        PlanPrice.provider == "TELEGRAM_STARS",
                        PlanPrice.currency == "XTR",
                    )
                )
            )
            if plans
            else []
        )
        valid_plans = bool(plans) and all(any(price.plan_id == p.id for price in prices) for p in plans)
        channels = list(session.scalars(select(Channel).where(Channel.bot_id == bot.id)))
        checks = {
            "managed_bot": bot.status != "OWNERSHIP_CHANGED",
            "token": bool(session.scalar(select(BotSecret.id).where(BotSecret.bot_id == bot.id))),
            "webhook": bot.health.get("webhook_ok", False),
            "welcome": bool(
                session.scalar(
                    select(BotText.value).where(BotText.bot_id == bot.id, BotText.key == "WELCOME")
                )
            ),
            "plan": valid_plans,
            "payment_method": bool(stars),
            "channel_permissions": all(c.status == "CONNECTED" for c in channels),
            "support_and_policies": bool(
                settings
                and settings.support_username
                and all(settings.policies.get(x) for x in ["terms", "privacy", "refund"])
            ),
            "test_message": bool(bot.health.get("test_message_sent")),
        }
        return {"checks": checks, "ready": all(checks.values())}

    def publish(self, session, bot, actor_id):
        entitlement(session, bot.tenant_id)
        health = self.health(session, bot)
        self.r.clients.child(session, bot).call(
            "sendMessage",
            chat_id=bot.owner_telegram_user_id,
            text="✅ Prueba de configuración completada. Tu bot está preparado para publicarse.",
        )
        bot.health = {**health, "test_message_sent": True}
        readiness = self.readiness(session, bot)
        if not readiness["ready"]:
            return readiness
        bot.published = True
        audit(session, bot.tenant_id, actor_id, "BOT_PUBLISHED", bot.id)
        return {**readiness, "url": f"https://t.me/{bot.username}"}
