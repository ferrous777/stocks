from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple


@dataclass(frozen=True)
class StrategyMetadata:
    """Static metadata used by discovery and recommendation orchestration."""

    name: str
    version: str
    supported_asset_classes: Tuple[str, ...]
    holding_horizon: str


class StrategyPlugin(ABC):
    """Contract for Issue #3 strategy plug-ins."""

    metadata: StrategyMetadata

    @abstractmethod
    def prepare_data(self, raw_data: Mapping[str, Any]) -> Dict[str, Any]:
        """Normalize and validate raw input into a strategy-specific shape."""

    @abstractmethod
    def run_backtest(self, prepared_data: Mapping[str, Any]) -> Dict[str, Any]:
        """Execute backtest logic and return deterministic structured output."""

    @abstractmethod
    def compute_metrics(self, backtest_output: Mapping[str, Any]) -> Dict[str, float]:
        """Compute risk/performance metrics from backtest output."""

    @abstractmethod
    def generate_recommendation(
        self,
        metrics: Mapping[str, float],
        risk_profile: str = "moderate",
    ) -> Dict[str, Any]:
        """Generate recommendation payload from computed metrics."""
