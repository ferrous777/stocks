from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from strategies.plugin_manager import StrategyPluginManager


@dataclass
class PluginRuntimeResult:
    results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    failures: Dict[str, str] = field(default_factory=dict)


class StrategyPluginRuntime:
    """Runs discovered strategy plugins end-to-end against raw input data."""

    def __init__(self, manager: Optional[StrategyPluginManager] = None):
        self.manager = manager or StrategyPluginManager()

    def run(
        self,
        raw_data: Mapping[str, Any],
        risk_profile: str = "moderate",
    ) -> PluginRuntimeResult:
        load_result = self.manager.load_plugins()
        runtime_result = PluginRuntimeResult(failures=dict(load_result.failures))

        for plugin_name, plugin in load_result.loaded.items():
            try:
                prepared = plugin.prepare_data(raw_data)
                backtest_output = plugin.run_backtest(prepared)
                metrics = plugin.compute_metrics(backtest_output)
                recommendation = plugin.generate_recommendation(metrics, risk_profile=risk_profile)
                runtime_result.results[plugin_name] = {
                    "metrics": metrics,
                    "recommendation": recommendation,
                }
            except Exception as exc:
                runtime_result.failures[plugin_name] = str(exc)

        return runtime_result
