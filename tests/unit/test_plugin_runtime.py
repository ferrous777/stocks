from strategies.plugin_runtime import StrategyPluginRuntime
from strategies.plugin_manager import PluginLoadResult


class _GoodPlugin:
    def prepare_data(self, raw_data):
        return dict(raw_data)

    def run_backtest(self, prepared_data):
        return {"prepared": prepared_data}

    def compute_metrics(self, backtest_output):
        return {
            "sharpe_ratio": 2.2,
            "calmar_ratio": 2.1,
            "max_drawdown": 0.1,
            "total_return": 0.2,
        }

    def generate_recommendation(self, metrics, risk_profile="moderate"):
        return {"action": "buy", "risk_profile": risk_profile}


class _BadPlugin:
    def prepare_data(self, raw_data):
        raise RuntimeError("failed prepare")

    def run_backtest(self, prepared_data):
        return {}

    def compute_metrics(self, backtest_output):
        return {}

    def generate_recommendation(self, metrics, risk_profile="moderate"):
        return {"action": "avoid"}


class _StubManager:
    def load_plugins(self):
        return PluginLoadResult(
            loaded={"good": _GoodPlugin(), "bad": _BadPlugin()},
            failures={"strategies.broken_module": "import error"},
        )


def test_plugin_runtime_runs_good_plugins_and_collects_failures():
    runtime = StrategyPluginRuntime(manager=_StubManager())

    result = runtime.run({"symbol": "AAPL"}, risk_profile="conservative")

    assert "good" in result.results
    assert result.results["good"]["recommendation"]["action"] == "buy"
    assert result.results["good"]["recommendation"]["risk_profile"] == "conservative"
    assert "bad" in result.failures
    assert "strategies.broken_module" in result.failures
