from __future__ import annotations

import math
from typing import Dict, Iterable, List


def _to_list(values: Iterable[float]) -> List[float]:
    numbers = [float(v) for v in values]
    if not numbers:
        raise ValueError("Expected at least one return value")
    return numbers


def annualized_return(returns: Iterable[float], periods_per_year: int = 252) -> float:
    periodic_returns = _to_list(returns)
    cumulative = 1.0
    for value in periodic_returns:
        cumulative *= 1.0 + value
    years = len(periodic_returns) / float(periods_per_year)
    if years <= 0:
        raise ValueError("periods_per_year must produce a positive year fraction")
    return cumulative ** (1.0 / years) - 1.0


def sharpe_ratio(returns: Iterable[float], risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    periodic_returns = _to_list(returns)
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")

    rf_per_period = risk_free_rate / periods_per_year
    excess = [value - rf_per_period for value in periodic_returns]
    mean_excess = sum(excess) / len(excess)
    variance = sum((value - mean_excess) ** 2 for value in excess) / len(excess)
    std_dev = math.sqrt(variance)
    if std_dev == 0:
        return 0.0
    return (mean_excess / std_dev) * math.sqrt(periods_per_year)


def sortino_ratio(returns: Iterable[float], risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    periodic_returns = _to_list(returns)
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")

    rf_per_period = risk_free_rate / periods_per_year
    excess = [value - rf_per_period for value in periodic_returns]
    downside = [value for value in excess if value < 0]
    if not downside:
        return 0.0
    downside_variance = sum(value ** 2 for value in downside) / len(excess)
    downside_deviation = math.sqrt(downside_variance)
    if downside_deviation == 0:
        return 0.0
    mean_excess = sum(excess) / len(excess)
    return (mean_excess / downside_deviation) * math.sqrt(periods_per_year)


def max_drawdown(returns: Iterable[float]) -> float:
    periodic_returns = _to_list(returns)
    equity = 1.0
    peak = 1.0
    max_dd = 0.0

    for value in periodic_returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        drawdown = (equity - peak) / peak
        max_dd = min(max_dd, drawdown)

    return abs(max_dd)


def calmar_ratio(returns: Iterable[float], periods_per_year: int = 252) -> float:
    ann_return = annualized_return(returns, periods_per_year=periods_per_year)
    dd = max_drawdown(returns)
    if dd == 0:
        return 0.0
    return ann_return / dd


def profit_factor(trade_returns: Iterable[float]) -> float:
    realized = _to_list(trade_returns)
    gross_profit = sum(value for value in realized if value > 0)
    gross_loss = abs(sum(value for value in realized if value < 0))
    if gross_loss == 0:
        return 0.0 if gross_profit == 0 else float("inf")
    return gross_profit / gross_loss


def win_rate(trade_returns: Iterable[float]) -> float:
    realized = _to_list(trade_returns)
    wins = sum(1 for value in realized if value > 0)
    return wins / len(realized)


def summarize_performance(returns: Iterable[float], risk_free_rate: float = 0.0) -> Dict[str, float]:
    periodic_returns = _to_list(returns)
    return {
        "total_return": math.prod(1.0 + value for value in periodic_returns) - 1.0,
        "annualized_return": annualized_return(periodic_returns),
        "sharpe_ratio": sharpe_ratio(periodic_returns, risk_free_rate=risk_free_rate),
        "sortino_ratio": sortino_ratio(periodic_returns, risk_free_rate=risk_free_rate),
        "max_drawdown": max_drawdown(periodic_returns),
        "calmar_ratio": calmar_ratio(periodic_returns),
        "profit_factor": profit_factor(periodic_returns),
        "win_rate": win_rate(periodic_returns),
    }
