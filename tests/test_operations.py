from sqlalchemy import select
from platform_app import models as m
from platform_app.cache import PublicConfigCache
from platform_app.worker import Worker
from conftest import bot_parts, signed_data


def test_public_catalog_cache_invalidates_after_creator_plan_change(env):
    client, r = env["client"], env["r"]
    bot, contact, plan = bot_parts(env)
    token = client.post(
        f"/api/auth/b/{bot.public_id}",
        json={"init_data": signed_data(contact.telegram_user_id, env["fake"].tokens[bot.telegram_bot_id])},
    ).json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    url = f"/api/b/{bot.public_id}/plans"
    first = client.get(url, headers=headers).json()
    assert first[0]["prices"][0]["amount_minor"] == "500"
    saved = client.put(
        f"/api/t/{bot.tenant_id}/plans/{plan.id}",
        headers=env["a"],
        json={
            "bot_id": bot.id,
            "name": "Updated",
            "duration_days": 30,
            "prices": [{"provider": "TELEGRAM_STARS", "currency": "XTR", "amount_minor": 750}],
        },
    )
    assert saved.status_code == 200
    refreshed = client.get(url, headers=headers).json()
    assert refreshed[0]["name"] == "Updated" and refreshed[0]["prices"][0]["amount_minor"] == "750"
    other = bot_parts(env, "b")[0]
    assert (
        r.public_cache.read(other, "plans", lambda: [{"name": "Other tenant"}])[0]["name"] == "Other tenant"
    )


def test_health_scanner_deduplicates_and_quarantines_ownership_changes(env):
    r, worker = env["r"], Worker(env["r"])
    with r.db.system() as db:
        db.get(m.ManagedBot, env["bb"]).status = "OWNERSHIP_CHANGED"
        worker.tick(db)
        worker.tick(db)
        scans = list(db.scalars(select(m.Job).where(m.Job.kind == "HEALTH_SCAN")))
        assert len(scans) == 1
        worker.dispatch(db, scans[0])
        health = list(db.scalars(select(m.Job).where(m.Job.kind == "HEALTH")))
        assert len(health) == 1 and health[0].bot_id == env["ba"]


def test_cached_public_values_cannot_be_mutated_by_another_caller(env):
    cache, bot = PublicConfigCache(capacity=1), bot_parts(env)[0]
    loaded = cache.read(bot, "catalog", lambda: {"plans": [{"name": "Premium"}]})
    loaded["plans"][0]["name"] = "Corrupted"
    assert cache.read(bot, "catalog", lambda: None)["plans"][0]["name"] == "Premium"
