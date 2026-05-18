import math

import pytest

from analysis.performance_metrics import (
    annualized_return,
    calmar_ratio,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    summarize_performance,
    win_rate,
)


def test_summary_contains_expected_metric_keys():
    summary = summarize_performance([0.01, -0.02, 0.03, 0.01])
    assert set(summary.keys()) == {
        "total_return",
        "annualized_return",
        "sharpe_ratio",
        "sortino_ratio",
        "max_drawdown",
        "calmar_ratio",
        "profit_factor",
        "win_rate",
    }


def test_drawdown_and_win_rate_values():
    returns = [0.1, -0.2, 0.05, -0.1]
    assert max_drawdown(returns) > 0
    assert win_rate(returns) == 0.5


def test_profit_factor_infinite_when_no_losses():
    assert profit_factor([0.02, 0.01]) == float("inf")


def test_ratios_are_numeric_for_mixed_returns():
    returns = [0.015, -0.01, 0.005, -0.002, 0.01]
    assert math.isfinite(sharpe_ratio(returns))
    assert math.isfinite(sortino_ratio(returns))
    assert math.isfinite(calmar_ratio(returns))
    assert math.isfinite(annualized_return(returns))


def test_empty_returns_raise_value_error():
    with pytest.raises(ValueError):
        summarize_performance([])
