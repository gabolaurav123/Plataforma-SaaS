from types import SimpleNamespace
import pytest
from sqlalchemy import select, func
from platform_app import models as m
from platform_app.config import Settings
from platform_app.polling import Poller, PollingEngine, process_lock
from platform_app.api.webhooks import store_update
from platform_app.services.console import Console
from platform_app.worker import Worker


class Chat:
    def __init__(self, env, actor=202, bot_id=None):
        self.env, self.r, self.actor, self.bot_id = env, env["r"], actor, bot_id
        self.r.settings.deployment_mode = "telegram"
        self.number, self.jobs = 1000 + actor * 100, []

    def update(self, text=None, data=None, private=True):
        self.number += 1
        actor = {"id": self.actor, "first_name": "Native user"}
        message = {
            "chat": {"id": self.actor, "type": "private" if private else "group"},
            "from": actor,
            "message_id": self.number,
            "text": text or "",
        }
        update = {"update_id": self.number}
        update.update(
            {"callback_query": {"id": str(self.number), "from": actor, "message": message, "data": data}}
            if data
            else {"message": message}
        )
        with self.r.db.system() as db:
            if self.bot_id:
                self.r.updates.child(db, db.get(m.ManagedBot, self.bot_id), update)
            else:
                self.r.updates.master(db, update)
        with self.r.db.system() as db:
            self.jobs = list(
                db.scalars(
                    select(m.Job)
                    .where(m.Job.dedup_key.like(f"console:{self.bot_id or 'master'}:{self.number}:%"))
                    .order_by(m.Job.dedup_key)
                )
            )
        return self

    @property
    def text(self):
        return "\n".join(job.payload.get("text", "") for job in self.jobs)

    def find(self, label):
        for job in reversed(self.jobs):
            for row in job.payload.get("reply_markup", {}).get("inline_keyboard", []):
                for button in row:
                    if label in button["text"] and "callback_data" in button:
                        return button["callback_data"]
        raise AssertionError(f"No button {label!r}: {self.text}")

    def click(self, label):
        return self.update(data=self.find(label))


def button_for(env, actor, action, **data):
    with env["r"].db.system() as db:
        ui = Console(env["r"], db, None, {"update_id": 1}, {"id": actor, "first_name": "User"})
        return ui.button("Test", action, **data)["callback_data"]


def test_new_creator_native_onboarding_without_mini_app(env):
    chat = Chat(env, 303).update("/start").click("Crear mi negocio").update("Nuevo club")
    assert "PAYMENT_PENDING" in chat.text
    chat.click("Activar prueba gratuita")
    assert "TRIAL" in chat.text and "3 días" in chat.text
    chat.click("Conectar mi bot").update("880001:" + "X" * 35)
    assert "comprobando" in chat.text
    with env["r"].db.system() as db:
        user = db.scalar(select(m.PlatformUser).where(m.PlatformUser.telegram_user_id == 303))
        attempt = db.scalar(select(m.ConnectionAttempt).where(m.ConnectionAttempt.actor_id == user.id))
        env["r"].connections.validate(db, attempt)
        assert attempt.status == "VALIDATED"
        callback = db.scalar(
            select(m.ConsoleButton).where(
                m.ConsoleButton.telegram_user_id == 303, m.ConsoleButton.action == "connect_confirm"
            )
        )
        data = "ui:" + callback.id
    chat.update(data=data)
    with env["r"].db.system() as db:
        bot = db.scalar(select(m.ManagedBot).where(m.ManagedBot.telegram_bot_id == 880001))
        assert bot.connection_kind == "TOKEN"
        bid = bot.id
        secret = db.scalar(select(m.BotSecret).where(m.BotSecret.bot_id == bid))
        assert "X" * 35 not in str(secret.token_ciphertext)
    env["r"].provisioner.provision(bid)
    admin = Chat(env, 303, bid).update("/start")
    assert "Modo administrador" in admin.text
    assert "web_app" not in str([j.payload for j in chat.jobs + admin.jobs])


