"""
Notification channels — each channel sends an alert message via a specific service.
"""

import logging

import requests

logger = logging.getLogger(__name__)


class SlackChannel:
    """Send alert notifications via Slack Incoming Webhook."""

    @staticmethod
    def send(webhook_url: str, alert_data: dict) -> bool:
        """
        Post a formatted alert message to a Slack channel.

        Parameters
        ----------
        webhook_url : str
            The Slack Incoming Webhook URL.
        alert_data : dict
            Keys: ticker_symbol, condition, threshold, current_price

        Returns
        -------
        bool
            True if the message was sent successfully, False otherwise.
        """
        ticker = alert_data["ticker_symbol"]
        condition = alert_data["condition"]
        threshold = alert_data["threshold"]
        current_price = alert_data["current_price"]

        condition_fr = "au-dessus de" if condition == "ABOVE" else "en-dessous de"
        emoji = "\U0001f4c8" if condition == "ABOVE" else "\U0001f4c9"

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emoji} Alerte PEA Tracker",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Ticker :*\n{ticker}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Condition :*\n{condition_fr} {threshold:.2f} \u20ac",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Prix actuel :*\n{current_price:.2f} \u20ac",
                        },
                    ],
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "PEA Tracker \u2014 Notification automatique",
                        }
                    ],
                },
            ],
            "text": (
                f"{emoji} {ticker} est {condition_fr} {threshold:.2f} \u20ac "
                f"(prix actuel : {current_price:.2f} \u20ac)"
            ),
        }

        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("Slack notification sent for %s", ticker)
                return True
            else:
                logger.error(
                    "Slack notification failed for %s: HTTP %s — %s",
                    ticker,
                    resp.status_code,
                    resp.text,
                )
                return False
        except requests.RequestException as exc:
            logger.error("Slack notification error for %s: %s", ticker, exc)
            return False
