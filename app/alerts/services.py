"""
Alert evaluation logic.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.extensions import db
from app.models import Alert, DailyPrice, LiveQuote
from app.notifications.dispatcher import dispatch_alert_notifications

logger = logging.getLogger(__name__)


def evaluate_alerts(*, use_live: bool = False) -> list[dict]:
    """
    Check all active alerts against latest prices.

    When *use_live* is ``True`` the price is read from ``LiveQuote`` first
    (with a fallback to ``DailyPrice``).

    Uses an atomic UPDATE … WHERE triggered=false guard so that concurrent
    workers (multiple Gunicorn processes, scheduler + cron overlap) can
    never dispatch the same notification twice.

    Returns list of triggered alerts info.
    """
    active_alerts = Alert.query.filter_by(is_active=True, triggered=False).all()
    triggered = []

    for alert in active_alerts:
        current_price = None

        if use_live:
            live = LiveQuote.query.filter_by(ticker_id=alert.ticker_id).first()
            if live and live.price is not None:
                current_price = live.price

        if current_price is None:
            latest = (
                DailyPrice.query.filter_by(ticker_id=alert.ticker_id)
                .order_by(DailyPrice.date.desc())
                .first()
            )
            if not latest or latest.close is None:
                continue
            current_price = latest.close

        is_triggered = False
        if alert.condition == "ABOVE" and current_price >= alert.threshold_price:
            is_triggered = True
        elif alert.condition == "BELOW" and current_price <= alert.threshold_price:
            is_triggered = True

        if is_triggered:
            # Atomic flag flip — only the first process to execute this
            # UPDATE will get rowcount == 1; every other concurrent caller
            # will see rowcount == 0 and skip the notification.
            now = datetime.now(timezone.utc)
            result = db.session.execute(
                text(
                    "UPDATE alerts "
                    "SET triggered = true, last_triggered_at = :now "
                    "WHERE id = :id AND triggered = false"
                ),
                {"id": alert.id, "now": now},
            )
            db.session.commit()

            if result.rowcount != 1:
                # Another worker already triggered this alert — skip.
                continue

            alert_data = {
                "alert_id": alert.id,
                "ticker_symbol": alert.ticker.symbol,
                "condition": alert.condition,
                "threshold": float(alert.threshold_price),
                "current_price": float(current_price),
            }
            triggered.append(alert_data)

            logger.info(
                "Alert triggered: %s %s %.2f (current: %.2f)",
                alert.ticker.symbol, alert.condition, alert.threshold_price, current_price
            )

            # Send notification only after the flag is persisted
            try:
                dispatch_alert_notifications(alert_data, alert.user)
            except Exception as exc:
                logger.error("Notification dispatch failed for alert %s: %s", alert.id, exc)

    return triggered
