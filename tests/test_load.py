"""Small deterministic routing/load smoke, not a production throughput claim."""

import pytest
from sqlalchemy import select, func
from platform_app import models as m
from platform_app.services.common import enqueue
from platform_app.worker import Worker


@pytest.mark.parametrize("bot_count", [100, 1000, 10000])
def test_indexed_multi_bot_routing(env, bot_count):
    with env["r"].db.system() as db:
        db.add_all(
            [
                m.ManagedBot(
                    id=m.uid(),
                    tenant_id=env["ta"],
                    telegram_bot_id=10000000 + i,
                    owner_telegram_user_id=101,
                    public_id=f"load-{i}",
                    username=f"load_{i}_bot",
                    name=f"Load {i}",
                )
                for i in range(bot_count)
            ]
        )
    with env["r"].db.system() as db:
        for index in [0, bot_count // 2, bot_count - 1]:
            bot = db.scalar(select(m.ManagedBot).where(m.ManagedBot.public_id == f"load-{index}"))
            assert bot.telegram_bot_id == 10000000 + index and bot.tenant_id == env["ta"]
        assert db.scalar(select(func.count()).select_from(m.ManagedBot)) == bot_count + 2


def test_stale_send_is_not_delivered_twice(env):
    with env["r"].db.system() as db:
        job = enqueue(db, "SEND", env["ta"], {"chat_id": 900001, "text": "test"}, "crash-recovery", env["ba"])
        job.status, job.lease_until = "RUNNING", m.now() - 1
        job_id = job.id
    assert Worker(env["r"]).claim() is None
    with env["r"].db.system() as db:
        assert db.get(m.Job, job_id).status == "DELIVERY_UNKNOWN"
