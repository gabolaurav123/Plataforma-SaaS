"""One Seenode Worker: outbound long polling + durable PostgreSQL outbox.

Use one replica. An OS lock prevents duplicate processes in a container; Telegram
409 conflicts stop the service rather than allowing competing pollers. Idle polls
never query PostgreSQL. Incoming updates wake the outbox worker immediately.
"""

import logging
import signal
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import select, func, case, delete, update as sql_update
from . import models as m
from .runtime import Runtime
from .worker import Worker
from .api.webhooks import store_update
from .errors import DomainError, RetryLater
from .services.bots import MASTER_UPDATES, CHILD_UPDATES
from .services.common import enqueue, send

log = logging.getLogger("platform.polling")


@contextmanager
def process_lock(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as stream:
        try:
            if __import__("os").name == "nt":
                import msvcrt

                stream.seek(0)
                stream.write(b"0")
                stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Ya hay un proceso Telegram ejecutándose en este contenedor.") from None
        yield


class Poller:
    def __init__(self, engine, key, tenant_id, client, version):
        self.engine, self.key, self.tenant_id, self.client, self.version = (
            engine,
            key,
            tenant_id,
            client,
            version,
        )
        self.stop = threading.Event()
        with engine.r.db.system() as db:
            cursor = db.scalar(select(m.PollCursor).where(m.PollCursor.bot_key == key))
            self.offset = cursor.next_offset if cursor else 0
        self.thread = threading.Thread(target=self.run, name="telegram-" + key[:8], daemon=True)

    def once(self):
        updates = self.client.call(
            "getUpdates",
            offset=self.offset,
            limit=100,
            timeout=self.engine.r.settings.polling_timeout,
            allowed_updates=MASTER_UPDATES if self.key == "master" else CHILD_UPDATES,
        )
        for update in updates:
            if self.stop.is_set() or self.engine.stop.is_set():
                break
            store_update(
                None if self.key == "master" else self.key,
                self.tenant_id,
                update,
                self.engine.r,
                polling=True,
            )
            # Only advance after the update, outbox job and cursor commit together.
            self.offset = update["update_id"] + 1
            self.engine.wake.set()
            query = update.get("callback_query")
            if query:
                # Processing wakes after the durable insert and can overlap this UI acknowledgement.
                try:
                    self.client.call("answerCallbackQuery", callback_query_id=query["id"])
                except DomainError:
                    pass

    def run(self):
        failures = 0
        while not self.stop.is_set() and not self.engine.stop.is_set():
            try:
                self.once()
                failures = 0
            except Exception as error:
                code = error.code if isinstance(error, (DomainError, RetryLater)) else "POLLING_STORAGE_ERROR"
                log.error("poll_failed bot=%s code=%s", self.key, code)
                if code in {"POLLING_CONFLICT", "TOKEN_INVALID"}:
                    if self.key == "master":
                        self.engine.fatal = (
                            "Revisa el token maestro y mantén una sola réplica sin otro webhook."
                        )
                        self.engine.stop.set()
                    else:
                        with self.engine.r.db.system() as db:
                            bot = db.get(m.ManagedBot, self.key)
                            if bot:
                                bot.last_error_code = code
                                if bot.connection_kind == "TOKEN" or code == "POLLING_CONFLICT":
                                    bot.status = "CONNECTION_ERROR"
                                    db.info["bots_changed"] = True
                                    send(
                                        db,
                                        None,
                                        bot.owner_telegram_user_id,
                                        f"⚠️ @{bot.username}: revisa la conexión desde tu cuenta SaaS. "
                                        + (
                                            "El token fue revocado; reemplázalo desde Conexión."
                                            if code == "TOKEN_INVALID"
                                            else "Otro servicio está usando este bot. Detén ese servicio y vuelve a conectar."
                                        ),
                                        f"connection-error:{bot.id}:{self.version}:{code}",
                                    )
                                else:
                                    enqueue(
                                        db,
                                        "PROVISION",
                                        bot.tenant_id,
                                        {},
                                        f"token-repair:{bot.id}:{self.version}",
                                        bot.id,
                                    )
                    self.engine.wake.set()
                    return
                failures += 1
                delay = error.seconds if isinstance(error, RetryLater) else min(60, 2 ** min(failures, 6))
                self.stop.wait(delay)


class PollingEngine:
    def __init__(self, runtime):
        self.r, self.worker = runtime, Worker(runtime)
        self.stop, self.wake = threading.Event(), threading.Event()
        self.pollers, self.fatal = {}, None
        self.drainers = []

    def reconcile(self):
        if self.r.settings.telegram_transport == "webhook":
            return
        desired = {"master": (None, self.r.clients.master(), 1)}
        with self.r.db.system() as db:
            bots = list(
                db.scalars(
                    select(m.ManagedBot)
                    .where(
                        m.ManagedBot.status.not_in(
                            [
                                "OWNERSHIP_CHANGED",
                                "SUSPENDED",
                                "DISCONNECTED",
                                "CONNECTION_ERROR",
                                "PROVISIONING",
                            ]
                        )
                    )
                    .order_by(m.ManagedBot.id)
                )
            )
            if len(bots) > self.r.settings.polling_max_bots:
                raise RuntimeError(
                    "Se superó POLLING_MAX_BOTS; amplía capacidad antes de incorporar más bots."
                )
            for bot in bots:
                secret = db.scalar(select(m.BotSecret).where(m.BotSecret.bot_id == bot.id))
                if secret:
                    desired[bot.id] = (bot.tenant_id, self.r.clients.child(db, bot), secret.token_version)
                    if bot.id not in self.pollers:
                        enqueue(
                            db, "REGISTER_COMMANDS", bot.tenant_id, {}, f"commands-id:{bot.id}:0006", bot.id
                        )
        for key, poller in list(self.pollers.items()):
            if key not in desired or desired[key][2] != poller.version:
                poller.stop.set()
                # Never launch the replacement until its previous getUpdates request ends.
                poller.thread.join(self.r.settings.polling_timeout + 9)
                if poller.thread.is_alive():
                    raise RuntimeError("El lector anterior no terminó; reinicia una sola réplica.")
                del self.pollers[key]
                self.r.clients.retire(key, poller.version)
        for key, (tid, client, version) in desired.items():
            if key not in self.pollers:
                poller = Poller(self, key, tid, client, version)
                self.pollers[key] = poller
                poller.thread.start()

    def maintenance(self):
        with self.r.db.system() as db:
            enqueue(db, "TICK", None, {}, f"tick:{m.now() // 60}")
            db.execute(delete(m.ConsoleButton).where(m.ConsoleButton.expires_at < m.now()))
            db.execute(delete(m.ConsoleState).where(m.ConsoleState.expires_at < m.now()))
            for attempt in db.scalars(
                select(m.ConnectionAttempt).where(
                    m.ConnectionAttempt.expires_at < m.now(),
                    m.ConnectionAttempt.status.in_(["PENDING", "VALIDATED"]),
                )
            ):
                attempt.status, attempt.token_ciphertext = "EXPIRED", None
            for report in db.scalars(
                select(m.Report).where(
                    m.Report.expires_at < m.now(), m.Report.content_ciphertext.is_not(None)
                )
            ):
                report.content_ciphertext, report.status = None, "EXPIRED"
            db.execute(
                sql_update(m.TelegramUpdate)
                .where(
                    m.TelegramUpdate.status == "FAILED", m.TelegramUpdate.created_at < m.now() - 14 * 86400
                )
                .values(sensitive_ciphertext=None)
            )
            db.execute(
                sql_update(m.ProviderEvent)
                .where(
                    m.ProviderEvent.status.in_(["FAILED", "REVIEW_REQUIRED"]),
                    m.ProviderEvent.created_at < m.now() - 14 * 86400,
                )
                .values(payload_ciphertext=None)
            )
            # Keep durable offsets forever; prune only completed transport data, not business records.
            db.execute(
                delete(m.TelegramUpdate).where(
                    m.TelegramUpdate.status == "DONE", m.TelegramUpdate.created_at < m.now() - 7 * 86400
                )
            )

    def deadline(self, maintenance_at, lane=None):
        with self.r.db.system() as db:
            dates = [maintenance_at]
            due, stale = db.execute(
                select(
                    func.min(case((m.Job.status == "PENDING", m.Job.run_at))),
                    func.min(case((m.Job.status == "RUNNING", m.Job.lease_until))),
                ).where(m.Job.status.in_(["PENDING", "RUNNING"]), m.Job.lane == lane if lane else True)
            ).one()
            if due is not None:
                dates.append(due)
            if stale is not None:
                dates.append(stale)
            return max(0.1, min(dates) - time.time())

    def drain(self, lane, wake):
        worker = Worker(self.r, lane)
        while not self.stop.is_set():
            wake.clear()
            try:
                if worker.run_one():
                    continue
                delay = self.deadline(m.now() + self.r.settings.maintenance_interval, lane)
            except Exception:
                log.error("queue_unavailable lane=%s", lane)
                delay = 5
            wake.wait(min(delay, self.r.settings.maintenance_interval))

    def run(self):
        server, http_thread = None, None
        if self.r.settings.payment_webhooks_enabled or self.r.settings.telegram_transport == "webhook":
            import uvicorn
            from .ingress import create_ingress

            server = uvicorn.Server(
                uvicorn.Config(
                    create_ingress(self.r),
                    host="0.0.0.0",
                    port=self.r.settings.port,
                    access_log=False,
                    log_level="warning",
                )
            )
            http_thread = threading.Thread(target=server.run, name="webhook-listener", daemon=True)
            http_thread.start()
            deadline = time.monotonic() + 15
            while not server.started:
                if not http_thread.is_alive() or time.monotonic() >= deadline:
                    server.should_exit = True
                    raise RuntimeError("WEBHOOK_LISTENER_START_FAILED")
                self.stop.wait(0.05)
        capability = self.r.manager.configure_master()
        self.reconcile()
        log.info(
            "telegram_worker_ready master=@%s managed_bots_enabled=%s active_readers=%d maintenance_seconds=%d",
            capability["username"],
            capability["enabled"],
            len(self.pollers),
            self.r.settings.maintenance_interval,
        )
        next_maintenance = 0
        for lane, count in [
            ("interactive", self.r.settings.interactive_workers),
            ("background", self.r.settings.background_workers),
        ]:
            for _ in range(count):
                wake = threading.Event()
                self.r.job_wakeups.append(wake)
                thread = threading.Thread(
                    target=self.drain, args=(lane, wake), name="queue-" + lane, daemon=True
                )
                self.drainers.append((thread, wake))
                thread.start()
        try:
            while not self.stop.is_set():
                if http_thread and not http_thread.is_alive():
                    self.fatal = "WEBHOOK_LISTENER_STOPPED"
                    break
                self.wake.clear()
                if m.now() >= next_maintenance:
                    self.maintenance()
                    next_maintenance = m.now() + self.r.settings.maintenance_interval
                    self.reconcile()
                if self.r.bot_config_changed.is_set():
                    self.r.bot_config_changed.clear()
                    self.reconcile()
                # Metadata is refreshed on change or maintenance, never after each message.
                self.r.bot_config_changed.wait(min(1, max(0.1, next_maintenance - time.time())))
        finally:
            self.stop.set()
            for thread, wake in self.drainers:
                wake.set()
            for thread, wake in self.drainers:
                thread.join(15)
                self.r.job_wakeups.remove(wake)
            for poller in self.pollers.values():
                poller.stop.set()
            for poller in self.pollers.values():
                poller.thread.join(self.r.settings.polling_timeout + 9)
            if server:
                server.should_exit = True
                http_thread.join(15)
        if self.fatal:
            raise RuntimeError(self.fatal)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    runtime = Runtime()
    if runtime.settings.deployment_mode != "telegram":
        raise SystemExit("Configura DEPLOYMENT_MODE=telegram para este comando.")
    if runtime.settings.environment == "production":
        runtime.db.verify_production_boundary()
    engine = PollingEngine(runtime)

    def stop(*_):
        engine.stop.set()
        engine.wake.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with process_lock(Path(runtime.settings.storage_path) / "telegram-worker.lock"):
        try:
            engine.run()
        finally:
            runtime.close()


if __name__ == "__main__":
    main()
