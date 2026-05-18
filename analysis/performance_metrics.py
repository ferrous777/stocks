from __future__ import annotations

import math
from typing import Dict, Iterable, List


def _to_list(values: Iterable[float]) -> List[float]:
    numbers = [float(v) for v in values]
    if not numbers:
        raise ValueError("Expected at least one return value")
    return numbers


def annualized_return(returns: Iterable[float], periods_per_year: int = 252) -> float:
    """Compute annualized return from periodic returns."""
    periodic_returns = _to_list(returns)
    cumulative = 1.0
    for value in periodic_returns:
        cumulative *= 1.0 + value
    years = len(periodic_returns) / float(periods_per_year)
    if years <= 0:
        raise ValueError("periods_per_year must produce a positive year fraction")
    return cumulative ** (1.0 / years) - 1.0


def sharpe_ratio(returns: Iterable[float], risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    """Compute the annualized Sharpe ratio."""
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
    """Compute the annualized Sortino ratio."""
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
    """Compute maximum drawdown as a fraction of peak equity."""
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
    """Compute the Calmar ratio using annualized return and max drawdown."""
    ann_return = annualized_return(returns, periods_per_year=periods_per_year)
    dd = max_drawdown(returns)
    if dd == 0:
        return 0.0
    return ann_return / dd


def volatility(returns: Iterable[float], periods_per_year: int = 252) -> float:
    """Compute annualized volatility from periodic returns."""
    periodic_returns = _to_list(returns)
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")

    mean_return = sum(periodic_returns) / len(periodic_returns)
    variance = sum((value - mean_return) ** 2 for value in periodic_returns) / len(periodic_returns)
    return math.sqrt(variance) * math.sqrt(periods_per_year)


def drawdown_duration(returns: Iterable[float]) -> int:
    """Compute the longest consecutive drawdown duration in periods."""
    periodic_returns = _to_list(returns)
    equity = 1.0
    peak = 1.0
    current_duration = 0
    longest_duration = 0

    for value in periodic_returns:
        equity *= 1.0 + value
        if equity < peak:
            current_duration += 1
            longest_duration = max(longest_duration, current_duration)
        else:
            peak = equity
            current_duration = 0

    return longest_duration


def profit_factor(trade_returns: Iterable[float]) -> float:
    """Compute profit factor as gross profit divided by gross loss."""
    realized = _to_list(trade_returns)
    gross_profit = sum(value for value in realized if value > 0)
    gross_loss = abs(sum(value for value in realized if value < 0))
    if gross_loss == 0:
        return 0.0 if gross_profit == 0 else float("inf")
    return gross_profit / gross_loss


def win_rate(trade_returns: Iterable[float]) -> float:
    """Compute the fraction of positive-return periods."""
    realized = _to_list(trade_returns)
    wins = sum(1 for value in realized if value > 0)
    return wins / len(realized)


def summarize_performance(
    returns: Iterable[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> Dict[str, float]:
    """Summarize a return series for backtest reporting.

    Args:
        returns: Periodic return series.
        risk_free_rate: Annual risk-free rate used for risk-adjusted ratios.
        periods_per_year: Number of return periods in a year for annualization.
    """
    periodic_returns = _to_list(returns)
    return {
        "total_return": math.prod(1.0 + value for value in periodic_returns) - 1.0,
        "annualized_return": annualized_return(periodic_returns, periods_per_year=periods_per_year),
        "volatility": volatility(periodic_returns, periods_per_year=periods_per_year),
        "sharpe_ratio": sharpe_ratio(
            periodic_returns,
            risk_free_rate=risk_free_rate,
            periods_per_year=periods_per_year,
        ),
        "sortino_ratio": sortino_ratio(
            periodic_returns,
            risk_free_rate=risk_free_rate,
            periods_per_year=periods_per_year,
        ),
        "max_drawdown": max_drawdown(periodic_returns),
        "drawdown_duration": drawdown_duration(periodic_returns),
        "calmar_ratio": calmar_ratio(periodic_returns, periods_per_year=periods_per_year),
        "profit_factor": profit_factor(periodic_returns),
        "win_rate": win_rate(periodic_returns),
    }
