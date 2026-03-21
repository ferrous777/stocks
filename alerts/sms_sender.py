"""
SMS alert sender via Twilio REST API.

Only URGENT alerts are dispatched via SMS to avoid message noise.
Each alert becomes a short, actionable text message.
"""
import logging
from typing import List

from alerts.alert_models import Alert, AlertType

logger = logging.getLogger(__name__)

# Max SMS body length (Twilio supports up to 1600 chars, but we keep it short)
_MAX_LENGTH = 320


def send_sms_alerts(alerts: List[Alert], sms_cfg) -> None:
    """
    Send URGENT alerts as SMS via Twilio.

    Parameters
    ----------
    alerts:   URGENT Alert objects to send (INFO alerts should be filtered before calling).
    sms_cfg:  AlertSmsConfig dataclass.
    """
    if not alerts:
        return

    account_sid = sms_cfg.twilio_account_sid
    auth_token  = sms_cfg.twilio_auth_token
    from_number = sms_cfg.from_number
    recipients  = sms_cfg.recipients or []

    if not account_sid or not auth_token or not from_number:
        logger.error("Twilio credentials not configured — cannot send SMS.")
        return
    if not recipients:
        logger.warning("No SMS recipients configured — skipping SMS delivery.")
        return

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
    except ImportError:
        logger.error("twilio package not installed. Run: pip install twilio")
        return

    for alert in alerts:
        body = _format_sms(alert)
        for to_number in recipients:
            try:
                message = client.messages.create(
                    body=body,
                    from_=from_number,
                    to=to_number,
                )
                logger.info(
                    f"SMS sent to {to_number}: sid={message.sid} "
                    f"alert={alert.alert_type.value} symbol={alert.symbol}"
                )
            except Exception as exc:
                logger.error(f"SMS to {to_number} failed: {exc}")


def _format_sms(alert: Alert) -> str:
    """Produce a concise, human-readable SMS body."""
    sym = alert.symbol or "PORTFOLIO"
    meta = alert.metadata or {}

    if alert.alert_type == AlertType.STOP_LOSS_BREACH:
        price = meta.get("current_price", 0)
        stop  = meta.get("stop_loss", 0)
        return (
            f"[STOCK ALERT] {sym} STOP LOSS BREACHED. "
            f"Price=${price:.2f} < Stop=${stop:.2f}. "
            f"Review position immediately."
        )[:_MAX_LENGTH]

    if alert.alert_type == AlertType.TAKE_PROFIT_REACHED:
        price  = meta.get("current_price", 0)
        target = meta.get("take_profit", 0)
        return (
            f"[STOCK ALERT] {sym} TAKE PROFIT REACHED. "
            f"Price=${price:.2f} >= Target=${target:.2f}. "
            f"Consider taking profits."
        )[:_MAX_LENGTH]

    # Generic URGENT fallback
    return f"[STOCK ALERT] {sym}: {alert.subject}"[:_MAX_LENGTH]
