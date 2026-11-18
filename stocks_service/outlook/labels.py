"""Outcome labels: what happened to every plan the pipeline would have produced in the past.

For sampled sessions ``d`` (every ``STRIDE``-th XNYS session, shared by all symbols) and every
symbol with a bar on ``d``:

* **Signal labels:** each strategy decides from the point-in-time view at ``d``; a long/short
  decision becomes an ATR plan simulated by the shared ``exec_daily_v1`` simulator.
* **Base-rate labels** (strategy ``BASE``): the same ATR plan in *both* directions, whatever the
  strategies say. These give each symbol's unconditional outcome distribution and the
  "neutral-state" estimate for symbols without an active signal.

Each label stores the net trade return under an explicit cost profile for a reference
position of ``REFERENCE_NOTIONAL`` dollars, and its **excess over T-bills**: net return minus
the ^IRX rate (known at ``d``) accrued over the calendar days the capital was in the trade.
Outside the trade the capital earns the same T-bill rate either way, so this excess is the
trade's contribution to a six-month (126-session) horizon return. Not-filled plans have
excess 0. Unresolved plans (data ends first) are not labels.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .. import sessions
from ..levels import LevelsUnavailable, atr_levels
from ..research.backtest import PolicyParams, _irx_rate
from ..research.series import SymbolSeries
from ..sim import CostProfile, DataGapError, ExecutionPolicy, TradePlan, net_trade, simulate_trade
from ..strategies import decide, get_spec

LABEL_VERSION = "labels@1"
BASE = "base_rate"
STRIDE = 5
REFERENCE_NOTIONAL = 10_000.0


@dataclass(slots=True)
class Label:
    strategy: str
    symbol: str
    side: str
    decided: dt.date
    resolved: dt.date     # session on which the outcome became known
    result: str
    net_return: float
    excess: float         # net_return minus T-bill accrual while invested
    sessions_held: int | None


def sample_sessions(start: dt.date, end: dt.date) -> list[dt.date]:
    """Every STRIDE-th calendar session (anchored on the calendar start, so independent of ``start``)."""
    return [d for d in sessions.sessions_between(start, end) if sessions.session_number(d) % STRIDE == 0]


def _label(series: SymbolSeries, irx: SymbolSeries, strategy: str, side: str, d: dt.date, view, lv_params: dict,
           cost: CostProfile, policy: ExecutionPolicy, horizon_bars: int) -> Label | None:
    lv = atr_levels(view, side, lv_params)
    plan = TradePlan(side, d, lv.entry_limit, lv.stop, lv.target)
    bars = series.bars_after(d, horizon_bars)
    nxt = sessions.next_session(d)
    if not bars or bars[0].session != nxt:
        return None
    oc = simulate_trade(plan, bars, nxt, policy)
    if oc.result == "unresolved":
        return None
    if oc.result == "not_filled":
        return Label(strategy, series.symbol, side, d, nxt, "not_filled", 0.0, 0.0, None)
    qty = REFERENCE_NOTIONAL / oc.fill_price
    nt = net_trade(oc, side, qty, cost, series.dividends_on_basis(d))
    cash = _irx_rate(irx, d) * (oc.exit_session - oc.fill_session).days / 360
    return Label(strategy, series.symbol, side, d, oc.exit_session, oc.result, nt.net_return,
                 nt.net_return - cash, oc.sessions_held)


def build_labels(universe: dict[str, SymbolSeries], symbols: list[str], irx: SymbolSeries, strategies: list[str],
                 start: dt.date, end: dt.date, cost: CostProfile, *, resolved_before: dt.date,
                 policy: ExecutionPolicy = ExecutionPolicy(), params: PolicyParams = PolicyParams(),
                 log=None) -> tuple[list[Label], dict]:
    """Labels for decisions in [start, end] whose outcome resolved strictly before ``resolved_before``."""
    specs = [get_spec(k) for k in strategies]
    lv_params = params.levels_dict
    horizon_bars = policy.timeout_sessions + 3
    days = sample_sessions(start, end)
    labels: list[Label] = []
    stats = {"sampled_sessions": len(days), "data_gaps": 0, "no_levels": 0, "unresolved": 0}
    for n, sym in enumerate(symbols):
        series = universe[sym]
        for d in days:
            if d >= resolved_before or not series.has_bar(d):
                continue
            view = series.view_at(d)
            wanted = [(BASE, "long"), (BASE, "short")]
            for spec in specs:
                if series.count_through(d) >= spec.min_bars:
                    dec = decide(view, spec)
                    if dec.direction in ("long", "short"):
                        wanted.append((spec.key, dec.direction))
            outcomes: dict[str, Label | None] = {}
            for strategy, side in wanted:
                if side not in outcomes:  # the plan depends only on (symbol, d, side): simulate once
                    try:
                        outcomes[side] = _label(series, irx, BASE, side, d, view, lv_params, cost, policy, horizon_bars)
                    except LevelsUnavailable:
                        outcomes[side] = None
                        stats["no_levels"] += 1
                    except DataGapError:
                        outcomes[side] = None
                        stats["data_gaps"] += 1
                    if outcomes[side] is None or outcomes[side].resolved >= resolved_before:
                        if outcomes[side] is not None:
                            stats["unresolved"] += 1
                        outcomes[side] = None
                lab = outcomes[side]
                if lab is not None:
                    labels.append(lab if strategy == BASE else Label(strategy, *(
                        getattr(lab, f) for f in ("symbol", "side", "decided", "resolved", "result", "net_return",
                                                  "excess", "sessions_held"))))
        if log and (n + 1) % 10 == 0:
            log(step="labels", symbols_done=n + 1, labels=len(labels))
    stats["labels"] = len(labels)
    return labels, stats
