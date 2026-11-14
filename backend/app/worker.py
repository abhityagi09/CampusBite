"""Dedicated reminder worker: ``python -m app.worker`` (the ``scheduler`` Compose service).

* APScheduler runs the job every ORDER_REMINDER_CHECK_INTERVAL_SECONDS (default 60), independent of HTTP
  traffic. The API process does not schedule anything.
* One job at a time per process (max_instances=1, coalesce): a slow run never overlaps the next.
* Across processes/containers a PostgreSQL advisory lock lets only one run proceed at a time;
  the others skip. Even without the lock, the UNIQUE event_key prevents duplicate reminders.
* Runs once immediately on start, so reminders missed while the worker was down are caught up.
* SIGTERM/SIGINT: stop scheduling and let the running job finish (each reminder commits on
  its own, so an interrupted run loses nothing that was recorded).
"""

import logging
import signal
import threading
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from app.core.config import settings
from app.database.session import SessionLocal, engine
from app.services.notifications import MockNotifier
from app.services.reminder_service import ReminderRunResult, process_reminders

log = logging.getLogger("campusbite.worker")
LOCK_KEY = 0x43425244  # "CBRD": CampusBite reminders
_notifier = MockNotifier()  # swap for a real e-mail / push adapter later


def run_once(session_factory=SessionLocal, bind=engine, notifier=None, now=None) -> ReminderRunResult | None:
    """One reminder pass. Returns None if another process holds the lock."""
    with bind.connect() as lock_conn:
        postgres = lock_conn.dialect.name == "postgresql"
        if postgres and not lock_conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}):
            log.info("another reminder run is in progress; skipping")
            return None
        try:
            with session_factory() as db:
                result = process_reminders(db, notifier or _notifier, now)
            if result.sent or result.failed:
                log.info("reminders: sent=%s duplicates=%s failed=%s",
                         result.sent, result.skipped_duplicates, result.failed)
            return result
        finally:
            if postgres:  # (also released automatically if the connection dies)
                lock_conn.scalar(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})


def _job() -> None:
    try:
        run_once()
    except Exception:  # keep the scheduler alive; the next tick retries
        log.exception("reminder run failed")


def build_scheduler(interval_seconds: int) -> BlockingScheduler:
    scheduler = BlockingScheduler(
        timezone=timezone.utc,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 30},
    )
    scheduler.add_job(_job, IntervalTrigger(seconds=interval_seconds), id="order-reminders",
                      next_run_time=datetime.now(timezone.utc), replace_existing=True)
    return scheduler


def main() -> None:  # pragma: no cover - process entry point
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.REMINDER_SCHEDULER_ENABLED:
        # Stay up (no restart loop under `restart: unless-stopped`) but do nothing.
        log.warning("REMINDER_SCHEDULER_ENABLED=false: reminder worker idle")
        stopped = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stopped.set())
        stopped.wait()
        return
    interval = settings.ORDER_REMINDER_CHECK_INTERVAL_SECONDS
    scheduler = build_scheduler(interval)

    def stop(signum, _frame):
        log.info("signal %s received, shutting down", signum)
        scheduler.shutdown(wait=True)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("reminder worker started (every %ss, threshold %s min)",
             interval, settings.ORDER_REMINDER_THRESHOLD_MINUTES)
    scheduler.start()
    engine.dispose()


if __name__ == "__main__":
    main()
