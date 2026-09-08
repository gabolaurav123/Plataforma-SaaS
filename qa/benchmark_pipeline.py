"""Isolated PostgreSQL benchmark: ingestion -> durable UPDATE -> Telegram SEND.

Telegram delivery is simulated. Optional RTT is charged per SQL statement, not
presented as a production measurement. Never accepts a remote database host.
"""

import argparse
import base64
import json
from pathlib import Path
import statistics
import sys
import time
import uuid

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
parser.add_argument("--port", type=int, default=55443)
parser.add_argument("--rtt-ms", type=int, default=0)
parser.add_argument("--samples", type=int, default=6)
args = parser.parse_args()
sys.path.insert(0, str(args.source / "backend"))
from sqlalchemy import create_engine, event, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from platform_app import models as m  # noqa: E402
from platform_app.config import Settings  # noqa: E402
from platform_app.runtime import Runtime  # noqa: E402
from platform_app.worker import Worker  # noqa: E402
from platform_app.api.webhooks import store_update  # noqa: E402
from platform_app.services.tenants import upsert_user, create_tenant  # noqa: E402

url = f"postgresql+psycopg://postgres:postgres@127.0.0.1:{args.port}/postgres?sslmode=disable&gssencmode=disable"


@event.listens_for(Engine, "connect")
def disable_socket_prepared_statements(connection, record):
    connection.prepare_threshold = None  # PGlite socket multiplexes a single server session.


schema = "bench_" + uuid.uuid4().hex
engine = create_engine(url)
with engine.begin() as db:
    db.execute(text(f'CREATE SCHEMA "{schema}"'))
engine.dispose()
settings = Settings(
    _env_file=None,
    database_url=url + "&options=-csearch_path%3D" + schema,
    system_database_url=None,
    deployment_mode="telegram",
    master_bot_username="benchmark_bot",
    master_bot_token="100001:" + "M" * 35,
    platform_owner_ids="101",
    encryption_keys=json.dumps({"v1": base64.b64encode(b"x" * 32).decode()}),
    user_rps=10000,
    bot_rps=10000,
    tenant_rps=10000,
    global_rps=10000,
)


class FakeTelegram:
    sent = 0

    def __call__(self, *args, **kwargs):
        return self

    def call(self, method, **params):
        if method == "sendMessage":
            self.sent += 1
            return {"message_id": self.sent}
        return True


api = FakeTelegram()
r = Runtime(settings, api)


@event.listens_for(r.db.engine, "connect")
def set_benchmark_schema(connection, record):
    connection.autocommit = True
    connection.execute(f'SET search_path TO "{schema}"')
    connection.autocommit = False


with r.db.system() as db:
    assert db.scalar(text("SELECT current_schema()")) == schema, "Benchmark schema isolation failed"
m.Base.metadata.create_all(r.db.engine)
with r.db.system() as db:
    user = upsert_user(db, {"id": 101, "first_name": "Benchmark"})
    create_tenant(db, user, "Benchmark business", settings)
worker = Worker(r, "interactive")
queries, enabled = [], False


def count(conn, cursor, statement, parameters, context, many):
    if enabled:
        queries.append(statement.split()[0] + " " + statement.split("\n")[0][:90])
        if args.rtt_ms:
            time.sleep(args.rtt_ms / 1000)


event.listen(r.db.engine, "before_cursor_execute", count)
results = []
try:
    for i in range(args.samples + 1):
        number = 870000 + i
        command = "/start" if i % 2 == 0 else "/admin"
        update = {
            "update_id": number,
            "message": {
                "message_id": number,
                "text": command,
                "from": {"id": 101, "first_name": "Benchmark"},
                "chat": {"id": 101, "type": "private"},
            },
        }
        queries.clear()
        enabled = True
        start, sent = time.perf_counter(), api.sent
        store_update(None, None, update, r, polling=True)
        for _ in range(10):
            worker.run_one()
            if api.sent > sent:
                break
        assert api.sent == sent + 1, "First response was not delivered"
        elapsed = round((time.perf_counter() - start) * 1000, 2)
        enabled = False
        if i:
            results.append({"command": command, "elapsed_ms": elapsed, "sql_statements": len(queries)})
    print(
        json.dumps(
            {
                "source": args.source.name,
                "telegram": "simulated",
                "injected_sql_rtt_ms": args.rtt_ms,
                "median_ms": statistics.median(x["elapsed_ms"] for x in results),
                "samples": results,
                "last_trace": queries,
            },
            indent=2,
        )
    )
finally:
    r.db.engine.dispose()
    with engine.begin() as db:
        db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()
