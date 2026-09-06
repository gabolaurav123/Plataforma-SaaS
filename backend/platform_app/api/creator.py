import json
from fastapi import APIRouter, Depends, UploadFile, File, Query, Response
from sqlalchemy import select
from .. import models as m
from ..db import get_scoped
from ..errors import DomainError
from ..services import tenants, crm
from ..services.common import audit, enqueue
from ..services.texts import DEFAULT_TEXTS, TEMPLATES
from .auth import runtime, master, tenant_context, permit, login
from .serialization import public
from . import schemas as s

router = APIRouter(prefix="/api")


@router.post("/auth/master")
def auth_master(body: s.Login, r=Depends(runtime)):
    return login(r, body.init_data)


@router.get("/me")
def me(auth=Depends(master), r=Depends(runtime)):
    with r.db.system() as db:
        memberships = list(
            db.scalars(
                select(m.TenantMember).where(
                    m.TenantMember.user_id == auth.user_id, m.TenantMember.active.is_(True)
                )
            )
        )
        return {
            "user": public(db.get(m.PlatformUser, auth.user_id)),
            "platform_owner": auth.telegram_user_id in r.settings.owner_ids,
            "workspaces": [
                {"id": x.tenant_id, "name": db.get(m.Tenant, x.tenant_id).name, "role": x.role}
                for x in memberships
            ],
        }


@router.post("/workspaces", status_code=201)
def workspace(body: s.TenantCreate, auth=Depends(master), r=Depends(runtime)):
    with r.db.system() as db:
        return public(tenants.create_tenant(db, db.get(m.PlatformUser, auth.user_id), body.name, r.settings))


@router.get("/saas-plans")
def saas_plans(auth=Depends(master), r=Depends(runtime)):
    with r.db.system() as db:
        return [public(x) for x in db.scalars(select(m.SaaSPlan).where(m.SaaSPlan.active.is_(True)))]


