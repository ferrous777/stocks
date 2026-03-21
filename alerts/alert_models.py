"""
Alert data models.

AlertType  -- enum of the five alert categories
AlertSeverity -- URGENT fires SMS immediately; INFO batches into digest
Alert      -- the universal alert payload passed to all senders
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
from datetime import datetime


class AlertType(Enum):
    HIGH_CONFIDENCE_PREDICTION = "HIGH_CONFIDENCE_PREDICTION"
    STOP_LOSS_BREACH           = "STOP_LOSS_BREACH"
    TAKE_PROFIT_REACHED        = "TAKE_PROFIT_REACHED"
    POSITION_PARAMS_CHANGED    = "POSITION_PARAMS_CHANGED"
    DAILY_SUMMARY              = "DAILY_SUMMARY"


class AlertSeverity(Enum):
    URGENT = "URGENT"   # SMS + Telegram + Email immediately
    INFO   = "INFO"     # Email digest + Telegram; SMS skipped


@dataclass
class Alert:
    alert_type: AlertType
    severity: AlertSeverity
    symbol: Optional[str]
    subject: str
    body_text: str
    body_html: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # ── Convenience constructors ──────────────────────────────────────────

    @classmethod
    def high_confidence(cls, symbol: str, action: str, confidence: float,
                        entry_price: float, stop_loss: float, take_profit: float,
                        strategy_names: list, details: str = "") -> "Alert":
        pct = f"{confidence * 100:.0f}%"
        subject = f"[{pct}] {action} signal — {symbol}"
        body_text = (
            f"NEW HIGH-CONFIDENCE {action} SIGNAL\n"
            f"Symbol    : {symbol}\n"
            f"Confidence: {pct}\n"
            f"Entry     : ${entry_price:.2f}\n"
            f"Stop Loss : ${stop_loss:.2f}\n"
            f"Take Profit: ${take_profit:.2f}\n"
            f"Strategies: {', '.join(strategy_names)}\n"
            f"{details}"
        )
        body_html = _html_table(subject, {
            "Symbol": symbol, "Signal": action, "Confidence": pct,
            "Entry": f"${entry_price:.2f}", "Stop Loss": f"${stop_loss:.2f}",
            "Take Profit": f"${take_profit:.2f}",
            "Strategies": ", ".join(strategy_names),
        })
        return cls(
            alert_type=AlertType.HIGH_CONFIDENCE_PREDICTION,
            severity=AlertSeverity.INFO,
            symbol=symbol,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            metadata={"confidence": confidence, "entry_price": entry_price,
                       "stop_loss": stop_loss, "take_profit": take_profit,
                       "action": action, "strategies": strategy_names},
        )

    @classmethod
    def stop_loss_breach(cls, symbol: str, current_price: float,
                          stop_loss: float, quantity: float) -> "Alert":
        subject = f"[URGENT] STOP LOSS BREACHED — {symbol}"
        body_text = (
            f"⚠️  STOP LOSS BREACHED\n"
            f"Symbol       : {symbol}\n"
            f"Current Price: ${current_price:.2f}\n"
            f"Stop Loss    : ${stop_loss:.2f}\n"
            f"Quantity     : {quantity}\n"
            f"Action needed: Consider exiting position to limit losses."
        )
        body_html = _html_table(subject, {
            "Symbol": symbol, "Current Price": f"${current_price:.2f}",
            "Stop Loss": f"${stop_loss:.2f}", "Quantity": str(quantity),
        }, warning=True)
        return cls(
            alert_type=AlertType.STOP_LOSS_BREACH,
            severity=AlertSeverity.URGENT,
            symbol=symbol,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            metadata={"current_price": current_price, "stop_loss": stop_loss,
                       "quantity": quantity},
        )

    @classmethod
    def take_profit_reached(cls, symbol: str, current_price: float,
                             take_profit: float, quantity: float) -> "Alert":
        subject = f"[URGENT] TAKE PROFIT REACHED — {symbol}"
        body_text = (
            f"🎯 TAKE PROFIT REACHED\n"
            f"Symbol       : {symbol}\n"
            f"Current Price: ${current_price:.2f}\n"
            f"Take Profit  : ${take_profit:.2f}\n"
            f"Quantity     : {quantity}\n"
            f"Action needed: Consider taking profits."
        )
        body_html = _html_table(subject, {
            "Symbol": symbol, "Current Price": f"${current_price:.2f}",
            "Take Profit": f"${take_profit:.2f}", "Quantity": str(quantity),
        })
        return cls(
            alert_type=AlertType.TAKE_PROFIT_REACHED,
            severity=AlertSeverity.URGENT,
            symbol=symbol,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            metadata={"current_price": current_price, "take_profit": take_profit,
                       "quantity": quantity},
        )

    @classmethod
    def params_changed(cls, symbol: str, changes: dict, new_rec: dict) -> "Alert":
        """
        Alert when model parameters for a held position have meaningfully shifted.
        `changes` is a dict of {field: (old_value, new_value)} for changed fields.
        """
        change_lines = "\n".join(
            f"  {k}: {v[0]} → {v[1]}" for k, v in changes.items()
        )
        subject = f"[ACTION] Trade parameters changed — {symbol}"
        body_text = (
            f"TRADE PARAMETERS UPDATED\n"
            f"Symbol: {symbol}\n\n"
            f"Changes detected:\n{change_lines}\n\n"
            f"Updated recommendation:\n"
            f"  Action    : {new_rec.get('action', 'N/A')}\n"
            f"  Entry     : ${new_rec.get('entry_price', 0):.2f}\n"
            f"  Stop Loss : ${new_rec.get('stop_loss', 0):.2f}\n"
            f"  Take Profit: ${new_rec.get('take_profit', 0):.2f}\n"
            f"  Confidence: {new_rec.get('confidence', 0) * 100:.0f}%"
        )
        rows = {k: f"{v[0]} → {v[1]}" for k, v in changes.items()}
        rows["New Action"] = new_rec.get("action", "N/A")
        rows["New Stop Loss"] = f"${new_rec.get('stop_loss', 0):.2f}"
        rows["New Take Profit"] = f"${new_rec.get('take_profit', 0):.2f}"
        body_html = _html_table(subject, rows)
        return cls(
            alert_type=AlertType.POSITION_PARAMS_CHANGED,
            severity=AlertSeverity.INFO,
            symbol=symbol,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            metadata={"changes": changes, "new_rec": new_rec},
        )

    @classmethod
    def daily_summary(cls, positions: list, date: str) -> "Alert":
        lines = [f"DAILY PORTFOLIO SUMMARY — {date}", ""]
        for p in positions:
            sym = p.get("symbol", "?")
            qty = p.get("quantity", 0)
            price = p.get("institution_price") or 0
            pnl_pct = (p.get("unrealized_pnl_pct") or 0) * 100
            action = p.get("current_rec_action", "HOLD")
            confidence = (p.get("current_rec_confidence") or 0) * 100
            lines.append(
                f"  {sym:8s} qty={qty:<6.2f} price=${price:<8.2f} "
                f"P&L={pnl_pct:+.1f}%  model={action} ({confidence:.0f}%)"
            )
        body_text = "\n".join(lines)
        body_html = _summary_html(positions, date)
        return cls(
            alert_type=AlertType.DAILY_SUMMARY,
            severity=AlertSeverity.INFO,
            symbol=None,
            subject=f"Daily Portfolio Summary — {date}",
            body_text=body_text,
            body_html=body_html,
            metadata={"positions": positions, "date": date},
        )


# ──────────────────────────────────────────────────────────────────────────────
# HTML helpers
# ──────────────────────────────────────────────────────────────────────────────

def _html_table(title: str, rows: dict, warning: bool = False) -> str:
    color = "#c0392b" if warning else "#2980b9"
    cells = "".join(
        f"<tr><td style='padding:4px 8px;font-weight:bold'>{k}</td>"
        f"<td style='padding:4px 8px'>{v}</td></tr>"
        for k, v in rows.items()
    )
    return (
        f"<html><body>"
        f"<h2 style='color:{color}'>{title}</h2>"
        f"<table border='0' cellspacing='2' cellpadding='4'>{cells}</table>"
        f"</body></html>"
    )


def _summary_html(positions: list, date: str) -> str:
    header = "<tr><th>Symbol</th><th>Qty</th><th>Price</th><th>P&L %</th><th>Model</th><th>Confidence</th></tr>"
    rows = ""
    for p in positions:
        pnl_pct = (p.get("unrealized_pnl_pct") or 0) * 100
        color = "green" if pnl_pct >= 0 else "red"
        rows += (
            f"<tr>"
            f"<td>{p.get('symbol','?')}</td>"
            f"<td>{p.get('quantity',0):.2f}</td>"
            f"<td>${p.get('institution_price') or 0:.2f}</td>"
            f"<td style='color:{color}'>{pnl_pct:+.1f}%</td>"
            f"<td>{p.get('current_rec_action','HOLD')}</td>"
            f"<td>{(p.get('current_rec_confidence') or 0)*100:.0f}%</td>"
            f"</tr>"
        )
    return (
        f"<html><body><h2>Daily Portfolio Summary — {date}</h2>"
        f"<table border='1' cellspacing='0' cellpadding='6'>{header}{rows}</table>"
        f"</body></html>"
    )
