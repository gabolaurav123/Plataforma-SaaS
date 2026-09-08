"""Run against an isolated local PostgreSQL; CI supplies PostgreSQL 18."""

import base64
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import create_engine, event, select, text, func
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from platform_app import models as m
from platform_app.config import Settings
from platform_app.runtime import Runtime
from platform_app.worker import Worker
from platform_app.api.webhooks import store_update
from platform_app.services.common import enqueue
from platform_app.services.tenants import create_tenant, upsert_user
from conftest import FakeTelegram

pytestmark = pytest.mark.postgres


@pytest.fixture
def pg_runtime():
    uri = os.environ.get("PG_TEST_URL")
    if not uri:
        pytest.skip("PG_TEST_URL is not set")
    assert make_url(uri).host in {"localhost", "127.0.0.1"}, "Local test database required"
    root = create_engine(uri, connect_args={"prepare_threshold": None})
    schema = "qa_" + m.uid().replace("-", "")
    with root.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
        pglite = "PGlite" in db.scalar(text("SELECT version()"))
    root.dispose()
    r = Runtime(
        Settings(
            _env_file=None,
            database_url=uri,
            system_database_url=None,
            master_bot_token="100001:" + "M" * 35,
            encryption_keys=json.dumps({"v1": base64.b64encode(b"x" * 32).decode()}),
        ),
        FakeTelegram(),
    )

    @event.listens_for(r.db.engine, "connect")
    def set_schema(conn, record):
        conn.prepare_threshold = None
        conn.autocommit = True
        conn.execute(f'SET search_path TO "{schema}"')
        conn.autocommit = False

    m.Base.metadata.create_all(r.db.engine)
    with r.db.system() as db:
        tenants = [
            create_tenant(
                db, upsert_user(db, {"id": i, "first_name": "Queue test"}), "Queue test", r.settings
            ).id
            for i in (101, 202)
        ]
    try:
        yield r, tenants, pglite
    finally:
        r.db.engine.dispose()
        with root.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()


def update(number):
    return {
        "update_id": number,
        "message": {
            "message_id": number,
            "text": "/id",
            "from": {"id": 101},
            "chat": {"id": 101, "type": "private"},
        },
    }


def test_postgres_atomic_ingestion_dedup(pg_runtime):
    r, _, _ = pg_runtime
    store_update(None, None, update(7001), r, polling=True)
    assert store_update(None, None, update(7001), r, polling=True)["duplicate"]
    store_update(None, None, update(7000), r, polling=True)
    with r.db.system() as db:
        assert db.scalar(select(m.PollCursor.next_offset)) == 7002
        assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind == "UPDATE")) == 2
        assert db.scalar(
            select(m.TelegramUpdate).where(m.TelegramUpdate.update_id == 7001)
        ).sensitive_ciphertext


def test_postgres_atomic_ingestion_rolls_back_cursor(pg_runtime):
    r, _, pglite = pg_runtime
    if pglite:
        pytest.skip("Error/rollback wire protocol is checked on real PostgreSQL 18 in CI")
    store_update(None, None, update(7001), r, polling=True)
    with r.db.system() as db:
        db.execute(text("ALTER TABLE jobs ADD CONSTRAINT reject_update CHECK (kind <> 'UPDATE') NOT VALID"))
    with pytest.raises(IntegrityError):
        store_update(None, None, update(7002), r, polling=True)
    with r.db.system() as db:
        assert db.scalar(select(m.PollCursor.next_offset)) == 7002
        assert not db.scalar(select(m.TelegramUpdate.id).where(m.TelegramUpdate.update_id == 7002))


def test_postgres_claim_fairness_and_stream_order(pg_runtime):
    r, tids, _ = pg_runtime
    a, b = sorted(tids)
    with r.db.system() as db:
        first = enqueue(db, "UPDATE", a, {}, "first", lane="interactive", stream_key="s", sequence=1)
        second = enqueue(db, "SEND", a, {}, "second", lane="interactive", stream_key="s", sequence=2)
        other = enqueue(db, "UPDATE", b, {}, "other", lane="interactive", stream_key="other", sequence=1)
        ids = first.id, second.id, other.id
    worker = Worker(r, "interactive")
    assert worker.claim() == ids[0]
    assert worker.claim() == ids[2]
    assert worker.claim() is None
    with r.db.system() as db:
        db.get(m.Job, ids[0]).status = "DONE"
    assert worker.claim() == ids[1]