def delegated_chat(env):
    Chat(env, 404).update("/start")
    with env["r"].db.system() as db:
        user = db.scalar(select(m.PlatformUser).where(m.PlatformUser.telegram_user_id == 404))
        db.add(m.BotAdmin(tenant_id=env["tb"], bot_id=env["bb"], user_id=user.id, role="ADMIN"))
    return Chat(env, 404, env["bb"]).update("/admin")


def test_callbacks_bound_to_actor_private_chat_and_current_role(env):
    chat = delegated_chat(env).click("⚙️ Configuración")
    config = chat.find("Nombre, descripción")
    attacker = Chat(env, 405, env["bb"]).update(data=config)
    assert "caducó" in attacker.text
    chat.update(data=config, private=False)
    assert not chat.jobs
    with env["r"].db.system() as db:
        member = db.scalar(select(m.BotAdmin).where(m.BotAdmin.bot_id == env["bb"]))
        member.role = "READ_ONLY"
    chat.update(data=config)
    assert "Tu rol" in chat.text


def test_cross_tenant_and_owner_permissions_are_rechecked(env):
    chat = Chat(env)
    chat.update(data=button_for(env, 202, "bot", tid=env["ta"], id=env["ba"]))
    assert "No tienes acceso" in chat.text
    chat.update("/admin")
    assert "Solo el administrador" in chat.text
    admin = Chat(env, 101).update("/admin")
    assert "Administración de la plataforma" in admin.text
    admin.click("Negocios y acceso").click("Tenant B").click("Abrir negocio")
    assert "Tenant B" in admin.text


def test_dialog_survives_runtime_recreation_and_lost_permission(env):
    chat = (
        delegated_chat(env).click("⚙️ Configuración").click("Nombre, descripción").click("Descripción corta")
    )
    from platform_app.runtime import Runtime

    fresh = Runtime(env["r"].settings, env["fake"])
    chat.r = fresh
    try:
        chat.update("La descripción nueva")
        assert "Guardado" in chat.text
        with fresh.db.system() as db:
            config = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == env["bb"]))
            assert config.short_description == "La descripción nueva"
        chat.update("/admin").click("⚙️ Configuración").click("Nombre, descripción").click("Nombre")
        with fresh.db.system() as db:
            db.scalar(select(m.BotAdmin).where(m.BotAdmin.bot_id == env["bb"])).active = False
        chat.update("No autorizado")
        assert "acceso" in chat.text
        with fresh.db.system() as db:
            assert db.get(m.ManagedBot, env["bb"]).name != "No autorizado"
            assert not db.scalar(select(m.Message.id).where(m.Message.text == "No autorizado"))
    finally:
        fresh.close()


def test_native_plan_wizard_and_customer_checkout(env):
    creator = Chat(env, 202, env["bb"]).update("/admin").click("Planes").click("Crear").update("Club native")
    creator.click("Añadir / editar precio").click("Telegram Stars").update("250")
    creator.click("Renovación automática")
    creator.click("Activar / desactivar")
    customer = Chat(env, 900002, env["bb"]).update("/start")
    assert "web_app" not in str([j.payload for j in customer.jobs])
    customer.click("Ver planes").click("Club native").click("Stars")
    assert "pago" in customer.text.lower()
    with env["r"].db.system() as db:
        pay = db.scalar(select(m.Payment).where(m.Payment.bot_id == env["bb"]))
        assert pay.amount_minor == 250 and pay.recurring and pay.status == "PENDING"
        job = db.scalar(select(m.Job).where(m.Job.kind == "CHECKOUT", m.Job.bot_id == env["bb"]))
        Worker(env["r"]).dispatch(db, job)
    assert any(method == "createInvoiceLink" for _, method, _ in env["fake"].calls)


def test_callback_cannot_be_replayed_to_repeat_mutation(env):
    chat = Chat(env)
    with env["r"].db.system() as db:
        plan = db.scalar(select(m.Plan).where(m.Plan.bot_id == env["bb"]))
        pid = plan.id
    callback = button_for(env, 202, "plan_toggle", tid=env["tb"], id=pid)
    chat.update(data=callback)
    assert "desactivado" in chat.text
    chat.update(data=callback)
    assert "ya fue utilizado" in chat.text
    with env["r"].db.system() as db:
        assert db.get(m.Plan, pid).active is False


