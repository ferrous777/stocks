from datetime import datetime, timedelta

from market_data.data_types import DataPoint, HistoricalData
from strategies.strategy import Strategy


class DummyAliasStrategy(Strategy):
    def __init__(self):
        super().__init__(name="DummyAlias", description="Alias test strategy")

    def requires_fundamentals(self) -> bool:
        return False

    def get_min_required_points(self) -> int:
        return 1

    def analyze(self, date=None):
        return {}

    def _calculate_strategy_metrics(self, trades):
        return {}

    def generate_signals(self, data_points, index):
        # Enter using buy/sell aliases and then exit deterministically.
        if index == 1:
            return "buy", 0.8, "enter long"
        if index == 2:
            return "exit", 0.7, "exit long"
        if index == 3:
            return "sell", 0.8, "enter short"
        if index == 4:
            return "exit", 0.7, "exit short"
        return "hold", 0.0, "hold"


def _build_history(symbol="TEST", days=8):
    start = datetime(2025, 1, 1)
    prices = [100.0, 101.0, 103.0, 102.0, 99.0, 98.0, 100.0, 101.0]
    points = []
    for i in range(days):
        close = prices[i]
        points.append(
            DataPoint(
                date=(start + timedelta(days=i)).strftime("%Y-%m-%d"),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1_000_000,
            )
        )
    return HistoricalData(symbol=symbol, data_points=points)


def test_backtest_executes_buy_sell_alias_signals():
    strategy = DummyAliasStrategy()
    history = _build_history()
    strategy.add_data("TEST", history)

    start_date = datetime(2025, 1, 1)
    end_date = datetime(2025, 1, 8)
    results = strategy.backtest(start_date, end_date)

    assert "TEST" in results
    result = results["TEST"]
    assert result.total_trades == 2
    assert result.strategy_returns.total_trades_executed == 2
