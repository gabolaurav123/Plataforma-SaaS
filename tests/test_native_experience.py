import pytest
from sqlalchemy import select, func
from platform_app import models as m
from platform_app.errors import DomainError
from platform_app.services import console, crypto_wallets, payment_methods, business, background, refunds
from platform_app.services.i18n import t
from platform_app.worker import Worker
from platform_app.api.webhooks import store_update
from test_native_telegram import Chat


def incoming(env, actor, number, **content):
    update = {
        "update_id": number,
        "message": {
            "message_id": number,
            "from": {"id": actor, "first_name": "Client"},
            "chat": {"id": actor, "type": "private"},
            **content,
        },
    }
    with env["r"].db.system() as db:
        console.handle(env["r"], db, update, db.get(m.ManagedBot, env["ba"]))


@pytest.mark.parametrize("actor", [101, 909091])
def test_id_is_global_and_does_not_consume_an_open_form(env, actor):
    r = env["r"]
    with r.db.system() as db:
        bot = db.get(m.ManagedBot, env["ba"])
        bot.published = False
        ui = console.Console(r, db, bot, {"update_id": 1}, {"id": actor})
        ui.state().data = {
            "business": actor == 101,
            "flow": "biz:crypto_address",
            "wallet": {"asset": "USDT"},
        }
    for command in ["/id", "/id@child_0_bot"]:
        chat = Chat(env, actor, env["ba"]).update(command)
        assert str(actor) in chat.text
        with r.db.system() as db:
            state = db.scalar(
                select(m.ConsoleState).where(
                    m.ConsoleState.bot_key == env["ba"], m.ConsoleState.telegram_user_id == actor
                )
            )
            assert state.data["flow"] == "biz:crypto_address"
            assert not db.scalar(select(m.Contact.id).where(m.Contact.telegram_user_id == 909091))
            assert db.scalar(select(m.PlatformUser.id).where(m.PlatformUser.telegram_user_id == actor))


def test_customer_text_and_media_native_reply_preserves_form_and_rechecks_role(env):
    r = env["r"]
    with r.db.system() as db:
        from platform_app.services.tenants import upsert_user

        agent = upsert_user(db, {"id": 303, "first_name": "Support"})
        db.add(
            m.BotAdmin(tenant_id=env["ta"], bot_id=env["ba"], user_id=agent.id, role="SUPPORT", active=True)
        )
        agent_id = agent.id
    incoming(env, 900001, 820001, text="Can you help?")
    incoming(env, 900001, 820002, photo=[{"file_id": "customer-photo"}], caption="This is the issue")
    with r.db.system() as db:
        jobs = list(db.scalars(select(m.Job).where(m.Job.dedup_key.like("inbox-delivery:%"))))
        assert len(jobs) == 6  # Owner + support, one text and one text/photo pair.
        assert {j.payload["chat_id"] for j in jobs} == {101, 303}
        for job in jobs:
            Worker(r).process_send(db, job, db.get(m.ManagedBot, env["ba"]))
        db.flush()
        delivery = db.scalar(
            select(m.InboxDelivery).where(m.InboxDelivery.viewer_id == 303, m.InboxDelivery.part == "media")
        )
        target = delivery.telegram_message_id
        assert target and delivery.status == "SENT"
        ui = console.Console(r, db, db.get(m.ManagedBot, env["ba"]), {"update_id": 0}, {"id": 303})
        ui.state().data = {"business": True, "flow": "biz:some_open_form", "draft": "keep"}
    incoming(env, 303, 820003, voice={"file_id": "admin-voice"}, reply_to_message={"message_id": target})
    with r.db.system() as db:
        out = db.scalar(select(m.Message).where(m.Message.direction == "OUT"))
        assert out.admin_id == agent_id and out.media == {"kind": "voice", "file_id": "admin-voice"}
        job = db.scalar(select(m.Job).where(m.Job.dedup_key.like("inbox:%")))
        assert job.payload["chat_id"] == 900001
        Worker(r).process_send(db, job, db.get(m.ManagedBot, env["ba"]))
        assert out.status == "SENT"
        state = db.scalar(
            select(m.ConsoleState).where(
                m.ConsoleState.bot_key == env["ba"], m.ConsoleState.telegram_user_id == 303
            )
        )
        assert state.data["draft"] == "keep"
        db.scalar(select(m.BotAdmin).where(m.BotAdmin.user_id == agent_id)).active = False
    incoming(env, 303, 820004, text="Must not send", reply_to_message={"message_id": target})
    with r.db.system() as db:
        assert db.scalar(select(func.count()).select_from(m.Message).where(m.Message.direction == "OUT")) == 1
        with pytest.raises(DomainError):
            Worker(r).process_send(
                db,
                db.scalar(select(m.Job).where(m.Job.dedup_key.like("inbox:%"))),
                db.get(m.ManagedBot, env["ba"]),
            )


