from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Mapping, Optional


@dataclass(frozen=True)
class RiskThresholds:
    min_buy_sharpe: float
    min_buy_calmar: float
    max_buy_drawdown: float
    min_hold_sharpe: float
    max_hold_drawdown: float
    short_sharpe_ceiling: float
    short_drawdown_floor: float


@dataclass(frozen=True)
class RiskThresholdOverride:
    """Optional threshold values layered over a base risk profile."""

    min_buy_sharpe: Optional[float] = None
    min_buy_calmar: Optional[float] = None
    max_buy_drawdown: Optional[float] = None
    min_hold_sharpe: Optional[float] = None
    max_hold_drawdown: Optional[float] = None
    short_sharpe_ceiling: Optional[float] = None
    short_drawdown_floor: Optional[float] = None

    def apply(self, base: RiskThresholds) -> RiskThresholds:
        """Merge this override into a base threshold profile."""
        return replace(
            base,
            min_buy_sharpe=self.min_buy_sharpe if self.min_buy_sharpe is not None else base.min_buy_sharpe,
            min_buy_calmar=self.min_buy_calmar if self.min_buy_calmar is not None else base.min_buy_calmar,
            max_buy_drawdown=self.max_buy_drawdown if self.max_buy_drawdown is not None else base.max_buy_drawdown,
            min_hold_sharpe=self.min_hold_sharpe if self.min_hold_sharpe is not None else base.min_hold_sharpe,
            max_hold_drawdown=self.max_hold_drawdown if self.max_hold_drawdown is not None else base.max_hold_drawdown,
            short_sharpe_ceiling=self.short_sharpe_ceiling if self.short_sharpe_ceiling is not None else base.short_sharpe_ceiling,
            short_drawdown_floor=self.short_drawdown_floor if self.short_drawdown_floor is not None else base.short_drawdown_floor,
        )


@dataclass(frozen=True)
class RecommendationPolicyConfig:
    """Policy configuration for risk-profile defaults and per-strategy overrides.

    The defaults provide a stable starting point; strategy-specific overrides can
    be used to calibrate thresholds for distinct holding periods or signal types.
    """

    risk_profiles: Mapping[str, RiskThresholds] = field(default_factory=lambda: RISK_THRESHOLDS)
    strategy_overrides: Mapping[str, RiskThresholdOverride] = field(default_factory=dict)


class RecommendationPolicy:
    """Recommendation policy with layered defaults and strategy overrides."""

    def __init__(self, config: RecommendationPolicyConfig | None = None):
        self.config = config or RecommendationPolicyConfig()

    def get_thresholds(self, risk_profile: str = "moderate", strategy_name: str | None = None) -> RiskThresholds:
        if risk_profile not in self.config.risk_profiles:
            raise ValueError(f"Unsupported risk profile '{risk_profile}'")

        thresholds = self.config.risk_profiles[risk_profile]
        if strategy_name and strategy_name in self.config.strategy_overrides:
            thresholds = self.config.strategy_overrides[strategy_name].apply(thresholds)
        return thresholds

    def evaluate(self, metrics: Mapping[str, float], risk_profile: str = "moderate", strategy_name: str | None = None) -> Dict[str, str]:
        thresholds = self.get_thresholds(risk_profile=risk_profile, strategy_name=strategy_name)

        required_metrics = ["sharpe_ratio", "calmar_ratio", "max_drawdown", "total_return"]
        missing = [name for name in required_metrics if name not in metrics]
        if missing:
            raise ValueError(f"Missing required metrics: {', '.join(missing)}")

        sharpe = float(metrics["sharpe_ratio"])
        calmar = float(metrics["calmar_ratio"])
        drawdown = abs(float(metrics["max_drawdown"]))
        total_return = float(metrics["total_return"])

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


def evaluate_recommendation(
    metrics: Mapping[str, float],
    risk_profile: str = "moderate",
    strategy_name: str | None = None,
    policy: RecommendationPolicy | None = None,
) -> Dict[str, str]:
    """Return a deterministic recommendation label based on risk-adjusted metrics."""
    return (policy or RecommendationPolicy()).evaluate(
        metrics,
        risk_profile=risk_profile,
        strategy_name=strategy_name,
    )
