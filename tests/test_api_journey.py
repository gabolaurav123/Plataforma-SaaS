from sqlalchemy import select
from platform_app import models as m
from platform_app.worker import Worker
from conftest import bot_parts, signed_data


def drain(runtime):
    worker = Worker(runtime)
    for _ in range(50):
        if not worker.run_one():
            break


def test_creator_to_customer_paid_membership_journey(env):
    c, r = env["client"], env["r"]
    bot, contact, plan = bot_parts(env)
    base = f"/api/t/{env['ta']}"
    assert c.get("/api/me", headers=env["a"]).json()["platform_owner"] is True
    settings = c.put(
        base + f"/bots/{bot.id}/settings",
        headers=env["a"],
        json={
            "name": "Published Club",
            "description": "Private creator community",
            "short_description": "Club",
            "menu_text": "Mi membresía",
            "support_username": "support_test",
            "terms": "Terms",
            "privacy": "Privacy",
            "refund": "Refund policy",
            "commands": [
                {"command": "start", "description": "Start"},
                {"command": "paysupport", "description": "Payments help"},
            ],
        },
    )
    assert settings.status_code == 200, settings.text
    assert (
        c.put(
            base + f"/bots/{bot.id}/texts/WELCOME", headers=env["a"], json={"value": "Hola {{first_name}}"}
        ).status_code
        == 200
    )
    assert (
        c.put(base + "/providers/TELEGRAM_STARS", headers=env["a"], json={"enabled": True}).status_code == 200
    )
    extra_plan = c.post(
        base + "/plans",
        headers=env["a"],
        json={
            "bot_id": bot.id,
            "name": "Annual",
            "duration_days": 365,
            "prices": [{"provider": "TELEGRAM_STARS", "currency": "XTR", "amount_minor": 5000}],
        },
    )
    assert extra_plan.status_code == 201, extra_plan.text
    drain(r)
    published = c.post(base + f"/bots/{bot.id}/publish", headers=env["a"])
    assert published.status_code == 200 and published.json()["ready"], published.text
    token = c.post(
        f"/api/auth/b/{bot.public_id}",
        json={"init_data": signed_data(contact.telegram_user_id, env["fake"].tokens[bot.telegram_bot_id])},
    ).json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    assert c.get(f"/api/b/{bot.public_id}/me", headers=headers).status_code == 200
    assert len(c.get(f"/api/b/{bot.public_id}/plans", headers=headers).json()) == 2
    checkout = c.post(
        f"/api/b/{bot.public_id}/checkout",
        headers=headers,
        json={"plan_id": plan.id, "idempotency_key": "journey-checkout"},
    )
    assert checkout.status_code == 200, checkout.text
    with r.db.system() as db:
        payment = db.get(m.Payment, checkout.json()["id"])
        secret = db.scalar(select(m.BotSecret).where(m.BotSecret.bot_id == bot.id))
        webhook_secret = r.vault.decrypt(secret.webhook_ciphertext, f"{bot.tenant_id}:{bot.id}:webhook")
    hook_headers = {"X-Telegram-Bot-Api-Secret-Token": webhook_secret}
    query = {
        "id": "query-test",
        "from": {"id": contact.telegram_user_id},
        "invoice_payload": payment.invoice_payload,
        "currency": "XTR",
        "total_amount": 500,
    }
    assert (
        c.post(
            f"/telegram/webhook/{bot.public_id}",
            headers=hook_headers,
            json={"update_id": 100, "pre_checkout_query": query},
        ).status_code
        == 200
    )
    event = {
        "currency": "XTR",
        "total_amount": 500,
        "invoice_payload": payment.invoice_payload,
        "telegram_payment_charge_id": "journey-charge",
    }
    assert (
        c.post(
            f"/telegram/webhook/{bot.public_id}",
            headers=hook_headers,
            json={
                "update_id": 101,
                "message": {"from": {"id": contact.telegram_user_id}, "successful_payment": event},
            },
        ).status_code
        == 200
    )
    drain(r)
    profile = c.get(f"/api/b/{bot.public_id}/me", headers=headers).json()
    assert len(profile["subscriptions"]) == 1 and profile["subscriptions"][0]["status"] == "ACTIVE"
    assert (
        c.post(
            f"/api/b/{bot.public_id}/support", headers=headers, json={"text": "Necesito ayuda con mi plan"}
        ).status_code
        == 200
    )
    report = c.get(base + "/analytics", headers=env["a"])
    assert report.status_code == 200 and report.json()["revenue_minor"] == {"XTR": "500"}


def test_growth_team_and_billing_admin_routes(env):
    c = env["client"]
    base = f"/api/t/{env['ta']}"
    campaign = c.post(
        base + "/campaigns",
        headers=env["a"],
        json={"bot_id": env["ba"], "name": "Campaign", "text": "Hola {{first_name}}"},
    )
    assert campaign.status_code == 201, campaign.text
    assert (
        c.post(
            base + "/campaigns/" + campaign.json()["id"] + "/action",
            headers=env["a"],
            json={"action": "START"},
        ).status_code
        == 200
    )
    rule = c.post(
        base + "/automations",
        headers=env["a"],
        json={
            "bot_id": env["ba"],
            "name": "Welcome",
            "trigger": "START",
            "action": "SEND_MESSAGE",
            "text": "Hello",
        },
    )
    assert rule.status_code == 201, rule.text
    coupon = c.post(
        base + "/coupons",
        headers=env["a"],
        json={"code": "WELCOME10", "percent_off": 10, "max_redemptions": 10, "expires_at": m.now() + 86400},
    )
    assert coupon.status_code == 201, coupon.text
    link = c.post(
        base + "/links",
        headers=env["a"],
        json={"bot_id": env["ba"], "source": "instagram", "campaign": "sept"},
    )
    assert link.status_code == 201 and "?start=" in link.json()["url"]
    member = c.post(base + "/team", headers=env["a"], json={"telegram_user_id": 202, "role": "SUPPORT"})
    assert member.status_code == 200, member.text
    assert c.get(base + "/resources/contacts", headers=env["b"]).status_code == 200
    members = c.get(base + "/resources/team", headers=env["a"]).json()["items"]
    target = next(x for x in members if x["user_id"] == env["ub"])
    assert c.delete(base + "/team/" + target["id"], headers=env["a"]).status_code == 200
    assert c.get(base + "/resources/contacts", headers=env["b"]).status_code == 404
    ticket = c.post(
        "/api/support/tickets",
        headers=env["a"],
        json={"subject": "Help", "text": "Please help with my new bot"},
    )
    assert ticket.status_code == 201
    assert c.get("/api/owner/resources/support", headers=env["a"]).status_code == 200
    assert c.get("/api/owner/health", headers=env["b"]).status_code == 403