def test_native_reply_mapping_cannot_be_used_by_another_admin_or_bot(env):
    incoming(env, 900001, 830001, text="Only for this business")
    r = env["r"]
    with r.db.system() as db:
        delivery = db.scalar(select(m.InboxDelivery))
        delivery.status, delivery.telegram_message_id = "SENT", 991
        for actor, bid in [(202, env["bb"]), (202, env["ba"]), (101, env["bb"])]:
            from platform_app.services.inbox import native_reply

            ui = console.Console(r, db, db.get(m.ManagedBot, bid), {"update_id": 2}, {"id": actor})
            assert not native_reply(ui, {"text": "forged", "reply_to_message": {"message_id": 991}})
        assert db.scalar(select(func.count()).select_from(m.Message).where(m.Message.direction == "OUT")) == 0


@pytest.mark.parametrize("language", ["es", "en", "pt"])
def test_crypto_wallet_wizard_and_customer_network_checkout(env, language):
    r = env["r"]
    with r.db.system() as db:
        db.get(m.PlatformUser, env["ua"]).locale = language
    chat = Chat(env, 101, env["ba"]).update("/admin").click(t("methods", language))
    chat.click("Cripto" if language != "en" else "Crypto")
    chat.click(t("crypto_add", language)).click("USDT").click("TRON")
    chat.update("T" + "a" * 33).update("-").update("-").update("-").click(t("confirm", language))
    chat.click(t("crypto_enable", language))
    with r.db.system() as db:
        bot = db.get(m.ManagedBot, env["ba"])
        method = payment_methods.get(db, bot, "CRYPTO_MANUAL")
        assert method.enabled
        wallet = crypto_wallets.wallets(db, bot)[0]
        assert wallet["network"] == "TRON (TRC20)" and wallet["memo"] == ""
        plan = db.scalar(select(m.Plan).where(m.Plan.bot_id == bot.id))
        plan.product_kind = "PHYSICAL"
        business.price(db, bot, plan, "CRYPTO_MANUAL", "USDT", "12.345678", env["ua"])
        plan_id = plan.id
    customer = Chat(env, 900001, env["ba"]).update("/plans").click("Premium").click("Cripto").click("TRON")
    assert t("checkout_queued", "es") in customer.text
    with r.db.system() as db:
        payment = db.scalar(select(m.Payment).where(m.Payment.provider == "CRYPTO_MANUAL"))
        assert payment.plan_id == plan_id and payment.amount_minor == 12345678
        assert payment.instructions_snapshot["address"] == wallet["address"]
        method = payment_methods.get(db, db.get(m.ManagedBot, env["ba"]), "CRYPTO_MANUAL")
        method.public_config = {"wallets": []}
        job = db.scalar(select(m.Job).where(m.Job.dedup_key == "checkout:" + payment.id))
        background.process(r, db, job, db.get(m.ManagedBot, env["ba"]))
        delivery = db.scalar(select(m.Job).where(m.Job.dedup_key == "checkout-delivery:" + payment.id))
        assert wallet["address"] in delivery.payload["text"] and "TRON" in delivery.payload["text"]
        assert payment.status == "PENDING"