def test_owner_grant_requires_confirmation_and_no_payment_is_faked(env):
    chat = Chat(env, 101)
    chat.update(data=button_for(env, 101, "tenant_extend", id=env["tb"]))
    with env["r"].db.system() as db:
        before = db.scalar(
            select(m.SaaSSubscription.current_period_end).where(m.SaaSSubscription.tenant_id == env["tb"])
        )
    chat.update("30")
    with env["r"].db.system() as db:
        assert (
            db.scalar(
                select(m.SaaSSubscription.current_period_end).where(m.SaaSSubscription.tenant_id == env["tb"])
            )
            == before
        )
    chat.click("Confirmar cambio")
    with env["r"].db.system() as db:
        assert (
            db.scalar(
                select(m.SaaSSubscription.current_period_end).where(m.SaaSSubscription.tenant_id == env["tb"])
            )
            == before + 30 * 86400
        )
        assert db.scalar(select(func.count()).select_from(m.SaaSCharge)) == 0


def test_polling_offsets_commit_with_jobs_and_duplicate_delivery(env):
    env["r"].settings.deployment_mode = "telegram"
    update = {
        "update_id": 7000,
        "message": {
            "from": {"id": 303, "first_name": "User"},
            "chat": {"id": 303, "type": "private"},
            "message_id": 1,
            "text": "/start",
        },
    }
    store_update(None, None, update, env["r"], polling=True)
    store_update(None, None, update, env["r"], polling=True)
    with env["r"].db.system() as db:
        assert db.scalar(select(m.PollCursor.next_offset).where(m.PollCursor.bot_key == "master")) == 7001
        assert (
            db.scalar(
                select(func.count()).select_from(m.TelegramUpdate).where(m.TelegramUpdate.update_id == 7000)
            )
            == 1
        )
        assert (
            db.scalar(select(func.count()).select_from(m.Job).where(m.Job.dedup_key == "update:master:7000"))
            == 1
        )
    worker = Worker(env["r"])
    for _ in range(20):
        if not worker.run_one():
            break
    assert any(
        method == "sendMessage" and params.get("chat_id") == 303 for _, method, params in env["fake"].calls
    )


def test_no_ack_on_storage_failure_and_no_database_access_on_empty_poll(env, monkeypatch):
    engine = PollingEngine(env["r"])
    replies = [{"update_id": 7100, "message": {"text": "hello"}}]
    client = SimpleNamespace(call=lambda *a, **kw: replies)
    poller = Poller(engine, "master", None, client, 1)

    def fail(*args, **kwargs):
        raise RuntimeError("storage failed")

    monkeypatch.setattr("platform_app.polling.store_update", fail)
    with pytest.raises(RuntimeError):
        poller.once()
    assert poller.offset == 0 and not engine.wake.is_set()
    replies.clear()
    monkeypatch.setattr(env["r"].db, "system", fail)
    poller.once()
    assert poller.offset == 0


def test_precheckout_fast_path_does_not_wait_for_worker(env):
    from conftest import bot_parts

    bot, person, plan = bot_parts(env)
    with env["r"].db.system() as db:
        pay = env["r"].payments.create(
            db, bot, person, plan.id, "TELEGRAM_STARS", "XTR", "test-poll-checkout"
        )
    query = {
        "id": "query-fast",
        "from": {"id": person.telegram_user_id},
        "currency": "XTR",
        "total_amount": pay.amount_minor,
        "invoice_payload": pay.invoice_payload,
    }
    store_update(
        bot.id, bot.tenant_id, {"update_id": 7200, "pre_checkout_query": query}, env["r"], polling=True
    )
    assert any(method == "answerPreCheckoutQuery" and params["ok"] for _, method, params in env["fake"].calls)
    with env["r"].db.system() as db:
        assert db.scalar(select(m.TelegramUpdate.status).where(m.TelegramUpdate.update_id == 7200)) == "DONE"


