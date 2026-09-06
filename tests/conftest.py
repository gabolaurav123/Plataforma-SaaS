import base64
import hashlib
import hmac
import json
from urllib.parse import urlencode
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from platform_app.config import Settings
from platform_app.runtime import Runtime
from platform_app.main import create_app
from platform_app import models as m
from platform_app.services.tenants import create_tenant, upsert_user
from platform_app.services.crm import upsert_contact

MASTER_TOKEN = "100001:" + "M" * 35


def signed_data(user_id, token=MASTER_TOKEN, timestamp=None, **extra):
    data = {
        "auth_date": str(timestamp if timestamp is not None else m.now()),
        "user": json.dumps({"id": user_id, "first_name": f"User {user_id}"}),
        **extra,
    }
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


class FakeTelegram:
    def __init__(self):
        self.calls, self.tokens = [], {}
        self.manage, self.permissions, self.fail, self.invites = True, True, None, 0

    def __call__(self, token, test_environment=False):
        api = self

        class Client:
            def call(self, method, **params):
                bot_id = int(token.split(":")[0])
                api.calls.append((bot_id, method, params))
                if api.fail == method:
                    from platform_app.telegram import TelegramError

                    raise TelegramError("TELEGRAM_TRANSPORT_UNKNOWN", "Test transport failure", 502)
                if method == "getMe":
                    return {
                        "id": bot_id,
                        "is_bot": True,
                        "first_name": "Test",
                        "username": "test_bot",
                        "can_manage_bots": api.manage,
                    }
                if method in {"getManagedBotToken", "replaceManagedBotToken"}:
                    if method == "replaceManagedBotToken" or params["user_id"] not in api.tokens:
                        api.tokens[params["user_id"]] = f"{params['user_id']}:" + m.uid().replace("-", "")
                    return api.tokens[params["user_id"]]
                if method == "savePreparedKeyboardButton":
                    return {"id": "prepared-keyboard", "expiration_date": m.now() + 3600}
                if method == "getChatMember":
                    return {
                        "status": "administrator" if params["user_id"] == bot_id else "member",
                        "can_invite_users": api.permissions,
                        "can_restrict_members": api.permissions,
                    }
                if method in {"createChatInviteLink", "createChatSubscriptionInviteLink"}:
                    api.invites += 1
                    return {"invite_link": f"https://t.me/+test{api.invites}"}
                if method == "getWebhookInfo":
                    for bid, action, data in reversed(api.calls):
                        if bid == bot_id and action == "setWebhook":
                            return {"url": data["url"], "pending_update_count": 0}
                    return {"url": "", "pending_update_count": 0}
                if method == "getChatMenuButton":
                    for bid, action, data in reversed(api.calls):
                        if bid == bot_id and action == "setChatMenuButton":
                            return data["menu_button"]
                    return {}
                if method == "sendMessage":
                    return {"message_id": len(api.calls)}
                if method == "createInvoiceLink":
                    return "https://t.me/$exampleInvoice"
                if method == "getStarTransactions":
                    return {"transactions": []}
                return True

        return Client()


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        master_bot_token=MASTER_TOKEN,
        master_webhook_secret="master-webhook-" + "s" * 32,
        encryption_keys=json.dumps({"v1": base64.b64encode(b"x" * 32).decode()}),
        platform_owner_ids="101",
        storage_path=str(tmp_path / "storage"),
        user_rps=10000,
        tenant_rps=10000,
        bot_rps=10000,
        global_rps=10000,
    )
    fake = FakeTelegram()
    r = Runtime(settings, fake)
    m.Base.metadata.create_all(r.db.engine)
    with r.db.system() as db:
        user_a = upsert_user(db, {"id": 101, "first_name": "Alice"})
        user_b = upsert_user(db, {"id": 202, "first_name": "Bob"})
        ta = create_tenant(db, user_a, "Tenant A", settings)
        tb = create_tenant(db, user_b, "Tenant B", settings)
        tenant_ids, users = [ta.id, tb.id], [user_a.id, user_b.id]
        bots = []
        for index, tenant in enumerate([ta, tb]):
            bot = m.ManagedBot(
                id=m.uid(),
                tenant_id=tenant.id,
                telegram_bot_id=700001 + index,
                owner_telegram_user_id=101 if index == 0 else 202,
                public_id=m.uid(),
                username=f"child_{index}_bot",
                name=f"Bot {index}",
            )
            db.add(bot)
            bots.append(bot.id)
    for bid in bots:
        r.provisioner.provision(bid)
    with r.db.system() as db:
        for index, bid in enumerate(bots):
            bot = db.get(m.ManagedBot, bid)
            bot.published = True
            upsert_contact(db, bot, {"id": 900001 + index, "first_name": f"Client {index}"})
            db.add(m.ProviderConfig(tenant_id=bot.tenant_id, provider="TELEGRAM_STARS", enabled=True))
            db.add(m.ProviderConfig(tenant_id=bot.tenant_id, provider="BANK_TRANSFER", enabled=True))
            plan = m.Plan(
                id=m.uid(), tenant_id=bot.tenant_id, bot_id=bot.id, name="Premium", duration_days=30
            )
            db.add(plan)
            db.flush()
            db.add(
                m.PlanPrice(
                    tenant_id=bot.tenant_id,
                    plan_id=plan.id,
                    provider="TELEGRAM_STARS",
                    currency="XTR",
                    amount_minor=500,
                )
            )
            db.add(
                m.PlanPrice(
                    tenant_id=bot.tenant_id,
                    plan_id=plan.id,
                    provider="BANK_TRANSFER",
                    currency="MXN",
                    amount_minor=49900,
                )
            )
    client = TestClient(create_app(r))
    auth_a = client.post("/api/auth/master", json={"init_data": signed_data(101)}).json()["access_token"]
    auth_b = client.post("/api/auth/master", json={"init_data": signed_data(202)}).json()["access_token"]
    yield {
        "r": r,
        "fake": fake,
        "client": client,
        "ta": tenant_ids[0],
        "tb": tenant_ids[1],
        "ua": users[0],
        "ub": users[1],
        "ba": bots[0],
        "bb": bots[1],
        "a": {"Authorization": f"Bearer {auth_a}"},
        "b": {"Authorization": f"Bearer {auth_b}"},
    }
    client.close()
    r.db.engine.dispose()


def bot_parts(env, which="a"):
    with env["r"].db.system() as db:
        bot = db.get(m.ManagedBot, env["b" + which])
        contact = db.scalar(select(m.Contact).where(m.Contact.bot_id == bot.id))
        plan = db.scalar(select(m.Plan).where(m.Plan.bot_id == bot.id))
        return bot, contact, plan
