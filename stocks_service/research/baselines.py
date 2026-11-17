"""Benchmark equity curves over the same sessions and capital as a backtest.

* Buy-and-hold of one symbol (or a splice, e.g. QQQ before QQQM existed), dividends credited
  as cash that earns the T-bill rate.
* Cash at the 13-week T-bill rate (^IRX).
* Equal-weight buy-and-hold of the tradable universe members that have a bar on the first
  session — separates timing skill from the hindsight of a hand-picked universe.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from .backtest import _irx_rate
from .series import SymbolSeries


def cash_curve(irx: SymbolSeries, days: list[dt.date], initial: float) -> list[float]:
    out, v = [], initial
    for i, d in enumerate(days):
        out.append(v)
        if i + 1 < len(days):
            v *= 1 + _irx_rate(irx, d) * (days[i + 1] - d).days / 360
    return out


def cash_daily_returns(irx: SymbolSeries, days: list[dt.date]) -> np.ndarray:
    c = cash_curve(irx, days, 1.0)
    return np.asarray(c[1:]) / np.asarray(c[:-1]) - 1


def _hold_values(series: SymbolSeries, days: list[dt.date], irx: SymbolSeries, capital: float,
                 start_index: int = 0) -> list[float]:
    """Buy at the first session's close (decision basis of that day), hold, dividends to cash."""
    d0 = days[start_index]
    price0 = series.close_on_basis(d0, d0)
    qty = capital / price0
    divs = dict(series.dividends_on_basis(d0))
    cash, out = 0.0, []
    for i, d in enumerate(days[start_index:], start=start_index):
        if d in divs:
            cash += divs[d] * qty
        out.append(qty * series.close_on_basis(d0, d) + cash)
        if i + 1 < len(days):
            cash *= 1 + _irx_rate(irx, d) * (days[i + 1] - d).days / 360
    return out


def buy_and_hold(series: SymbolSeries, days: list[dt.date], irx: SymbolSeries, initial: float) -> list[float]:
    if series.count_through(days[0]) == 0 or series.sessions[series.count_through(days[0]) - 1] != days[0]:
        raise ValueError(f"{series.symbol} has no bar on {days[0]}")
    return _hold_values(series, days, irx, initial)


def spliced_buy_and_hold(primary: SymbolSeries, fallback: SymbolSeries, switch: dt.date, days: list[dt.date],
                         irx: SymbolSeries, initial: float) -> list[float]:
    """Hold ``fallback`` through the first session on/after ``switch``, then roll the whole value into
    ``primary`` at that session's close and hold it (e.g. QQQ before QQQM's 2020-10-13 inception)."""
    if days[0] >= switch:
        return buy_and_hold(primary, days, irx, initial)
    k = next((i for i, d in enumerate(days) if d >= switch), None)
    if k is None:
        return buy_and_hold(fallback, days, irx, initial)
    first = _hold_values(fallback, days[: k + 1], irx, initial)
    rolled = _hold_values(primary, days, irx, first[k], start_index=k)
    return first[:k] + rolled


def equal_weight(universe: dict[str, SymbolSeries], members: list[str], days: list[dt.date], irx: SymbolSeries,
                 initial: float) -> tuple[list[float], list[str]]:
    held = [m for m in members if universe[m].count_through(days[0]) > 0
            and universe[m].sessions[universe[m].count_through(days[0]) - 1] == days[0]]
    if not held:
        raise ValueError("no universe member has a bar on the first session")
    per = initial / len(held)
    curves = [_hold_values(universe[m], days, irx, per) for m in held]
    return list(np.sum(np.asarray(curves), axis=0)), held
