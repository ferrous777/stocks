from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping


@dataclass(frozen=True)
class RiskThresholds:
    min_buy_sharpe: float
    min_buy_calmar: float
    max_buy_drawdown: float
    min_hold_sharpe: float
    max_hold_drawdown: float
    short_sharpe_ceiling: float
    short_drawdown_floor: float


RISK_THRESHOLDS: Dict[str, RiskThresholds] = {
    "conservative": RiskThresholds(
        min_buy_sharpe=2.25,
        min_buy_calmar=2.25,
        max_buy_drawdown=0.12,
        min_hold_sharpe=1.0,
        max_hold_drawdown=0.15,
        short_sharpe_ceiling=-0.25,
        short_drawdown_floor=0.20,
    ),
    "moderate": RiskThresholds(
        min_buy_sharpe=2.0,
        min_buy_calmar=2.0,
        max_buy_drawdown=0.15,
        min_hold_sharpe=0.75,
        max_hold_drawdown=0.20,
        short_sharpe_ceiling=-0.4,
        short_drawdown_floor=0.25,
    ),
    "aggressive": RiskThresholds(
        min_buy_sharpe=1.6,
        min_buy_calmar=1.5,
        max_buy_drawdown=0.25,
        min_hold_sharpe=0.5,
        max_hold_drawdown=0.30,
        short_sharpe_ceiling=-0.7,
        short_drawdown_floor=0.30,
    ),
}


def evaluate_recommendation(metrics: Mapping[str, float], risk_profile: str = "moderate") -> Dict[str, str]:
    """Return deterministic recommendation label based on risk-adjusted metrics."""
    if risk_profile not in RISK_THRESHOLDS:
        raise ValueError(f"Unsupported risk profile '{risk_profile}'")

    thresholds = RISK_THRESHOLDS[risk_profile]
    sharpe = float(metrics.get("sharpe_ratio", 0.0))
    calmar = float(metrics.get("calmar_ratio", 0.0))
    drawdown = abs(float(metrics.get("max_drawdown", 0.0)))
    total_return = float(metrics.get("total_return", 0.0))

    if (
        sharpe >= thresholds.min_buy_sharpe
        and calmar >= thresholds.min_buy_calmar
        and drawdown <= thresholds.max_buy_drawdown
        and total_return > 0
    ):
        return {"action": "buy", "reason": "Strong risk-adjusted performance with controlled drawdown."}

    if (
        sharpe <= thresholds.short_sharpe_ceiling
        and drawdown >= thresholds.short_drawdown_floor
        and total_return < 0
    ):
        return {"action": "short", "reason": "Persistently weak risk-adjusted performance and elevated drawdown."}

    if sharpe >= thresholds.min_hold_sharpe and drawdown <= thresholds.max_hold_drawdown:
        return {"action": "hold", "reason": "Mixed but acceptable profile for current risk tolerance."}

    return {"action": "avoid", "reason": "Does not meet risk-adjusted thresholds for allocation."}
