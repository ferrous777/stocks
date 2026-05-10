"""Recommendation payload contract: normalization + validation.

This keeps recommendation data deterministic and backward-compatible while
allowing flexible key/value metrics under `recommendations.metrics`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

ALLOWED_ACTIONS = {"BUY", "SELL", "HOLD"}
ALLOWED_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "N/A"}


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp01(value: Any) -> float:
    numeric = _to_float(value)
    if numeric is None:
        return 0.0
    if numeric < 0:
        return 0.0
    if numeric > 1:
        return 1.0
    return numeric


def _normalize_action(value: Any) -> str:
    action = str(value or "HOLD").upper().strip()
    if action in ALLOWED_ACTIONS:
        return action
    return "HOLD"


def _normalize_signals(signals: Any) -> List[Dict[str, Any]]:
    if not isinstance(signals, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for raw in signals:
        if not isinstance(raw, dict):
            continue
        normalized.append(
            {
                "strategy": str(raw.get("strategy") or "unknown"),
                "signal": _normalize_action(raw.get("signal")),
                "confidence": _clamp01(raw.get("confidence")),
                "details": str(raw.get("details") or ""),
                "metrics": raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {},
            }
        )
    return normalized


def _compute_trade_fields(action: str, entry: Optional[float], stop: Optional[float], target: Optional[float]) -> Dict[str, Any]:
    if entry is None or entry <= 0 or action == "HOLD":
        return {
            "risk_reward": None,
            "risk_pct": None,
            "reward_pct": None,
            "risk_level": "N/A",
        }

    if action == "BUY":
        risk = (entry - stop) if stop is not None else None
        reward = (target - entry) if target is not None else None
    else:
        risk = (stop - entry) if stop is not None else None
        reward = (entry - target) if target is not None else None

    if risk is None or reward is None or risk <= 0:
        return {
            "risk_reward": None,
            "risk_pct": None,
            "reward_pct": None,
            "risk_level": "N/A",
        }

    risk_pct = (risk / entry) * 100
    reward_pct = (reward / entry) * 100
    ratio = reward / risk if risk > 0 else None

    if risk_pct <= 3:
        risk_level = "LOW"
    elif risk_pct <= 7:
        risk_level = "MEDIUM"
    else:
        risk_level = "HIGH"

    return {
        "risk_reward": ratio,
        "risk_pct": risk_pct,
        "reward_pct": reward_pct,
        "risk_level": risk_level,
    }


def normalize_recommendation_payload(
    payload: Dict[str, Any],
    symbol: str,
    analysis_date: str,
    fallback_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Normalize recommendation payload to a stable contract.

    Required top-level shape:
      {"symbol": str, "analysis_date": str, "recommendations": { ... }}
    """
    source = payload if isinstance(payload, dict) else {}
    raw_rec = source.get("recommendations") if isinstance(source.get("recommendations"), dict) else source
    if not isinstance(raw_rec, dict):
        raw_rec = {}

    action = _normalize_action(raw_rec.get("action"))
    confidence = _clamp01(raw_rec.get("confidence"))

    entry_price = _to_float(raw_rec.get("entry_price"))
    if entry_price is None:
        entry_price = _to_float(raw_rec.get("current_price"))
    if entry_price is None:
        entry_price = _to_float(fallback_price)

    stop_loss = _to_float(raw_rec.get("stop_loss"))
    take_profit = _to_float(raw_rec.get("take_profit"))

    if action == "HOLD" and entry_price is not None:
        stop_loss = entry_price
        take_profit = entry_price

    signals = _normalize_signals(raw_rec.get("signals"))
    if signals and confidence == 0.0:
        confidence = sum(signal["confidence"] for signal in signals) / len(signals)

    trade_fields = _compute_trade_fields(action, entry_price, stop_loss, take_profit)

    benchmark = raw_rec.get("benchmark") if isinstance(raw_rec.get("benchmark"), dict) else {}
    spy_return_pct = _to_float(benchmark.get("spy_return_pct"))

    normalized = {
        "symbol": str(source.get("symbol") or symbol),
        "analysis_date": str(source.get("analysis_date") or analysis_date),
        "recommendations": {
            "action": action,
            "confidence": confidence,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_reward": trade_fields["risk_reward"],
            "risk_level": trade_fields["risk_level"],
            "risk_pct": trade_fields["risk_pct"],
            "reward_pct": trade_fields["reward_pct"],
            "position_size": raw_rec.get("position_size"),
            "signals": signals,
            "details": str(raw_rec.get("details") or raw_rec.get("reasoning") or ""),
            "time_estimate": raw_rec.get("time_estimate") if isinstance(raw_rec.get("time_estimate"), dict) else None,
            "benchmark": {
                "spy_return_pct": spy_return_pct,
                "period_days": int(benchmark.get("period_days")) if str(benchmark.get("period_days", "")).isdigit() else None,
            },
            # Flexible key-value extension area.
            "metrics": raw_rec.get("metrics") if isinstance(raw_rec.get("metrics"), dict) else {},
        },
    }

    return normalized


def validate_recommendation_payload(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    if not isinstance(payload, dict):
        return False, ["payload must be an object"]

    if not isinstance(payload.get("symbol"), str) or not payload.get("symbol"):
        errors.append("symbol must be a non-empty string")

    if not isinstance(payload.get("analysis_date"), str) or not payload.get("analysis_date"):
        errors.append("analysis_date must be a non-empty string")

    rec = payload.get("recommendations")
    if not isinstance(rec, dict):
        errors.append("recommendations must be an object")
        return False, errors

    if rec.get("action") not in ALLOWED_ACTIONS:
        errors.append("recommendations.action must be BUY, SELL, or HOLD")

    confidence = _to_float(rec.get("confidence"))
    if confidence is None or confidence < 0 or confidence > 1:
        errors.append("recommendations.confidence must be between 0 and 1")

    for numeric_key in ["entry_price", "stop_loss", "take_profit"]:
        value = rec.get(numeric_key)
        if value is not None and _to_float(value) is None:
            errors.append(f"recommendations.{numeric_key} must be numeric or null")

    if rec.get("risk_level") not in ALLOWED_RISK_LEVELS:
        errors.append("recommendations.risk_level must be LOW, MEDIUM, HIGH, or N/A")

    if not isinstance(rec.get("signals"), list):
        errors.append("recommendations.signals must be an array")

    benchmark = rec.get("benchmark")
    if benchmark is not None and not isinstance(benchmark, dict):
        errors.append("recommendations.benchmark must be an object")

    metrics = rec.get("metrics")
    if metrics is not None and not isinstance(metrics, dict):
        errors.append("recommendations.metrics must be an object")

    return len(errors) == 0, errors
