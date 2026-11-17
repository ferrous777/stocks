"""Regression tests for legacy fixes kept while the PythonAnywhere app still runs this code."""

import json
from datetime import datetime
from pathlib import Path

from market_data.data_types import DataPoint, HistoricalData
from strategies.ensemble import EnsembleStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.strategy import Strategy

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "yahoo" / "INTC_1d_2020-06-01_2025-06-02.json"


def _history(symbol="INTC"):
    res = json.loads(FIXTURE.read_text())["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    pts = []
    for i, ts in enumerate(res["timestamp"]):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            continue
        pts.append(DataPoint(date=datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"), open=q["open"][i],
                             high=q["high"][i], low=q["low"][i], close=q["close"][i], volume=q["volume"][i] or 0))
    return HistoricalData(symbol=symbol, data_points=pts)


class _ShortOnce(Strategy):
    """Enters one short on the first eligible bar, then holds."""

    def __init__(self):
        super().__init__("short_once", "test")

    def get_min_required_points(self):
        return 1

    def generate_signals(self, data_points, index):
        return ("short", 1.0, "") if index == 1 else ("hold", 0.0, "")

    def analyze(self, date=None):
        return {}

    def requires_fundamentals(self):
        return False

    def _calculate_strategy_metrics(self, trades):
        return {}


def test_short_stop_and_target_are_on_the_correct_side():
    """Legacy computed stop = close * -0.08, so every short 'stopped out' on the next bar."""
    s = _ShortOnce()
    s.add_data("INTC", _history())
    result = s.backtest(datetime(2020, 6, 1), datetime(2025, 6, 2))["INTC"]
    trade = result.trades[0]
    held = (trade.exit_date - trade.entry_date).days
    assert held > 1
    move = trade.exit_price / trade.entry_price - 1
    # Exit happened at the +8% stop, the -15% target, or the end of data — not on an arbitrary next bar.
    assert move >= 0.08 or move <= -0.15 or trade.exit_date.date().isoformat() == "2025-06-02"


def test_ensemble_accepts_buy_sell_vocabulary():
    """Legacy ensemble raised KeyError('buy') when momentum or mean reversion voted."""
    hist = _history()
    ens = EnsembleStrategy([MomentumStrategy(), MeanReversionStrategy()])
    ens.add_data("INTC", hist)
    for i in range(30, len(hist.data_points), 25):
        signal, confidence, _ = ens.generate_signals(hist.data_points, i)
        assert signal in ("long", "short", "exit", "hold")
        assert 0.0 <= confidence <= 1.0
