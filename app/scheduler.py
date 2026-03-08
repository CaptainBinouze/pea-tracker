"""
Intraday scheduler — APScheduler BackgroundScheduler.

Fetches live quotes and evaluates alerts every N minutes during Euronext
market hours (Mon–Fri, configurable open/close CET).

Activation: set ``ENABLE_INTRADAY=true`` in the environment.
"""

import logging
from datetime import datetime, timedelta, timezone

from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_scheduler = None  # singleton reference


def _is_market_open(app) -> bool:
    """Return True if we are within Euronext trading hours (CET/CEST)."""
    cet = ZoneInfo("Europe/Paris")
    now = datetime.now(cet)
    # Monday=0 … Friday=4
    if now.weekday() > 4:
        return False
    hour = now.hour + now.minute / 60.0
    return app.config["MARKET_OPEN_HOUR"] <= hour < app.config["MARKET_CLOSE_HOUR"]


def _intraday_job(app):
    """Single scheduler tick: fetch live quotes then evaluate alerts.

    Includes a timestamp-based dedup check so that if multiple workers
    each run their own scheduler, only the first one to fire actually
    does the work.
    """
    with app.app_context():
        if not _is_market_open(app):
            logger.debug("[scheduler] Market closed \u2014 skipping intraday fetch.")
            return

        # --- Dedup: skip if another worker already ran this tick -------------
        from app.extensions import db
        from app.models import LiveQuote

        interval = app.config.get("INTRADAY_INTERVAL_MINUTES", 10)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=interval - 2)
        recent = db.session.query(db.func.max(LiveQuote.updated_at)).scalar()
        if recent and recent >= cutoff:
            logger.debug("[scheduler] Another worker already ran this tick \u2014 skipping.")
            return

        from app.market.services import fetch_live_quotes
        from app.alerts.services import evaluate_alerts

        try:
            count = fetch_live_quotes()
            logger.info("[scheduler] Fetched %d live quote(s).", count)
        except Exception as exc:
            logger.error("[scheduler] fetch_live_quotes failed: %s", exc)
            return

        try:
            triggered = evaluate_alerts(use_live=True)
            if triggered:
                logger.info("[scheduler] %d alert(s) triggered.", len(triggered))
        except Exception as exc:
            logger.error("[scheduler] evaluate_alerts failed: %s", exc)


def init_scheduler(app):
    """Start the APScheduler BackgroundScheduler if ENABLE_INTRADAY is set.

    Safe to call from every Gunicorn worker \u2014 the job itself contains a
    timestamp-based dedup check so only one worker does actual work per
    tick.  The ``_scheduler`` singleton guard prevents double-init within
    the same process.
    """
    global _scheduler

    if not app.config.get("ENABLE_INTRADAY"):
        logger.info("[scheduler] Intraday disabled (ENABLE_INTRADAY is not set).")
        return

    if _scheduler is not None:
        logger.debug("[scheduler] Already initialised — skipping.")
        return

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    interval = app.config.get("INTRADAY_INTERVAL_MINUTES", 10)

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _intraday_job,
        trigger=IntervalTrigger(minutes=interval),
        args=[app],
        id="intraday_update",
        name=f"Intraday live quotes (every {interval} min)",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "[scheduler] Started — fetching live quotes every %d min during market hours.",
        interval,
    )
