"""
Alert engine — orchestrates all rule evaluations and dispatches alerts.

Call `AlertEngine.run(...)` once per scheduler cycle after the daily pipeline
completes. It:
  1. Evaluates position-level rules via position_monitor
  2. Checks new predictions for high-confidence BUY/SELL signals on symbols
     not already held
  3. Builds the daily summary alert
  4. Dispatches each alert to all configured channels
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from alerts.alert_models import Alert, AlertType, AlertSeverity
from alerts.position_monitor import evaluate_positions
from alerts.email_sender import send_email_alerts
from alerts.sms_sender import send_sms_alerts
from alerts.telegram_sender import send_telegram_alerts

logger = logging.getLogger(__name__)


class AlertEngine:
    """
    Stateless alert evaluation + dispatch.

    Parameters
    ----------
    db:             TimeSeriesDB instance
    config:         SystemConfig (from config_manager.get_config())
    """

    def __init__(self, db, config):
        self.db = db
        self.config = config
        self.alerts_cfg = config.alerts

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------
    def run(self, new_predictions: List[Dict] = None,
            new_transactions: List[Dict] = None,
            include_daily_summary: bool = False) -> List[Alert]:
        """
        Evaluate all alert rules and dispatch to configured channels.

        Parameters
        ----------
        new_predictions:
            List of fresh recommendation dicts produced by today's scheduler run.
            Each dict must have at minimum: symbol, action, confidence,
            entry_price, stop_loss, take_profit, supporting_strategies.
        new_transactions:
            List of newly-seen investment transactions from Plaid sync.
        include_daily_summary:
            If True, append a daily summary alert.

        Returns
        -------
        All Alert objects that were generated (fired + dispatched).
        """
        if not self.alerts_cfg.enabled:
            logger.info("Alerts disabled in config — skipping alert engine run.")
            return []

        alerts: List[Alert] = []

        # ── 1. Position-level rules (stop-loss, take-profit, drift) ──────
        try:
            position_alerts = evaluate_positions(self.db, self.alerts_cfg)
            alerts.extend(position_alerts)
        except Exception as exc:
            logger.error(f"Position monitor error: {exc}")

        # ── 2. High-confidence new predictions ───────────────────────────
        if new_predictions:
            alerts.extend(self._evaluate_new_predictions(new_predictions))

        # ── 3. Daily summary ─────────────────────────────────────────────
        if include_daily_summary:
            summary = self._build_daily_summary()
            if summary:
                alerts.append(summary)

        if not alerts:
            logger.info("No alerts triggered this cycle.")
            return []

        logger.info(f"Dispatching {len(alerts)} alert(s).")
        self._dispatch(alerts)
        return alerts

    # ------------------------------------------------------------------
    # Rule: new high-confidence predictions
    # ------------------------------------------------------------------
    def _evaluate_new_predictions(self, predictions: List[Dict]) -> List[Alert]:
        threshold = getattr(self.alerts_cfg, "prediction_confidence_threshold", 0.80)
        # Build set of currently-held symbols so we don't alert redundantly
        held_symbols = {p["symbol"] for p in self.db.get_portfolio_positions()}

        fired: List[Alert] = []
        for pred in predictions:
            confidence = pred.get("confidence", 0.0)
            symbol = pred.get("symbol", "")
            action = pred.get("action", "")

            if confidence < threshold:
                continue
            if action not in ("BUY", "SELL", "SHORT"):
                continue  # HOLD / EXIT don't generate buy-signal alerts
            if symbol in held_symbols:
                continue  # already have a position — drift checker handles this

            fired.append(Alert.high_confidence(
                symbol=symbol,
                action=action,
                confidence=confidence,
                entry_price=pred.get("entry_price", 0.0),
                stop_loss=pred.get("stop_loss", 0.0),
                take_profit=pred.get("take_profit", 0.0),
                strategy_names=pred.get("supporting_strategies", []),
                details=pred.get("details", ""),
            ))
        return fired

    # ------------------------------------------------------------------
    # Rule: daily summary
    # ------------------------------------------------------------------
    def _build_daily_summary(self) -> Optional[Alert]:
        positions = self.db.get_portfolio_positions()
        if not positions:
            return None

        # Enrich each position with the current model recommendation
        enriched = []
        for pos in positions:
            symbol = pos["symbol"]
            current_rec = self._get_latest_prediction(symbol)
            pos["current_rec_action"] = current_rec.get("action", "N/A") if current_rec else "N/A"
            pos["current_rec_confidence"] = current_rec.get("confidence") if current_rec else None
            enriched.append(pos)

        return Alert.daily_summary(enriched, date=datetime.now().strftime("%Y-%m-%d"))

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def _dispatch(self, alerts: List[Alert]):
        cfg = self.alerts_cfg

        if cfg.email and cfg.email.enabled:
            try:
                send_email_alerts(alerts, cfg.email)
            except Exception as exc:
                logger.error(f"Email dispatch failed: {exc}")

        if cfg.sms and cfg.sms.enabled:
            try:
                urgent = [a for a in alerts if a.severity == AlertSeverity.URGENT]
                if urgent:
                    send_sms_alerts(urgent, cfg.sms)
            except Exception as exc:
                logger.error(f"SMS dispatch failed: {exc}")

        if cfg.telegram and cfg.telegram.enabled:
            try:
                send_telegram_alerts(alerts, cfg.telegram)
            except Exception as exc:
                logger.error(f"Telegram dispatch failed: {exc}")

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------
    def _get_latest_prediction(self, symbol: str) -> Optional[Dict]:
        import json
        try:
            with self.db.get_connection() as conn:
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
        except Exception:
            pass
        return None
