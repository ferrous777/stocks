"""
Email alert sender (SMTP / TLS).

Behaviour
---------
- URGENT alerts are sent immediately in individual emails.
- INFO alerts are batched into a single digest email.
- All emails are sent as multipart (text/plain + text/html).
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

from alerts.alert_models import Alert, AlertSeverity

logger = logging.getLogger(__name__)


def send_email_alerts(alerts: List[Alert], email_cfg) -> None:
    """
    Dispatch alerts via SMTP.

    Parameters
    ----------
    alerts:     List of Alert objects to send.
    email_cfg:  AlertEmailConfig dataclass.
    """
    if not alerts:
        return

    urgent = [a for a in alerts if a.severity == AlertSeverity.URGENT]
    info   = [a for a in alerts if a.severity != AlertSeverity.URGENT]

    # Send urgent alerts one by one for immediate delivery
    if email_cfg.urgent_immediate:
        for alert in urgent:
            _send_single(alert, email_cfg)
    else:
        info = alerts  # batch everything

    # Batch INFO alerts into a single digest
    if info:
        _send_digest(info, email_cfg)


def _send_single(alert: Alert, cfg) -> None:
    subject = alert.subject
    _deliver(subject, alert.body_text, alert.body_html, cfg)


def _send_digest(alerts: List[Alert], cfg) -> None:
    subject = f"Stock Analyzer — Daily Alert Digest ({len(alerts)} alert(s))"
    # Combine plain text
    plain = "\n\n" + ("=" * 60) + "\n\n".join(
        f"[{a.alert_type.value}]\n{a.body_text}" for a in alerts
    )
    # Combine HTML
    html_parts = "".join(
        f"<hr/><h3>{a.subject}</h3>{a.body_html}" for a in alerts
    )
    html = f"<html><body>{html_parts}</body></html>"
    _deliver(subject, plain, html, cfg)


def _deliver(subject: str, plain: str, html: str, cfg) -> None:
    from_addr = cfg.from_address or cfg.smtp_user
    recipients = cfg.recipients or []
    if not recipients:
        logger.warning("No email recipients configured — skipping email delivery.")
        return
    if not cfg.smtp_user or not cfg.smtp_password:
        logger.error("SMTP credentials not configured — cannot send email.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(plain, "plain"))
    if html:
        msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg.smtp_user, cfg.smtp_password)
            server.sendmail(from_addr, recipients, msg.as_string())
        logger.info(f"Email sent: {subject!r} → {recipients}")
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed. Check ALERT_SMTP_USER / ALERT_SMTP_PASSWORD.")
    except Exception as exc:
        logger.error(f"Failed to send email ({subject!r}): {exc}")