def test_crypto_receipt_review_and_refund_are_manual_and_idempotent(env):
    from io import BytesIO
    from PIL import Image

    r = env["r"]
    with r.db.system() as db:
        bot = db.get(m.ManagedBot, env["ba"])
        wallet = crypto_wallets.save(
            db,
            bot,
            env["ua"],
            {"asset": "BNB", "network": "BNB Smart Chain (BEP20)", "address": "0x" + "a" * 40},
        )
        payment_methods.enable(db, r, bot, payment_methods.get(db, bot, "CRYPTO_MANUAL"), env["ua"])
        plan = db.scalar(select(m.Plan).where(m.Plan.bot_id == bot.id))
        plan.product_kind = "PHYSICAL"
        business.price(db, bot, plan, "CRYPTO_MANUAL", "BNB", "0.1", env["ua"])
        person = db.scalar(select(m.Contact).where(m.Contact.bot_id == bot.id))
        payment = r.payments.create(
            db, bot, person, plan.id, "CRYPTO_MANUAL", "BNB", "manual-crypto", wallet_id=wallet["id"]
        )
        assert payment.status == "PENDING" and payment.amount_minor == 10**17
        buf = BytesIO()
        Image.new("RGB", (200, 200), "blue").save(buf, format="PNG")
        receipt = r.receipts.submit(db, bot, payment, buf.getvalue())
        assert payment.status == "RECEIPT_SUBMITTED"
        r.receipts.review(db, bot, receipt, env["ua"], "APPROVE")
        r.receipts.review(db, bot, receipt, env["ua"], "APPROVE")
        charge = db.scalar(select(m.PaymentCharge).where(m.PaymentCharge.payment_id == payment.id))
        assert payment.status == "APPROVED" and charge.provider == "CRYPTO_MANUAL"
        assert (
            db.scalar(
                select(func.count())
                .select_from(m.Subscription)
                .where(m.Subscription.payment_id == payment.id)
            )
            == 1
        )
        with pytest.raises(DomainError, match="billetera"):
            r.payments.providers["CRYPTO_MANUAL"].refund(db, bot, payment, charge)
        refunds.record(db, r, bot, charge, payment.amount_minor, "blockchain-refund-reference", env["ua"])
        assert payment.status == "REFUNDED"


@pytest.mark.parametrize(
    "asset,amount",
    [
        ("ETH", "0.025"),
        ("BTC", "0.00000001"),
        ("BNB", "1.2"),
        ("USDT", "12.345678"),
        ("SOL", "2.1"),
        ("TON", "3.1"),
        ("XRP", "9.9"),
    ],
)
def test_crypto_amounts_preserve_precision(asset, amount):
    from decimal import Decimal

    minor = business.amount_minor(amount, asset)
    assert Decimal(business.money(minor, asset).split()[0]) == Decimal(amount)
    with pytest.raises(DomainError):
        business.amount_minor(str(2**63), asset)


def test_polling_dedup_offsets_and_nested_reply_privacy(env):
    r = env["r"]
    update = {
        "update_id": 9901,
        "message": {
            "message_id": 1,
            "from": {"id": 101},
            "chat": {"id": 101, "type": "private"},
            "voice": {"file_id": "private-voice"},
            "reply_to_message": {"message_id": 2, "text": "sensitive nested text"},
        },
    }
    store_update(None, None, update, r, polling=True)
    assert store_update(None, None, update, r, polling=True)["duplicate"]
    store_update(None, None, {**update, "update_id": 9900}, r, polling=True)
    with r.db.system() as db:
        saved = db.scalar(select(m.TelegramUpdate).where(m.TelegramUpdate.update_id == 9901))
        assert "sensitive nested text" not in str(saved.payload) and "private-voice" not in str(saved.payload)
        assert saved.sensitive_ciphertext
        assert db.scalar(select(m.PollCursor.next_offset).where(m.PollCursor.bot_key == "master")) == 9902
        assert (
            db.scalar(select(func.count()).select_from(m.Job).where(m.Job.dedup_key == "update:master:9901"))
            == 1
        )
