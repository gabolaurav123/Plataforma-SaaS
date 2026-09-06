from dataclasses import dataclass
from fastapi import Request, Depends
from sqlalchemy import select
from ..models import AuthSession, TenantMember, ManagedBot, BotSecret, now
from ..security import digest, random_secret, validate_init_data, require_role
from ..errors import DomainError
from ..services.tenants import upsert_user, entitlement
from ..services.common import audit


def runtime(request: Request):
    return request.app.state.runtime


def login(r, init_data, bot_public_id=None):
    with r.db.system() as session:
        bot = None
        token = r.settings.master_bot_token.get_secret_value()
        if bot_public_id:
            bot = session.scalar(select(ManagedBot).where(ManagedBot.public_id == bot_public_id))
            if not bot or bot.status == "OWNERSHIP_CHANGED":
                raise DomainError("BOT_UNAVAILABLE", "Bot no disponible.", 404)
            secret = session.scalar(select(BotSecret).where(BotSecret.bot_id == bot.id))
            if not secret or not r.vault:
                raise DomainError("BOT_UNAVAILABLE", "Bot no disponible.", 409)
            token = r.vault.decrypt(secret.token_ciphertext, f"{bot.tenant_id}:{bot.id}:token")
        data = validate_init_data(init_data, token, r.settings.init_data_max_age_seconds)
        user = upsert_user(session, data) if not bot else None
        plain = random_secret()
        auth = AuthSession(
            token_hash=digest(plain),
            telegram_user_id=data["id"],
            user_id=user.id if user else None,
            bot_id=bot.id if bot else None,
            kind="CUSTOMER" if bot else "MASTER",
            expires_at=now() + r.settings.session_ttl_seconds,
        )
        session.add(auth)
        audit(session, bot.tenant_id if bot else None, str(data["id"]), "LOGIN")
        return {
            "access_token": plain,
            "expires_in": r.settings.session_ttl_seconds,
            "kind": auth.kind,
            "user": {
                "id": data["id"],
                "first_name": data.get("first_name", ""),
                "username": data.get("username"),
            },
        }


def authenticate(request: Request, r=Depends(runtime)):
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise DomainError("AUTH_REQUIRED", "Abre el panel desde Telegram.", 401)
    with r.db.system() as session:
        auth = session.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == digest(header[7:]), AuthSession.expires_at > now()
            )
        )
        if not auth:
            raise DomainError("SESSION_EXPIRED", "Tu sesión terminó. Abre de nuevo la Mini App.", 401)
        return auth


def master(auth=Depends(authenticate)):
    if auth.kind != "MASTER":
        raise DomainError("MASTER_REQUIRED", "Acceso de creador requerido.", 403)
    return auth


@dataclass
class TenantContext:
    tenant_id: str
    user_id: str
    telegram_user_id: int
    role: str


def tenant_context(workspace_id: str, auth=Depends(master), r=Depends(runtime)):
    with r.db.system() as session:
        membership = session.scalar(
            select(TenantMember).where(
                TenantMember.tenant_id == workspace_id,
                TenantMember.user_id == auth.user_id,
                TenantMember.active.is_(True),
            )
        )
        if not membership:
            raise DomainError("WORKSPACE_NOT_FOUND", "Espacio no disponible.", 404)
        return TenantContext(workspace_id, auth.user_id, auth.telegram_user_id, membership.role)


def permit(ctx, permission, session=None):
    require_role(ctx.role, permission)
    if session is not None and permission not in {"read", "billing", "export"}:
        entitlement(session, ctx.tenant_id)


def customer(public_id: str, auth=Depends(authenticate), r=Depends(runtime)):
    if auth.kind != "CUSTOMER":
        raise DomainError("CUSTOMER_REQUIRED", "Abre la Mini App del bot correspondiente.", 403)
    with r.db.system() as session:
        bot = session.scalar(
            select(ManagedBot).where(ManagedBot.public_id == public_id, ManagedBot.id == auth.bot_id)
        )
        if not bot or bot.status == "OWNERSHIP_CHANGED":
            raise DomainError("BOT_NOT_FOUND", "Bot no disponible.", 404)
        return bot, auth


def platform_owner(auth=Depends(master), r=Depends(runtime)):
    if auth.telegram_user_id not in r.settings.owner_ids:
        raise DomainError("OWNER_REQUIRED", "Acceso de plataforma requerido.", 403)
    return auth
