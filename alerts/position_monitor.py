"""
Position monitor — compares held portfolio positions against the current
recommendations from the prediction engine and fires alerts when:

  1. Current price has breached the stop-loss level in the entry snapshot
  2. Current price has reached/exceeded the take-profit level
  3. Model parameters have drifted significantly from the entry snapshot:
       - stop_loss moved > parameter_change_pct (default 5 %)
       - take_profit moved > parameter_change_pct
       - action flipped to EXIT
       - confidence dropped > confidence_drop_threshold (default 15 pp)
"""
import json
import logging
from typing import List, Dict, Any, Optional

from alerts.alert_models import Alert

logger = logging.getLogger(__name__)


def evaluate_positions(db, alerts_config=None) -> List[Alert]:
    """
    Evaluate all open portfolio positions and return a list of triggered Alerts.

    Parameters
    ----------
    db:             TimeSeriesDB instance
    alerts_config:  AlertConfig dataclass (from config_manager). If None, uses defaults.
    """
    # Threshold defaults
    param_change_pct = 0.05
    confidence_drop  = 0.15

    if alerts_config is not None:
        param_change_pct = getattr(alerts_config, "parameter_change_pct", param_change_pct)
        confidence_drop  = getattr(alerts_config, "confidence_drop_threshold", confidence_drop)

    positions = db.get_portfolio_positions()
    if not positions:
        logger.info("No portfolio positions to evaluate.")
        return []

    triggered: List[Alert] = []

    for pos in positions:
        symbol   = pos.get("symbol")
        quantity = pos.get("quantity") or 0
        entry_snap = pos.get("entry_rec_snapshot")  # dict or None

        # Current market price from the position (as last synced by Plaid)
        current_price = pos.get("institution_price")
        if not current_price:
            logger.debug(f"No current price for {symbol}, skipping position monitor check.")
            continue

        # ── STOP-LOSS BREACH ─────────────────────────────────────────────
        if entry_snap:
            orig_stop_loss = _safe_float(entry_snap.get("stop_loss"))
            if orig_stop_loss and current_price < orig_stop_loss:
                triggered.append(
                    Alert.stop_loss_breach(symbol, current_price, orig_stop_loss, quantity)
                )

        # ── TAKE-PROFIT REACHED ──────────────────────────────────────────
        if entry_snap:
            orig_take_profit = _safe_float(entry_snap.get("take_profit"))
            if orig_take_profit and current_price >= orig_take_profit:
                triggered.append(
                    Alert.take_profit_reached(symbol, current_price, orig_take_profit, quantity)
                )

        # ── PARAMETER DRIFT ──────────────────────────────────────────────
        if entry_snap:
            current_rec = _get_latest_prediction(db, symbol)
            if current_rec:
                drift_alerts = _check_parameter_drift(
                    symbol, entry_snap, current_rec,
                    param_change_pct=param_change_pct,
                    confidence_drop=confidence_drop,
                )
                triggered.extend(drift_alerts)

    logger.info(f"Position monitor: {len(triggered)} alert(s) triggered across {len(positions)} positions.")
    return triggered


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _check_parameter_drift(symbol: str, entry_snap: dict, current_rec: dict,
                             param_change_pct: float, confidence_drop: float) -> List[Alert]:
    """Compare the entry snapshot to the current recommendation for drift."""
    changes: Dict[str, tuple] = {}

    # Stop-loss drift
    orig_sl = _safe_float(entry_snap.get("stop_loss"))
    new_sl  = _safe_float(current_rec.get("stop_loss"))
    if orig_sl and new_sl and orig_sl > 0:
        if abs(new_sl - orig_sl) / orig_sl > param_change_pct:
            changes["stop_loss"] = (f"${orig_sl:.2f}", f"${new_sl:.2f}")

    # Take-profit drift
    orig_tp = _safe_float(entry_snap.get("take_profit"))
    new_tp  = _safe_float(current_rec.get("take_profit"))
    if orig_tp and new_tp and orig_tp > 0:
        if abs(new_tp - orig_tp) / orig_tp > param_change_pct:
            changes["take_profit"] = (f"${orig_tp:.2f}", f"${new_tp:.2f}")

    # Action flipped to EXIT
    orig_action = (entry_snap.get("action") or "").upper()
    new_action  = (current_rec.get("action") or "").upper()
    if new_action == "EXIT" and orig_action != "EXIT":
        changes["action"] = (orig_action, "EXIT")

    # Confidence drop
    orig_conf = _safe_float(entry_snap.get("confidence"))
    new_conf  = _safe_float(current_rec.get("confidence"))
    if orig_conf is not None and new_conf is not None:
        if (orig_conf - new_conf) > confidence_drop:
            changes["confidence"] = (
                f"{orig_conf * 100:.0f}%", f"{new_conf * 100:.0f}%"
            )

    if changes:
        return [Alert.params_changed(symbol, changes, current_rec)]
    return []


def _get_latest_prediction(db, symbol: str) -> Optional[dict]:
    """Retrieve the most recent projection/recommendation for a symbol."""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT data FROM projections
                WHERE symbol = ?
                ORDER BY projection_date DESC
                LIMIT 1
            """, (symbol,))
            row = cursor.fetchone()
            if row:
                return json.loads(row["data"])
    except Exception as e:
        logger.debug(f"Could not load latest prediction for {symbol}: {e}")
    return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
