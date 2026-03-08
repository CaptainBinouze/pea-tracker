"""
Alert evaluation logic.
"""

import logging
from datetime import datetime, timezone

from app.extensions import db
from app.models import Alert, DailyPrice, LiveQuote
from app.notifications.dispatcher import dispatch_alert_notifications

logger = logging.getLogger(__name__)


def evaluate_alerts(*, use_live: bool = False) -> list[dict]:
    """
    Check all active alerts against latest prices.

    When *use_live* is ``True`` the price is read from ``LiveQuote`` first
    (with a fallback to ``DailyPrice``).

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
            alert.triggered = True
            alert.last_triggered_at = datetime.now(timezone.utc)

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

            # Send notifications to the user
            try:
                dispatch_alert_notifications(alert_data, alert.user)
            except Exception as exc:
                logger.error("Notification dispatch failed for alert %s: %s", alert.id, exc)

    db.session.commit()
    return triggered
