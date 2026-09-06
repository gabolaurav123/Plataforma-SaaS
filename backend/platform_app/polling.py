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
from sqlalchemy import select, func, delete
from . import models as m
from .runtime import Runtime
from .worker import Worker
from .api.webhooks import store_update
from .errors import DomainError, RetryLater
from .services.bots import MASTER_UPDATES, CHILD_UPDATES
from .services.common import enqueue

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
            query = update.get("callback_query")
            if query:
                # UI acknowledgement has no business effect and must not wait behind campaigns.
                try:
                    self.client.call("answerCallbackQuery", callback_query_id=query["id"])
                except DomainError:
                    pass
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

    def run(self):
        failures = 0
        while not self.stop.is_set() and not self.engine.stop.is_set():
            try:
                self.once()
                failures = 0
            except Exception as error:
                code = error.code if isinstance(error, (DomainError, RetryLater)) else "POLLING_STORAGE_ERROR"
                log.error("poll_failed bot=%s code=%s", self.key, code)
                if code == "POLLING_CONFLICT":
                    self.engine.fatal = "Telegram detectó otro proceso o webhook. Mantén una sola réplica."
                    self.engine.stop.set()
                    self.engine.wake.set()
                    return
                failures += 1
                if code == "TOKEN_INVALID" and self.key != "master" and failures == 1:
                    try:
                        with self.engine.r.db.system() as db:
                            bot = db.get(m.ManagedBot, self.key)
                            if bot:
                                bot.last_error_code = code
                                enqueue(
                                    db,
                                    "PROVISION",
                                    self.tenant_id,
                                    {},
                                    f"poll-token-repair:{self.key}:{m.now() // 900}",
                                    self.key,
                                )
                        self.engine.wake.set()
                    except Exception:
                        log.error("token_repair_enqueue_failed bot=%s", self.key)
                delay = error.seconds if isinstance(error, RetryLater) else min(60, 2 ** min(failures, 6))
                self.stop.wait(delay)


class PollingEngine:
    def __init__(self, runtime):
        self.r, self.worker = runtime, Worker(runtime)
        self.stop, self.wake = threading.Event(), threading.Event()
        self.pollers, self.fatal = {}, None

    def reconcile(self):
        desired = {"master": (None, self.r.clients.master(), 1)}
        with self.r.db.system() as db:
            bots = list(
                db.scalars(
                    select(m.ManagedBot)
                    .where(m.ManagedBot.status.not_in(["OWNERSHIP_CHANGED", "SUSPENDED"]))
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
        for key, poller in list(self.pollers.items()):
            if key not in desired or desired[key][2] != poller.version:
                poller.stop.set()
                # Never launch the replacement until its previous getUpdates request ends.
                poller.thread.join(self.r.settings.polling_timeout + 9)
                if poller.thread.is_alive():
                    raise RuntimeError("El lector anterior no terminó; reinicia una sola réplica.")
                del self.pollers[key]
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
            # Keep durable offsets forever; prune only completed transport data, not business records.
            db.execute(
                delete(m.TelegramUpdate).where(
                    m.TelegramUpdate.status == "DONE", m.TelegramUpdate.created_at < m.now() - 7 * 86400
                )
            )

    def deadline(self, maintenance_at):
        with self.r.db.system() as db:
            dates = [maintenance_at]
            due = db.scalar(select(func.min(m.Job.run_at)).where(m.Job.status == "PENDING"))
            stale = db.scalar(select(func.min(m.Job.lease_until)).where(m.Job.status == "RUNNING"))
            if due is not None:
                dates.append(due)
            if stale is not None:
                dates.append(stale)
            return max(0.1, min(dates) - time.time())

    def run(self):
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
        try:
            while not self.stop.is_set():
                self.wake.clear()
                if m.now() >= next_maintenance:
                    self.maintenance()
                    next_maintenance = m.now() + self.r.settings.maintenance_interval
                    self.reconcile()
                # Bound each drain so maintenance and newly provisioned bots cannot starve.
                until = time.monotonic() + 2
                worked = False
                while not self.stop.is_set() and self.worker.run_one():
                    worked = True
                    if time.monotonic() >= until:
                        break
                if worked:
                    self.reconcile()
                self.wake.wait(min(self.deadline(next_maintenance), self.r.settings.maintenance_interval))
        finally:
            self.stop.set()
            for poller in self.pollers.values():
                poller.stop.set()
            for poller in self.pollers.values():
                poller.thread.join(self.r.settings.polling_timeout + 9)
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
        engine.run()


if __name__ == "__main__":
    main()