def test_native_production_requires_identity_but_no_redis_or_public_urls():
    values = dict(
        _env_file=None,
        environment="production",
        deployment_mode="telegram",
        database_url="postgresql://api:pass@db/app",
        system_database_url="postgresql://system:pass@db/app",
        master_bot_token="12345:" + "x" * 32,
        master_bot_username="new_bot",
        platform_owner_ids="123",
        encryption_keys='{"v1":"eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg="}',
    )
    assert Settings(**values).redis_url is None
    with pytest.raises(ValueError):
        Settings(**{**values, "platform_owner_ids": ""})
    with pytest.raises(ValueError):
        Settings(**{**values, "deployment_mode": "web"})


def test_master_identity_verified_before_disabling_webhook(env):
    env["r"].settings.deployment_mode = "telegram"
    env["r"].settings.master_bot_username = "different_bot"
    env["fake"].calls.clear()
    from platform_app.errors import DomainError

    with pytest.raises(DomainError):
        env["r"].manager.configure_master()
    assert not any(method == "deleteWebhook" for _, method, _ in env["fake"].calls)


def test_process_lock_rejects_second_process_lock(tmp_path):
    with process_lock(tmp_path / "worker.lock"):
        with pytest.raises(RuntimeError):
            with process_lock(tmp_path / "worker.lock"):
                pass


def test_polling_conflict_stops_instance(env):
    from platform_app.telegram import TelegramError

    engine = PollingEngine(env["r"])

    def conflict(*args, **kwargs):
        raise TelegramError("POLLING_CONFLICT", "conflict", 502)

    poller = Poller(engine, "master", None, SimpleNamespace(call=conflict), 1)
    poller.run()
    assert engine.stop.is_set() and engine.fatal


def test_native_provision_publish_and_menu_configuration(env):
    chat = Chat(env)
    env["r"].settings.master_bot_username = "test_bot"
    env["r"].manager.configure_master()
    env["r"].provisioner.provision(env["bb"])
    with env["r"].db.system() as db:
        bot = db.get(m.ManagedBot, env["bb"])
        bot.published = False
        config = db.scalar(select(m.BotSettings).where(m.BotSettings.bot_id == bot.id))
        config.support_username = "soporte_bot"
        config.policies = {x: "Política válida" for x in ["terms", "privacy", "refund"]}
    chat.update(data=button_for(env, 202, "publish", tid=env["tb"], id=env["bb"]))
    assert "Bot publicado" in chat.text
    with env["r"].db.system() as db:
        assert db.get(m.ManagedBot, env["bb"]).published
    recent = env["fake"].calls
    assert any(
        method == "deleteWebhook" and params["drop_pending_updates"] is False for _, method, params in recent
    )
    assert recent[-1][1] == "sendMessage"


def test_native_team_campaign_automation_and_support(env):
    chat = Chat(env)
    Chat(env, 404).update("/start")
    chat.update(data=button_for(env, 202, "team_add", tid=env["tb"])).update("404 SUPPORT")
    assert "equipo configurado" in chat.text
    chat.update(data=button_for(env, 202, "campaign", tid=env["tb"], id=env["bb"]))
    chat.update("Hola {first_name}, tenemos novedades")
    assert "Hola" in chat.text
    chat.click("Iniciar / reanudar")
    with env["r"].db.system() as db:
        assert db.scalar(select(m.Campaign.status).where(m.Campaign.tenant_id == env["tb"])) == "DRAFT"
    chat.click("Confirmar envío")
    assert "Campaña en cola" in chat.text
    chat.update(data=button_for(env, 202, "automation", tid=env["tb"], id=env["bb"]))
    chat.update("Tu membresía vencerá pronto.")
    with env["r"].db.system() as db:
        assert (
            db.scalar(select(m.AutomationRule.trigger).where(m.AutomationRule.tenant_id == env["tb"]))
            == "SUBSCRIPTION_EXPIRING"
        )
    chat.update("/support").update("Necesito ayuda con mi bot nuevo")
    admin = Chat(env, 101).update("/admin").click("Soporte").click("Necesito ayuda")
    admin.click("Responder al creador").update("Te ayudaremos desde aquí.")
    with env["r"].db.system() as db:
        assert db.scalar(select(m.PlatformSupportTicket.status)) == "ANSWERED"
        reply = db.scalar(select(m.Job).where(m.Job.dedup_key.like("ticket-reply:%")))
        assert reply.payload["chat_id"] == 202