def test_postgres_expired_send_is_never_retried_blindly(pg_runtime):
    r, _, _ = pg_runtime
    with r.db.system() as db:
        job = enqueue(
            db,
            "SEND",
            None,
            {"chat_id": 101, "text": "Already possibly sent"},
            "stale-send",
            lane="interactive",
        )
        job.status, job.lease_until, job.lease_owner = "RUNNING", m.now() - 10, "old-worker"
        job_id = job.id
    assert Worker(r, "interactive").claim() is None
    with r.db.system() as db:
        assert db.get(m.Job, job_id).status == "DELIVERY_UNKNOWN"


def test_postgres_two_consumers_cannot_claim_same_job(pg_runtime):
    r, _, pglite = pg_runtime
    if pglite:
        pytest.skip("PGlite sockets share one session; CI runs this on PostgreSQL 18")
    with r.db.system() as db:
        job = enqueue(db, "UPDATE", None, {}, "concurrent", lane="interactive")
        job_id = job.id
    barrier = Barrier(2)

    def claim(_):
        worker = Worker(r, "interactive")
        barrier.wait(timeout=10)
        return worker.claim()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(claim, range(2)))
    assert results.count(job_id) == 1 and results.count(None) == 1


def test_reserved_reply_is_durable_before_telegram_send(pg_runtime, monkeypatch):
    r, _, pglite = pg_runtime
    if pglite:
        pytest.skip("Independent transaction visibility is checked on PostgreSQL 18")
    r.settings.deployment_mode = "telegram"
    store_update(None, None, update(7101), r, polling=True)
    client = r.clients.master()
    original, observed = client.call, []

    def deliver(method, **params):
        if method == "sendMessage":
            with r.db.system() as db:
                assert db.scalar(select(m.TelegramUpdate.status)) == "DONE"
                assert db.scalar(select(m.Job.status).where(m.Job.kind == "UPDATE")) == "DONE"
                assert db.scalar(select(m.Job.status).where(m.Job.kind == "SEND")) == "RUNNING"
                assert db.scalar(select(func.count()).select_from(m.ConsoleButton)) > 0
                observed.append(params["text"])
        return original(method, **params)

    monkeypatch.setattr(client, "call", deliver)
    worker = Worker(r, "interactive")
    assert worker.run_one() and len(observed) == 1
    assert not worker.run_one()
    with r.db.system() as db:
        reply = db.scalar(select(m.Job).where(m.Job.kind == "SEND"))
        assert reply.status == "DONE" and reply.payload["response_ms"] >= 0


def test_crash_after_reserving_reply_never_causes_automatic_resend(pg_runtime, monkeypatch):
    r, _, _ = pg_runtime
    r.settings.deployment_mode = "telegram"
    store_update(None, None, update(7102), r, polling=True)
    with r.db.system() as db:
        update_id = db.scalar(select(m.Job.id).where(m.Job.kind == "UPDATE"))
    worker = Worker(r, "interactive")
    original = worker.process_claimed

    def crash_before_delivery(job_id):
        if job_id != update_id:
            raise SystemExit("Simulated process death after commit")
        return original(job_id)

    monkeypatch.setattr(worker, "process_claimed", crash_before_delivery)
    with pytest.raises(SystemExit):
        worker.run_one()
    with r.db.system() as db:
        assert db.get(m.Job, update_id).status == "DONE"
        reply = db.scalar(select(m.Job).where(m.Job.kind == "SEND"))
        assert reply.status == "RUNNING" and reply.attempts == 1
        reply.lease_until = m.now() - 1
    assert Worker(r, "interactive").claim() is None
    with r.db.system() as db:
        assert db.scalar(select(m.Job.status).where(m.Job.kind == "SEND")) == "DELIVERY_UNKNOWN"


def test_reply_rolled_back_by_dialog_is_not_reserved(pg_runtime, monkeypatch):
    from platform_app.services.console import Console
    from platform_app.errors import DomainError

    r, _, _ = pg_runtime
    r.settings.deployment_mode = "telegram"
    with r.db.system() as db:
        db.add(m.ConsoleState(bot_key="master", telegram_user_id=101, expires_at=m.now() + 3600))

    def fail_after_reply(ui, message, query):
        ui.say("Rolled back reply")
        raise DomainError("TEST_ERROR", "Expected test failure")

    monkeypatch.setattr(Console, "run", fail_after_reply)
    request = update(7103)
    request["message"]["text"] = "form answer"
    store_update(None, None, request, r, polling=True)
    assert Worker(r, "interactive").run_one()
    with r.db.system() as db:
        replies = list(db.scalars(select(m.Job).where(m.Job.kind == "SEND")))
        assert len(replies) == 1 and replies[0].status == "DONE"
        assert "Rolled back reply" not in replies[0].payload["text"]
