"""
Telegram alert sender via python-telegram-bot (async, v20+).

All alert types are dispatched to Telegram (both URGENT and INFO).
Messages use Telegram Markdown V2 formatting for readability.
"""
import asyncio
import logging
import re
from typing import List

from alerts.alert_models import Alert, AlertType, AlertSeverity

logger = logging.getLogger(__name__)

# Telegram MarkdownV2 special characters that must be escaped
_MD2_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


def send_telegram_alerts(alerts: List[Alert], telegram_cfg) -> None:
    """
    Send alerts to all configured Telegram chat IDs.

    Parameters
    ----------
    alerts:         Alert objects to send.
    telegram_cfg:   AlertTelegramConfig dataclass.
    """
    if not alerts:
        return

    bot_token = telegram_cfg.bot_token
    chat_ids  = telegram_cfg.chat_ids or []

    if not bot_token:
        logger.error("Telegram bot_token not configured — cannot send Telegram alerts.")
        return
    if not chat_ids:
        logger.warning("No Telegram chat_ids configured — skipping Telegram delivery.")
        return

    try:
        import telegram
    except ImportError:
        logger.error("python-telegram-bot not installed. Run: pip install python-telegram-bot")
        return

    async def _send_all():
        bot = telegram.Bot(token=bot_token)
        for alert in alerts:
            text = _format_telegram(alert)
            for chat_id in chat_ids:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="MarkdownV2",
                    )
                    logger.info(
                        f"Telegram sent to {chat_id}: {alert.alert_type.value} {alert.symbol}"
                    )
                except Exception as exc:
                    logger.error(f"Telegram to {chat_id} failed: {exc}")

    # Run the async send in a fresh event loop (compatible with PythonAnywhere)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If inside an already-running loop (e.g. Flask dev server)
            import nest_asyncio  # type: ignore
            nest_asyncio.apply()
        asyncio.run(_send_all())
    except RuntimeError:
        asyncio.run(_send_all())


def _format_telegram(alert: Alert) -> str:
    """Format an alert as a Telegram MarkdownV2 message."""
    sym   = alert.symbol or "PORTFOLIO"
    meta  = alert.metadata or {}
    sev   = "🔴" if alert.severity == AlertSeverity.URGENT else "🔵"

    if alert.alert_type == AlertType.STOP_LOSS_BREACH:
        price = meta.get("current_price", 0)
        stop  = meta.get("stop_loss", 0)
        qty   = meta.get("quantity", 0)
        text = (
            f"{sev} *STOP LOSS BREACHED* — `{sym}`\n"
            f"Current price: `${price:.2f}`\n"
            f"Stop loss:     `${stop:.2f}`\n"
            f"Quantity:      `{qty}`\n"
            f"_Consider exiting position\\._"
        )

    elif alert.alert_type == AlertType.TAKE_PROFIT_REACHED:
        price  = meta.get("current_price", 0)
        target = meta.get("take_profit", 0)
        qty    = meta.get("quantity", 0)
        text = (
            f"{sev} *TAKE PROFIT REACHED* — `{sym}`\n"
            f"Current price: `${price:.2f}`\n"
            f"Take profit:   `${target:.2f}`\n"
            f"Quantity:      `{qty}`\n"
            f"_Consider taking profits\\._"
        )

    elif alert.alert_type == AlertType.HIGH_CONFIDENCE_PREDICTION:
        conf   = meta.get("confidence", 0) * 100
        action = meta.get("action", "?")
        entry  = meta.get("entry_price", 0)
        stop   = meta.get("stop_loss", 0)
        tp     = meta.get("take_profit", 0)
        strats = ", ".join(meta.get("strategies", []))
        text = (
            f"{sev} *HIGH CONFIDENCE {_esc(action)}* — `{sym}`\n"
            f"Confidence:  `{conf:.0f}%`\n"
            f"Entry:       `${entry:.2f}`\n"
            f"Stop Loss:   `${stop:.2f}`\n"
            f"Take Profit: `${tp:.2f}`\n"
            f"Strategies:  {_esc(strats)}"
        )

    elif alert.alert_type == AlertType.POSITION_PARAMS_CHANGED:
        changes = meta.get("changes", {})
        change_lines = "\n".join(f"  • {_esc(k)}: {_esc(str(v[0]))} → {_esc(str(v[1]))}"
                                  for k, v in changes.items())
        new_rec = meta.get("new_rec", {})
        text = (
            f"{sev} *TRADE PARAMS CHANGED* — `{sym}`\n"
            f"{change_lines}\n"
            f"New recommendation: `{new_rec.get('action','?')}`"
        )

    else:
        # DAILY_SUMMARY or fallback
        text = f"{sev} *{_esc(alert.subject)}*\n{_esc(alert.body_text[:600])}"

    return text


def _esc(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    for ch in _MD2_SPECIAL:
        text = text.replace(ch, f"\\{ch}")
    return text