def test_native_http_server_is_disabled(env):
    from platform_app.main import create_app

    env["r"].settings.deployment_mode = "telegram"
    with pytest.raises(RuntimeError, match="sin servidor web"):
        create_app(env["r"])


def test_native_all_resource_lists_resolve_and_hide_secrets(env):
    from platform_app.services.console import RES_LABELS

    chat = Chat(env)
    for resource in RES_LABELS:
        chat.update(data=button_for(env, 202, "list", tid=env["tb"], resource=resource))
        assert chat.jobs
        assert "ciphertext" not in chat.text and "database_url" not in chat.text


def test_native_customer_buttons_cannot_cross_bots_or_users(env):
    customer = Chat(env, 900002, env["bb"]).update("/start")
    callback = customer.find("Ver planes")
    other = Chat(env, 900001, env["ba"]).update(data=callback)
    assert "caducó" in other.text
    other_same_bot = Chat(env, 900003, env["bb"]).update(data=callback)
    assert "caducó" in other_same_bot.text


def test_native_receipt_delivery_rechecks_access_and_keeps_bytes_out_of_outbox(env):
    import io
    from PIL import Image
    from conftest import bot_parts

    bot, person, plan = bot_parts(env, "b")
    stream = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(stream, format="PNG")
    env["r"].settings.receipt_storage = "database"
    with env["r"].db.system() as db:
        pay = env["r"].payments.create(
            db, bot, person, plan.id, "BANK_TRANSFER", "MXN", "receipt-native", context="OFF_PLATFORM"
        )
        receipt = env["r"].receipts.submit(db, bot, pay, stream.getvalue())
        rid = receipt.id
    chat = Chat(env).update(data=button_for(env, 202, "receipt_image", tid=env["tb"], id=rid))
    job = chat.jobs[0]
    assert "receipt_id" in job.payload and "ciphertext" not in str(job.payload)
    with env["r"].db.system() as db:
        db.scalar(select(m.TenantMember).where(m.TenantMember.tenant_id == env["tb"])).active = False
    from platform_app.errors import DomainError

    with env["r"].db.system() as db, pytest.raises(DomainError):
        Worker(env["r"]).process_send(db, db.get(m.Job, job.id), None)


def test_single_process_loop_receives_persists_and_replies(env):
    import threading
    import time

    env["r"].settings.deployment_mode = "telegram"
    env["r"].settings.master_bot_username = "test_bot"
    engine = PollingEngine(env["r"])
    received, delivered = threading.Event(), threading.Event()
    failures = []
    base_factory = env["r"].clients.factory

    def factory(token, test_environment=False):
        base = base_factory(token, test_environment)

        class Client:
            def call(self, method, **params):
                if method == "getUpdates":
                    if token.startswith("100001:") and not received.is_set():
                        received.set()
                        return [
                            {
                                "update_id": 8100,
                                "message": {
                                    "message_id": 1,
                                    "from": {"id": 303, "first_name": "New"},
                                    "chat": {"id": 303, "type": "private"},
                                    "text": "/start",
                                },
                            }
                        ]
                    engine.stop.wait(0.05)
                    return []
                result = base.call(method, **params)
                if method == "sendMessage" and params.get("chat_id") == 303:
                    delivered.set()
                return result

        return Client()

    env["r"].clients.close()
    env["r"].clients.factory = factory

    def run():
        try:
            engine.run()
        except Exception as error:
            failures.append(type(error).__name__)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        assert delivered.wait(8), failures
        # Empty Telegram polls do not wake the outbox loop.
        time.sleep(0.1)
    finally:
        engine.stop.set()
        engine.wake.set()
        thread.join(5)
    assert not thread.is_alive() and not failures
    with env["r"].db.system() as db:
        assert db.scalar(select(m.PollCursor.next_offset).where(m.PollCursor.bot_key == "master")) == 8101
