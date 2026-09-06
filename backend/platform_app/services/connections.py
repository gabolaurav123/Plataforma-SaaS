"""Connect existing BotFather bots without ever putting a credential in a job payload."""

import re
from sqlalchemy import select, func
from .. import models as m
from ..db import get_scoped
from ..errors import DomainError
from ..security import random_secret, digest
from .common import enqueue, audit
from .tenants import entitlement

TOKEN = re.compile(r"[1-9][0-9]{4,19}:[A-Za-z0-9_-]{25,100}\Z")


class ConnectionService:
    def __init__(self, runtime):
        self.r = runtime

    def owner(self, db, tenant_id, actor_id):
        tenant = db.get(m.Tenant, tenant_id)
        if not tenant or tenant.owner_user_id != actor_id:
            raise DomainError("OWNER_REQUIRED", "Solo el propietario puede conectar o desconectar bots.", 403)
        return tenant

    def request(self, db, tenant_id, actor, token, key, replace_bot_id=None):
        self.owner(db, tenant_id, actor.id)
        entitlement(db, tenant_id)
        if not TOKEN.fullmatch(token.strip()):
            raise DomainError(
                "INVALID_BOT_TOKEN",
                "El token no tiene el formato de BotFather. Vuelve a copiarlo sin espacios.",
            )
        previous = db.scalar(
            select(m.ConnectionAttempt).where(
                m.ConnectionAttempt.tenant_id == tenant_id, m.ConnectionAttempt.request_key == key
            )
        )
        if previous:
            return previous
        if replace_bot_id:
            get_scoped(db, m.ManagedBot, replace_bot_id, tenant_id)
        attempt = m.ConnectionAttempt(
            id=m.uid(),
            tenant_id=tenant_id,
            actor_id=actor.id,
            request_key=key,
            replace_bot_id=replace_bot_id,
            expires_at=m.now() + 900,
        )
        attempt.token_ciphertext = self.r.vault.encrypt(token.strip(), f"{tenant_id}:{attempt.id}:connection")
        db.add(attempt)
        db.flush()
        enqueue(
            db,
            "VALIDATE_CONNECTION",
            tenant_id,
            {"attempt_id": attempt.id},
            "validate-connection:" + attempt.id,
        )
        audit(db, tenant_id, actor.id, "BOT_CONNECTION_REQUESTED", attempt.id)
        return attempt

    def validate(self, db, attempt):
        from .console import Console

        self.owner(db, attempt.tenant_id, attempt.actor_id)
        if attempt.status != "PENDING" or attempt.expires_at <= m.now():
            attempt.token_ciphertext = None
            return
        user = db.get(m.PlatformUser, attempt.actor_id)
        ui = Console(
            self.r,
            db,
            None,
            {"update_id": -int(attempt.id.replace("-", "")[:12], 16)},
            {"id": user.telegram_user_id},
        )
        token = self.r.vault.decrypt(attempt.token_ciphertext, f"{attempt.tenant_id}:{attempt.id}:connection")
        client = self.r.clients.factory(token, self.r.settings.telegram_test_environment)
        try:
            me = client.call("getMe")
            master_id = int(self.r.settings.master_bot_token.get_secret_value().split(":")[0])
            if not me.get("is_bot") or me["id"] == master_id:
                raise DomainError(
                    "MASTER_CONNECTION_FORBIDDEN", "Conecta el bot de tu negocio, no el bot maestro."
                )
            occupied = db.scalar(select(m.ManagedBot).where(m.ManagedBot.telegram_bot_id == me["id"]))
            if occupied and occupied.tenant_id != attempt.tenant_id:
                raise DomainError(
                    "BOT_ALREADY_CONNECTED",
                    "Este bot ya está registrado en otra cuenta. Contacta soporte.",
                    409,
                )
            if occupied and attempt.replace_bot_id and occupied.id != attempt.replace_bot_id:
                raise DomainError(
                    "BOT_ID_MISMATCH",
                    "El token pertenece a otro bot de tu cuenta. Selecciona ese bot para reemplazar su token.",
                    409,
                )
            webhook = client.call("getWebhookInfo")
            attempt.candidate = {
                "id": me["id"],
                "name": me.get("first_name", "Bot")[:64],
                "username": me.get("username", ""),
                "has_webhook": bool(webhook.get("url")),
                "existing_id": occupied.id if occupied else None,
            }
            attempt.status = "VALIDATED"
            ui.say(
                ui.t(
                    "connection_valid",
                    name=attempt.candidate["name"],
                    username=attempt.candidate["username"],
                    identifier=me["id"],
                )
                + ui.t("replace_webhook" if webhook.get("url") else "stop_other_polling"),
                [
                    [
                        ui.button(
                            ui.t("confirm_connection"),
                            "connect_confirm",
                            tid=attempt.tenant_id,
                            id=attempt.id,
                        )
                    ],
                    [ui.button(ui.t("cancel"), "connect_cancel", tid=attempt.tenant_id, id=attempt.id)],
                ],
            )
        except DomainError as error:
            attempt.status, attempt.error_code, attempt.token_ciphertext = "REJECTED", error.code, None
            from .i18n import error_text

            ui.say(
                ui.t(
                    "connection_failed",
                    reason=error_text(error, ui.language)
                    if error.code != "TOKEN_INVALID"
                    else ui.t("token_invalid"),
                )
            )
        finally:
            if hasattr(client, "close"):
                client.close()

    def confirm(self, db, attempt_id, tenant_id, actor):
        self.owner(db, tenant_id, actor.id)
        _, _, plan = entitlement(db, tenant_id)
        attempt = db.scalar(
            select(m.ConnectionAttempt)
            .where(m.ConnectionAttempt.id == attempt_id, m.ConnectionAttempt.tenant_id == tenant_id)
            .with_for_update()
        )
        if not attempt or attempt.actor_id != actor.id or attempt.expires_at <= m.now():
            raise DomainError("CONNECTION_EXPIRED", "La solicitud caducó. Vuelve a conectar tu bot.", 409)
        if attempt.status == "CONNECTED":
            return db.get(m.ManagedBot, attempt.candidate["connected_id"])
        if attempt.status != "VALIDATED" or not attempt.token_ciphertext:
            raise DomainError("CONNECTION_NOT_VALIDATED", "Espera la validación del token.", 409)
        # Global capacity and tenant quota are serialized against concurrent onboarding.
        db.scalar(select(m.SaaSPlan).order_by(m.SaaSPlan.id).limit(1).with_for_update())
        db.scalar(select(m.Tenant).where(m.Tenant.id == tenant_id).with_for_update())
        info = attempt.candidate
        bot = db.scalar(
            select(m.ManagedBot).where(m.ManagedBot.telegram_bot_id == info["id"]).with_for_update()
        )
        if bot and bot.tenant_id != tenant_id:
            raise DomainError("BOT_ALREADY_CONNECTED", "Este bot ya está registrado en otra cuenta.", 409)
        old = (
            get_scoped(db, m.ManagedBot, attempt.replace_bot_id, tenant_id)
            if attempt.replace_bot_id
            else None
        )
        if not bot or bot.status in {"DISCONNECTED", "OWNERSHIP_CHANGED"}:
            active = (
                select(func.count())
                .select_from(m.ManagedBot)
                .where(m.ManagedBot.status.not_in(["DISCONNECTED", "OWNERSHIP_CHANGED"]))
            )
            if db.scalar(active.where(m.ManagedBot.tenant_id == tenant_id)) - int(
                bool(old and old.status != "DISCONNECTED")
            ) >= plan.limits.get("bots", 1):
                raise DomainError("PLAN_LIMIT", "Alcanzaste el límite de bots de tu plan.", 409)
            if (
                self.r.settings.telegram_transport == "polling"
                and db.scalar(active) >= self.r.settings.polling_max_bots
                and not old
            ):
                raise DomainError(
                    "PLATFORM_CAPACITY",
                    "La plataforma necesita ampliar su capacidad antes de conectar más bots.",
                    409,
                )
        if not bot:
            bot = m.ManagedBot(
                id=m.uid(),
                tenant_id=tenant_id,
                telegram_bot_id=info["id"],
                owner_telegram_user_id=actor.telegram_user_id,
                public_id=m.uid(),
                username=info["username"],
                name=info["name"],
                connection_kind="TOKEN",
            )
            db.add(bot)
            db.flush()
        if old and old.id != bot.id:
            self.disconnect(db, old, actor)
        token = self.r.vault.decrypt(attempt.token_ciphertext, f"{tenant_id}:{attempt.id}:connection")
        secret = db.scalar(
            select(m.BotSecret)
            .where(m.BotSecret.bot_id == bot.id, m.BotSecret.tenant_id == tenant_id)
            .with_for_update()
        )
        context = f"{tenant_id}:{bot.id}"
        if not secret:
            webhook = random_secret()
            secret = m.BotSecret(
                tenant_id=tenant_id,
                bot_id=bot.id,
                token_ciphertext={},
                webhook_ciphertext=self.r.vault.encrypt(webhook, context + ":webhook"),
                webhook_secret_hash=digest(webhook),
                token_version=1,
                token_last_rotated_at=m.now(),
            )
            db.add(secret)
        else:
            secret.token_version += 1
        secret.token_ciphertext = self.r.vault.encrypt(token, context + ":token")
        secret.token_last_rotated_at = m.now()
        bot.connection_kind, bot.status, bot.disconnected_at, bot.last_error_code = (
            "TOKEN",
            "PROVISIONING",
            None,
            None,
        )
        bot.config_version += 1
        attempt.candidate = {**info, "connected_id": bot.id}
        attempt.status, attempt.token_ciphertext = "CONNECTED", None
        enqueue(db, "PROVISION", tenant_id, {}, "connect-provision:" + attempt.id, bot.id)
        audit(
            db,
            tenant_id,
            actor.id,
            "BOT_CONNECTED",
            bot.id,
            {"token_version": secret.token_version, "connection_kind": "TOKEN"},
        )
        return bot

    def disconnect(self, db, bot, actor):
        self.owner(db, bot.tenant_id, actor.id)
        bot.status, bot.disconnected_at, bot.published = "DISCONNECTED", m.now(), False
        bot.config_version += 1
        audit(db, bot.tenant_id, actor.id, "BOT_DISCONNECTED", bot.id)
        db.info["bots_changed"] = True

    def cancel(self, db, attempt, actor):
        self.owner(db, attempt.tenant_id, actor.id)
        if attempt.status not in {"CONNECTED", "CANCELLED"}:
            attempt.status, attempt.token_ciphertext = "CANCELLED", None