@router.get("/t/{workspace_id}/onboarding")
def onboarding(ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        return public(db.scalar(select(m.Onboarding).where(m.Onboarding.user_id == ctx.user_id)))


@router.put("/t/{workspace_id}/onboarding")
def save_onboarding(body: s.WizardSave, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        if body.bot_id:
            get_scoped(db, m.ManagedBot, body.bot_id, ctx.tenant_id)
        row = db.scalar(select(m.Onboarding).where(m.Onboarding.user_id == ctx.user_id))
        if not row:
            row = m.Onboarding(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
            db.add(row)
        row.step, row.data = body.step, {"bot_id": body.bot_id, "template": body.template}
        return {"saved": True, "step": row.step}


@router.get("/t/{workspace_id}/templates")
def templates(ctx=Depends(tenant_context)):
    return TEMPLATES


@router.get("/t/{workspace_id}/text-defaults")
def text_defaults(ctx=Depends(tenant_context)):
    return DEFAULT_TEXTS


@router.post("/t/{workspace_id}/bots/create")
def create_bot(body: s.BotCreate, ctx=Depends(tenant_context), r=Depends(runtime)):
    permit(ctx, "configure")
    if not r.vault:
        raise DomainError("VAULT_NOT_CONFIGURED", "El propietario debe configurar el cifrado.", 503)
    # Trusted system transaction: cancel all previous pending correlations for this verified user.
    with r.db.system() as db:
        user = db.get(m.PlatformUser, ctx.user_id)
        return r.manager.request_creation(db, ctx.tenant_id, user, body.name, body.username)


@router.get("/t/{workspace_id}/bots/{bot_id}/settings")
def bot_settings(bot_id: str, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        bot = get_scoped(db, m.ManagedBot, bot_id, ctx.tenant_id)
        config = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
        return {
            "bot": public(bot),
            "settings": public(config),
            "texts": [public(x) for x in db.scalars(select(m.BotText).where(m.BotText.bot_id == bot.id))],
        }


@router.put("/t/{workspace_id}/bots/{bot_id}/settings")
def update_bot(bot_id: str, body: s.BotConfig, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        bot = get_scoped(db, m.ManagedBot, bot_id, ctx.tenant_id)
        config = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
        if not config:
            raise DomainError("BOT_NOT_READY", "Completa primero la configuración del bot.", 409)
        bot.name, bot.config_version = body.name, bot.config_version + 1
        for field in [
            "description",
            "short_description",
            "menu_text",
            "support_username",
            "remove_expired_members",
        ]:
            setattr(config, field, getattr(body, field))
        config.commands = [x.model_dump() for x in body.commands]
        config.branding = {"color": body.brand_color}
        config.policies = {x: getattr(body, x) for x in ["terms", "privacy", "refund"]}
        enqueue(db, "CONFIGURE", ctx.tenant_id, {}, f"config:{bot.id}:{bot.config_version}", bot.id)
        audit(db, ctx.tenant_id, ctx.user_id, "BOT_CONFIGURED", bot.id)
        return {"saved": True, "sync_status": "QUEUED"}


@router.post("/t/{workspace_id}/bots/{bot_id}/photo")
def upload_photo(bot_id: str, file: UploadFile = File(...), ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        bot = get_scoped(db, m.ManagedBot, bot_id, ctx.tenant_id)
        r.provisioner.photo(db, bot, file.file.read(r.settings.max_upload_bytes + 1))
        return {"saved": True}


@router.put("/t/{workspace_id}/bots/{bot_id}/texts/{key}")
def text_save(bot_id: str, key: str, body: s.TextSave, ctx=Depends(tenant_context), r=Depends(runtime)):
    if key not in DEFAULT_TEXTS:
        raise DomainError("UNKNOWN_TEXT", "Texto no válido.")
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        bot = get_scoped(db, m.ManagedBot, bot_id, ctx.tenant_id)
        row = db.scalar(select(m.BotText).where(m.BotText.bot_id == bot.id, m.BotText.key == key))
        if not row:
            row = m.BotText(tenant_id=ctx.tenant_id, bot_id=bot.id, key=key, value=body.value)
            db.add(row)
        row.value = body.value
        bot.config_version += 1
        audit(db, ctx.tenant_id, ctx.user_id, "BOT_TEXT_CONFIGURED", bot.id, {"key": key})
        return {"saved": True, "default": DEFAULT_TEXTS[key]}


@router.post("/t/{workspace_id}/bots/{bot_id}/repair")
def repair(bot_id: str, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        bot = get_scoped(db, m.ManagedBot, bot_id, ctx.tenant_id)
        job = enqueue(
            db, "PROVISION", ctx.tenant_id, {"bot_id": bot.id}, f"repair:{bot.id}:{m.uid()}", bot.id
        )
        return {"job_id": job.id, "status": "QUEUED"}


@router.post("/t/{workspace_id}/bots/{bot_id}/rotate-token")
def rotate(bot_id: str, ctx=Depends(tenant_context), r=Depends(runtime)):
    permit(ctx, "team")
    with r.db.tenant(ctx.tenant_id) as db:
        bot = get_scoped(db, m.ManagedBot, bot_id, ctx.tenant_id)
        enqueue(
            db,
            "PROVISION",
            ctx.tenant_id,
            {"bot_id": bot.id, "rotate": True},
            f"rotate:{bot.id}:{m.uid()}",
            bot.id,
        )
        audit(db, ctx.tenant_id, ctx.user_id, "TOKEN_ROTATION_REQUESTED", bot.id)
        return {"status": "QUEUED"}


@router.get("/t/{workspace_id}/bots/{bot_id}/access")
def access(bot_id: str, ctx=Depends(tenant_context), r=Depends(runtime)):
    permit(ctx, "configure")
    with r.db.tenant(ctx.tenant_id) as db:
        bot = get_scoped(db, m.ManagedBot, bot_id, ctx.tenant_id)
        return r.clients.master().call("getManagedBotAccessSettings", user_id=bot.telegram_bot_id)


@router.put("/t/{workspace_id}/bots/{bot_id}/access")
def access_save(bot_id: str, body: s.AccessSettings, ctx=Depends(tenant_context), r=Depends(runtime)):
    permit(ctx, "team")
    with r.db.tenant(ctx.tenant_id) as db:
        bot = get_scoped(db, m.ManagedBot, bot_id, ctx.tenant_id)
        result = r.clients.master().call(
            "setManagedBotAccessSettings", user_id=bot.telegram_bot_id, **body.model_dump()
        )
        audit(db, ctx.tenant_id, ctx.user_id, "BOT_ACCESS_CONFIGURED", bot.id)
        return {"saved": result, "owner_always_has_access": True}


@router.get("/t/{workspace_id}/bots/{bot_id}/readiness")
def readiness(bot_id: str, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        return r.provisioner.readiness(db, get_scoped(db, m.ManagedBot, bot_id, ctx.tenant_id))


@router.post("/t/{workspace_id}/bots/{bot_id}/publish")
def publish(bot_id: str, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        return r.provisioner.publish(db, get_scoped(db, m.ManagedBot, bot_id, ctx.tenant_id), ctx.user_id)


@router.get("/t/{workspace_id}/bots/{bot_id}/connect-channel")
def channel_link(bot_id: str, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        return {"url": r.channels.connect_link(get_scoped(db, m.ManagedBot, bot_id, ctx.tenant_id))}


@router.post("/t/{workspace_id}/channels/{channel_id}/test")
def channel_test(channel_id: str, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        channel = get_scoped(db, m.Channel, channel_id, ctx.tenant_id)
        return r.channels.verify(db, get_scoped(db, m.ManagedBot, channel.bot_id, ctx.tenant_id), channel)


@router.post("/t/{workspace_id}/channels/{channel_id}/native-subscription")
def native_channel(
    channel_id: str, body: s.NativeSubscription, ctx=Depends(tenant_context), r=Depends(runtime)
):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        channel = get_scoped(db, m.Channel, channel_id, ctx.tenant_id)
        return r.channels.native_subscription(
            db, get_scoped(db, m.ManagedBot, channel.bot_id, ctx.tenant_id), channel, body.price_xtr
        )


def save_plan(db, body, ctx, plan=None):
    bot = get_scoped(db, m.ManagedBot, body.bot_id, ctx.tenant_id)
    if body.channel_id:
        channel = get_scoped(db, m.Channel, body.channel_id, ctx.tenant_id)
        if channel.bot_id != bot.id or channel.access_mode != "PLATFORM":
            raise DomainError("CHANNEL_MISMATCH", "Selecciona un canal propio de este bot.")
    if body.recurring and body.duration_days != 30:
        raise DomainError("STARS_PERIOD", "La renovación automática usa periodos de 30 días.")
    keys = [(p.provider, p.currency) for p in body.prices]
    if len(set(keys)) != len(keys):
        raise DomainError("DUPLICATE_PRICE", "Hay precios duplicados.")
    for price in body.prices:
        if (price.provider == "TELEGRAM_STARS") != (price.currency == "XTR"):
            raise DomainError("CURRENCY_MISMATCH", "Stars usa XTR; los demás métodos usan MXN o USD.")
        if body.recurring and price.provider == "TELEGRAM_STARS" and price.amount_minor > 10000:
            raise DomainError("STARS_LIMIT", "Hasta 10.000 Stars por suscripción recurrente.")
    if plan:
        for old in db.scalars(select(m.PlanPrice).where(m.PlanPrice.plan_id == plan.id)):
            db.delete(old)
        db.flush()
    else:
        plan = m.Plan(id=m.uid(), tenant_id=ctx.tenant_id)
        db.add(plan)
    for key, value in body.model_dump(exclude={"prices"}).items():
        setattr(plan, key, value)
    db.flush()
    for price in body.prices:
        db.add(m.PlanPrice(tenant_id=ctx.tenant_id, plan_id=plan.id, **price.model_dump()))
    bot.config_version += 1
    audit(db, ctx.tenant_id, ctx.user_id, "PLAN_CONFIGURED", plan.id)
    return public(plan)


@router.post("/t/{workspace_id}/plans", status_code=201)
def create_plan(body: s.PlanCreate, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        return save_plan(db, body, ctx)


@router.put("/t/{workspace_id}/plans/{plan_id}")
def update_plan(plan_id: str, body: s.PlanCreate, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        plan = get_scoped(db, m.Plan, plan_id, ctx.tenant_id)
        if body.bot_id != plan.bot_id or body.channel_id != plan.channel_id:
            raise DomainError("IMMUTABLE_PLAN_ACCESS", "Crea otro plan para cambiar el bot o el canal.", 409)
        return save_plan(db, body, ctx, plan)


@router.put("/t/{workspace_id}/providers/{provider}")
def save_provider(provider: str, body: s.ProviderSave, ctx=Depends(tenant_context), r=Depends(runtime)):
    if provider not in {"BANK_TRANSFER", "TELEGRAM_STARS"}:
        raise DomainError(
            "PROVIDER_ADAPTER_REQUIRED",
            "El proveedor externo necesita un adaptador y aprobación de actividad.",
            409,
        )
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "configure", db)
        config = db.scalar(select(m.ProviderConfig).where(m.ProviderConfig.provider == provider))
        if not config:
            config = m.ProviderConfig(id=m.uid(), tenant_id=ctx.tenant_id, provider=provider)
            db.add(config)
        if provider == "BANK_TRANSFER":
            if not r.vault:
                raise DomainError("VAULT_NOT_CONFIGURED", "Falta configurar cifrado.", 503)
            if body.enabled and (
                not body.bank_name or not body.account_holder or not (body.clabe or body.account)
            ):
                raise DomainError("BANK_DETAILS_REQUIRED", "Completa banco, titular y cuenta o CLABE.")
            config.secrets_ciphertext = r.vault.encrypt(
                json.dumps(body.model_dump(exclude={"enabled"})), f"{ctx.tenant_id}:{config.id}:provider"
            )
            config.public_config = {
                "bank_name": body.bank_name,
                "currency": body.currency,
                "usage": "OFF_PLATFORM_ONLY",
            }
        config.enabled = body.enabled
        audit(db, ctx.tenant_id, ctx.user_id, "PROVIDER_CONFIGURED", config.id, {"provider": provider})
        db.flush()
        return public(config)


@router.post("/t/{workspace_id}/payments/off-platform-bank")
def bank_payment(body: s.BankPayment, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "payments", db)
        bot = get_scoped(db, m.ManagedBot, body.bot_id, ctx.tenant_id)
        contact = get_scoped(db, m.Contact, body.contact_id, ctx.tenant_id)
        result = r.payments.create(
            db,
            bot,
            contact,
            body.plan_id,
            "BANK_TRANSFER",
            body.currency,
            f"admin:{ctx.user_id}:{body.idempotency_key}",
            context="OFF_PLATFORM",
        )
        audit(
            db,
            ctx.tenant_id,
            ctx.user_id,
            "OFF_PLATFORM_ORDER_RECORDED",
            result.id,
            {"reference": body.off_platform_order_reference},
        )
        return public(result)


@router.post("/t/{workspace_id}/receipts/{receipt_id}/review")
def receipt_review(receipt_id: str, body: s.Review, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "payments", db)
        receipt = get_scoped(db, m.BankReceipt, receipt_id, ctx.tenant_id)
        payment = get_scoped(db, m.Payment, receipt.payment_id, ctx.tenant_id)
        bot = get_scoped(db, m.ManagedBot, payment.bot_id, ctx.tenant_id)
        return public(
            r.receipts.review(db, bot, receipt, ctx.user_id, body.decision, body.note, body.accept_duplicate)
        )


@router.get("/t/{workspace_id}/receipts/{receipt_id}/image")
def receipt_image(receipt_id: str, ctx=Depends(tenant_context), r=Depends(runtime)):
    permit(ctx, "payments")
    with r.db.tenant(ctx.tenant_id) as db:
        receipt = get_scoped(db, m.BankReceipt, receipt_id, ctx.tenant_id)
        return Response(
            r.receipts.read(receipt),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )


@router.post("/t/{workspace_id}/charges/{charge_id}/refund")
def refund(charge_id: str, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "payments", db)
        charge = get_scoped(db, m.PaymentCharge, charge_id, ctx.tenant_id)
        payment = get_scoped(db, m.Payment, charge.payment_id, ctx.tenant_id)
        bot = get_scoped(db, m.ManagedBot, payment.bot_id, ctx.tenant_id)
        if not charge.refunded_at:
            r.payments.providers[payment.provider].refund(db, bot, payment, charge)
            r.payments.refunded_event(db, bot, {"telegram_payment_charge_id": charge.charge_id})
            audit(db, ctx.tenant_id, ctx.user_id, "REFUND_REQUESTED", charge.id)
        return {"status": "REFUNDED"}


@router.patch("/t/{workspace_id}/contacts/{contact_id}")
def update_contact(contact_id: str, body: s.ContactUpdate, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "sales", db)
        contact = get_scoped(db, m.Contact, contact_id, ctx.tenant_id)
        contact.stage, contact.opted_out = body.stage, body.opted_out
        audit(db, ctx.tenant_id, ctx.user_id, "CRM_UPDATED", contact.id)
        return public(contact)


@router.post("/t/{workspace_id}/contacts/{contact_id}/notes")
def note(contact_id: str, body: s.Note, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "support", db)
        get_scoped(db, m.Contact, contact_id, ctx.tenant_id)
        row = m.InternalNote(
            tenant_id=ctx.tenant_id, contact_id=contact_id, author_id=ctx.user_id, text=body.text
        )
        db.add(row)
        db.flush()
        return public(row)


@router.get("/t/{workspace_id}/conversations/{conversation_id}/messages")
def messages(
    conversation_id: str,
    ctx=Depends(tenant_context),
    r=Depends(runtime),
    limit: int = Query(50, ge=1, le=100),
    before: int | None = None,
):
    with r.db.tenant(ctx.tenant_id) as db:
        get_scoped(db, m.Conversation, conversation_id, ctx.tenant_id)
        query = select(m.Message).where(m.Message.conversation_id == conversation_id)
        if before:
            query = query.where(m.Message.created_at < before)
        return [public(x) for x in db.scalars(query.order_by(m.Message.created_at.desc()).limit(limit))]


@router.post("/t/{workspace_id}/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, body: s.MessageSend, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "support", db)
        conv = get_scoped(db, m.Conversation, conversation_id, ctx.tenant_id)
        bot = get_scoped(db, m.ManagedBot, conv.bot_id, ctx.tenant_id)
        return public(crm.reply(db, bot, conv, ctx.user_id, body.text, body.idempotency_key))


@router.post("/t/{workspace_id}/team")
def add_member(body: s.MemberCreate, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "team", db)
        tenants.feature(db, ctx.tenant_id, "team_members")
        user = db.scalar(
            select(m.PlatformUser).where(m.PlatformUser.telegram_user_id == body.telegram_user_id)
        )
        if not user:
            raise DomainError("USER_MUST_START_MASTER", "La persona debe abrir primero el Master Bot.", 409)
        row = db.scalar(select(m.TenantMember).where(m.TenantMember.user_id == user.id))
        if row and row.role == "OWNER":
            raise DomainError("OWNER_PROTECTED", "No se puede cambiar el propietario con esta acción.", 403)
        if not row:
            tenants.check_entity_limit(db, ctx.tenant_id, "admins", m.TenantMember)
            row = m.TenantMember(tenant_id=ctx.tenant_id, user_id=user.id, role=body.role)
            db.add(row)
        row.role, row.active = body.role, True
        audit(db, ctx.tenant_id, ctx.user_id, "TEAM_MEMBER_CONFIGURED", user.id)
        return {"saved": True}


@router.delete("/t/{workspace_id}/team/{member_id}")
def remove_member(member_id: str, ctx=Depends(tenant_context), r=Depends(runtime)):
    with r.db.tenant(ctx.tenant_id) as db:
        permit(ctx, "team", db)
        member = get_scoped(db, m.TenantMember, member_id, ctx.tenant_id)
        if member.role == "OWNER":
            raise DomainError("OWNER_PROTECTED", "No se puede eliminar al propietario.", 403)
        member.active = False
        audit(db, ctx.tenant_id, ctx.user_id, "TEAM_MEMBER_REMOVED", member.id)
        return {"saved": True}


@router.post("/t/{workspace_id}/billing/checkout/{plan_id}")
def billing_checkout(plan_id: str, ctx=Depends(tenant_context), r=Depends(runtime)):
    permit(ctx, "billing")
    with r.db.tenant(ctx.tenant_id) as db:
        return public(r.billing.checkout(db, ctx.tenant_id, db.get(m.PlatformUser, ctx.user_id), plan_id))


@router.post("/support/tickets", status_code=201)
def support_ticket(body: s.TicketCreate, auth=Depends(master), r=Depends(runtime)):
    with r.db.system() as db:
        ticket = m.PlatformSupportTicket(user_id=auth.user_id, **body.model_dump())
        db.add(ticket)
        db.flush()
        audit(db, None, auth.user_id, "SUPPORT_TICKET_CREATED", ticket.id)
        return public(ticket)
