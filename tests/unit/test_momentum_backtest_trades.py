from datetime import datetime, timedelta

from market_data.data_types import DataPoint, HistoricalData
from strategies.momentum import MomentumStrategy


def _build_trending_history(symbol="TEST"):
    start = datetime(2025, 1, 1)
    prices = []

    # Uptrend block with strong ROC
    prices.extend([100 + i * 1.8 for i in range(20)])
    # Flat/slow block to allow fade/exit conditions
    prices.extend([prices[-1] + (0.03 if i % 2 == 0 else -0.02) for i in range(10)])
    # Downtrend block with strong negative ROC
    prices.extend([prices[-1] - i * 1.4 for i in range(1, 21)])

    points = []
    for idx, close in enumerate(prices):
        points.append(
            DataPoint(
                date=(start + timedelta(days=idx)).strftime("%Y-%m-%d"),
                open=close,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume=1_000_000 + (idx * 1000),
            )
        )

    return HistoricalData(symbol=symbol, data_points=points)


def test_momentum_backtest_executes_trades_on_trending_data():
    strategy = MomentumStrategy()
    history = _build_trending_history()
    strategy.add_data("TEST", history)

    start_date = datetime(2025, 1, 1)
    end_date = datetime(2025, 3, 31)

    results = strategy.backtest(start_date, end_date)
    assert "TEST" in results
    assert results["TEST"].strategy_returns.total_trades_executed > 0
