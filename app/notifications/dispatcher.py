"""
Notification dispatcher — routes triggered alerts to the user's enabled channels.
"""

import logging

from app.models import NotificationPreference
from app.notifications.channels import SlackChannel

logger = logging.getLogger(__name__)


def dispatch_alert_notifications(alert_data: dict, user) -> None:
    """
    Send notifications for a triggered alert through all channels
    the user has enabled.

    Parameters
    ----------
    alert_data : dict
        Keys: alert_id, ticker_symbol, condition, threshold, current_price
    user : User
        The user who owns the alert.
    """
    pref = NotificationPreference.query.filter_by(user_id=user.id).first()

    if pref is None:
        logger.debug("No notification preferences for user %s — skipping", user.id)
        return

    # --- Slack ---
    if pref.slack_enabled and pref.slack_webhook_url:
        try:
            SlackChannel.send(pref.slack_webhook_url, alert_data)
        except Exception as exc:
            logger.error(
                "Slack dispatch failed for user %s: %s", user.id, exc
            )
